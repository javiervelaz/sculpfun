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

import math
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


# ------------------------------------------------------- offset de polígonos


def signed_area(points: list[Point]) -> float:
    """Área con signo. Positiva si el polígono está en sentido antihorario."""
    total = 0.0
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        total += x0 * y1 - x1 * y0
    return total / 2.0


def offset_polygon(points: list[Point], distance: float) -> list[Point]:
    """Desplaza cada lado del polígono `distance` mm hacia afuera del material.

    Es la generalización de `compensated_rect` a cualquier contorno cerrado,
    y es lo que permite compensar el kerf en una pieza con muescas: basta con
    correr **todo** el borde del material hacia afuera. Donde el borde encierra
    material (el perímetro) eso lo agranda; donde encierra vacío (una muesca,
    una ranura abierta a un canto) el mismo desplazamiento lo angosta, que es
    justo lo que hace falta. Un solo signo para toda la pieza.

    `distance` positivo agranda, negativo achica. Para cortar:

        perímetro de la pieza (PART)  ->  +kerf/2
        agujero interior (HOLE)       ->  -kerf/2

    Los lados casi paralelos no generan vértice y se dejan como están: con los
    desplazamientos de este proyecto (décimas de milímetro) no hay recorte que
    valga la pena.
    """
    pts = list(points)
    if len(pts) > 2 and math.isclose(pts[0][0], pts[-1][0], abs_tol=1e-9) \
            and math.isclose(pts[0][1], pts[-1][1], abs_tol=1e-9):
        pts = pts[:-1]
    if len(pts) < 3:
        raise ValueError("hacen falta al menos 3 puntos para desplazar un contorno")

    flipped = signed_area(pts) < 0
    if flipped:
        pts.reverse()

    edges: list[tuple[Point, Point]] = []
    for index in range(len(pts)):
        x0, y0 = pts[index]
        x1, y1 = pts[(index + 1) % len(pts)]
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy)
        if length < 1e-12:
            continue  # punto repetido: no define un lado
        ux, uy = dx / length, dy / length
        # Normal exterior de un polígono antihorario.
        nx, ny = uy, -ux
        edges.append(((x0 + nx * distance, y0 + ny * distance), (ux, uy)))

    if len(edges) < 3:
        raise ValueError("el contorno degeneró: no quedan 3 lados con longitud")

    out: list[Point] = []
    for index in range(len(edges)):
        (px, py), (dx, dy) = edges[index - 1]
        (qx, qy), (ex, ey) = edges[index]
        cross = dx * ey - dy * ex
        if abs(cross) < 1e-9:
            out.append((qx, qy))  # lados paralelos: no hay vértice que cortar
            continue
        t = ((qx - px) * ey - (qy - py) * ex) / cross
        out.append((px + dx * t, py + dy * t))

    if flipped:
        out.reverse()
    return out


def compensate(points: list[Point], *, kerf: float, role: str) -> list[Point]:
    """Aplica el kerf a un contorno según su rol. Con kerf 0 no toca nada."""
    if role not in ROLES:
        raise ValueError(f"rol invalido: {role!r}. Opciones: {', '.join(ROLES)}")
    if not kerf:
        return list(points)
    return offset_polygon(points, kerf / 2.0 if role == PART else -kerf / 2.0)


# ------------------------------------------------------------------- arcos


def arc_points(
    cx: float, cy: float, radius: float, start: float, end: float, through: float,
    *, max_segment_mm: float = 0.3,
) -> list[Point]:
    """Puntos de un arco de `start` a `end` (radianes) que pasa por `through`.

    El tercer ángulo desempata el sentido de giro, que es la única parte de
    dibujar un arco donde uno se equivoca en silencio y se entera cuando ve
    la pieza cortada al revés.
    """
    two_pi = 2.0 * math.pi
    sweep = (end - start) % two_pi              # barrido antihorario
    offset = (through - start) % two_pi
    if offset > sweep:                          # el punto testigo no cae adentro
        sweep -= two_pi                         # entonces se gira al revés
    steps = max(2, math.ceil(abs(sweep) * radius / max_segment_mm))
    return [
        (cx + radius * math.cos(start + sweep * i / steps),
         cy + radius * math.sin(start + sweep * i / steps))
        for i in range(steps + 1)
    ]


def notch(
    x_center: float, y_open: float, y_root: float, width: float,
    *, relief_diameter: float = 0.0, max_segment_mm: float = 0.3,
) -> list[Point]:
    """Muesca vertical abierta a un canto, con alivio circular en la raíz.

    Devuelve los puntos desde el canto de un lado hasta el canto del otro,
    para intercalar en el contorno de la pieza. `y_open` es el borde por donde
    entra la otra pieza y `y_root` el fondo.

    El alivio no es decoración. Hace dos cosas que se pagan caro sin él: saca
    el esquinero interno vivo, que en MDF es por donde arranca la fisura, y le
    da lugar al radio que el láser deja en la esquina de la otra pieza, para
    que asiente hasta el fondo en vez de quedar trabada un milímetro antes.
    """
    half = width / 2.0
    left, right = x_center - half, x_center + half
    sign = 1.0 if y_root > y_open else -1.0
    radius = relief_diameter / 2.0

    if radius <= half + 1e-9:
        # Sin alivio (o demasiado chico para asomar): esquina viva.
        return [(left, y_open), (left, y_root), (right, y_root), (right, y_open)]

    inset = math.sqrt(radius * radius - half * half)
    y_meet = y_root - sign * inset
    start = math.atan2(y_meet - y_root, left - x_center)
    end = math.atan2(y_meet - y_root, right - x_center)
    through = math.atan2(sign * radius, 0.0)

    return (
        [(left, y_open), (left, y_meet)]
        + arc_points(x_center, y_root, radius, start, end, through,
                     max_segment_mm=max_segment_mm)
        + [(right, y_meet), (right, y_open)]
    )
