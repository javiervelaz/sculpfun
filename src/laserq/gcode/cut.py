"""Corte vectorial: multipasada, compensación de kerf y orden de recorrido.

Grabar y cortar no son la misma operación con otros números. Cortar necesita
tres cosas que el generador de grabado no tiene, y las tres deciden si la
pieza sirve o va a la basura.

Multipasada
-----------
Un diodo no atraviesa 6 mm de una. Se repite el mismo contorno N veces, y se
repite **contorno por contorno**, no el programa entero: el material ya está
caliente y el aire ya está soplando en esa ranura, así que la segunda pasada
rinde bastante más ahí que después de dar toda la vuelta al dibujo.

Kerf
----
El láser no corta *sobre* la línea: se come un canal de ancho `kerf` centrado
en ella. Entonces una ranura dibujada de 6.0 mm queda de 6.0 + kerf, y una
pieza dibujada de 6.0 mm queda de 6.0 - kerf. Esa diferencia es exactamente
la que separa "encastra" de "baila".

    ranura (HOLE): se dibuja MÁS ANGOSTA que la medida final
    pieza  (PART): se dibuja MÁS ANCHA  que la medida final

El kerf no es una constante universal: cambia con el material, el espesor, el
foco y la cantidad de pasadas. Se mide con `laserq kerf-comb` y se guarda en
el perfil del material, como cualquier otro valor ganado quemando una prueba.

Orden
-----
Los interiores se cortan antes que el contorno. Al revés, la pieza se suelta
cuando termina el perímetro y las ranuras que faltan salen corridas — o peor,
la pieza se mueve y el cabezal la arrastra.

Acá el rol de cada contorno es explícito y no adivinado: los generadores de
este proyecto saben qué están dibujando. El día que entre importación de SVG
habrá que deducirlo por contención, y ese cálculo va en este módulo.
"""

from __future__ import annotations

from dataclasses import dataclass

from .builder import GcodeProgram

#: Contorno interior: una ranura, un agujero, cualquier cosa que se descarta.
HOLE = "hole"
#: Contorno exterior: el perímetro de la pieza que te querés quedar.
PART = "part"
ROLES = (HOLE, PART)

Point = tuple[float, float]


@dataclass
class Contour:
    """Un camino cerrado o abierto, con su rol declarado.

    El rol no es decorativo: define el signo de la compensación de kerf y el
    orden en que se corta.
    """

    points: list[Point]
    role: str = PART
    closed: bool = True
    #: Pasadas propias. None = usa las de CutOptions. Sirve para una placa de
    #: test donde cada celda lleva una cantidad distinta.
    passes: int | None = None

    def __post_init__(self) -> None:
        if self.role not in ROLES:
            raise ValueError(f"rol invalido: {self.role!r}. Opciones: {', '.join(ROLES)}")


@dataclass
class CutOptions:
    """Parámetros de una operación de corte."""

    speed: int = 300  # mm/min
    power: int = 1000  # 0..$30; cortando casi siempre es el máximo
    passes: int = 1
    #: Ancho del canal que se come el láser, en mm. 0 = sin compensar.
    kerf_mm: float = 0.0

    @classmethod
    def from_profile(cls, profile) -> "CutOptions":
        """Arma las opciones desde un MaterialProfile.

        Acá es donde `passes` del perfil deja de ser decorativo: el generador
        de grabado lo ignora porque una foto no se graba dos veces, pero un
        corte sí.
        """
        return cls(
            speed=profile.speed,
            power=profile.power,
            passes=max(1, profile.passes),
            kerf_mm=profile.kerf_mm,
        )


def compensated_rect(
    x: float, y: float, width: float, height: float, *, kerf: float, role: str
) -> list[Point]:
    """Rectángulo listo para cortar, con el kerf ya compensado.

    `(x, y, width, height)` describen la medida **final deseada**, no el
    camino: para una ranura de 6 mm de ancho pedís 6 y el camino sale de
    6 - kerf. El centro del rectángulo no se mueve.

    >>> [round(p[0], 3) for p in compensated_rect(0, 0, 6, 30, kerf=0.2, role=HOLE)]
    [0.1, 5.9, 5.9, 0.1]
    >>> [round(p[0], 3) for p in compensated_rect(0, 0, 6, 30, kerf=0.2, role=PART)]
    [-0.1, 6.1, 6.1, -0.1]
    """
    if role not in ROLES:
        raise ValueError(f"rol invalido: {role!r}. Opciones: {', '.join(ROLES)}")
    offset = -kerf / 2.0 if role == HOLE else kerf / 2.0
    if role == HOLE and (width + 2 * offset <= 0 or height + 2 * offset <= 0):
        raise ValueError(
            f"el kerf ({kerf:g} mm) se come la ranura de {width:g}x{height:g} mm: "
            f"no queda camino que recorrer"
        )
    return [
        (x - offset, y - offset),
        (x + width + offset, y - offset),
        (x + width + offset, y + height + offset),
        (x - offset, y + height + offset),
    ]


def slot(x: float, y: float, width: float, height: float, *, kerf: float = 0.0) -> Contour:
    """Atajo para una ranura de medida final `width` x `height`."""
    return Contour(
        compensated_rect(x, y, width, height, kerf=kerf, role=HOLE),
        role=HOLE,
    )


def outline(x: float, y: float, width: float, height: float, *, kerf: float = 0.0) -> Contour:
    """Atajo para el perímetro de una pieza de medida final `width` x `height`."""
    return Contour(
        compensated_rect(x, y, width, height, kerf=kerf, role=PART),
        role=PART,
    )


def order_contours(contours: list[Contour]) -> list[Contour]:
    """Interiores primero, perímetros después. Estable dentro de cada grupo."""
    return [c for c in contours if c.role == HOLE] + [c for c in contours if c.role == PART]


def cut_contours(
    program: GcodeProgram, contours: list[Contour], options: CutOptions
) -> GcodeProgram:
    """Emite los contornos ordenados, repitiendo cada uno sus pasadas."""
    for contour in order_contours(contours):
        passes = contour.passes if contour.passes is not None else options.passes
        for _ in range(max(1, passes)):
            program.polyline(
                contour.points,
                feed=options.speed,
                power=options.power,
                closed=contour.closed,
            )
    return program
