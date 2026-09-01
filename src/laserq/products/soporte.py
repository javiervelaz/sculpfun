"""Soporte para notebook: dos piezas de chapa fina que se cruzan a 90°.

Con dos piezas planas la única forma de que se sostengan solas es que se
crucen, así que el soporte son dos perfiles con una muesca a media altura
que encastran uno dentro del otro:

* **T (transversal)**: rectángulo, la muesca baja desde el canto superior.
  Es la que se ve de frente y la que lleva el grabado.
* **L (longitudinal)**: canto superior inclinado, la muesca sube desde la
  base. Es la que le da el ángulo a la notebook.

Lo que hace que el diseño funcione es que el tope de la T queda **al ras**
del canto inclinado de la L justo en el cruce. La notebook apoya sobre dos
líneas que se cortan y queda firme en los dos ejes. Un milímetro de más en
la T y se hamaca sobre ella.

Todo se dibuja en **medidas finales** y la compensación del kerf se aplica
una sola vez, al final, corriendo todo el borde del material hacia afuera:
el perímetro se agranda y las muescas se angostan con el mismo signo. Por
eso `notch()` recibe el espesor de la plancha y no el ancho de ranura ya
compensado — el ancho compensado sale solo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..gcode.builder import GcodeOptions, GcodeProgram
from ..gcode.cut import (
    HOLE,
    PART,
    Contour,
    CutOptions,
    arc_points,
    compensate,
    cut_contours,
    notch,
)
from ..gcode.font import text_polylines, text_width, thicken, unsupported

Point = tuple[float, float]

#: Grabado si no hay un perfil a mano. Conservador: marcar de menos se
#: arregla con otra pasada, quemar de más no.
GRABADO_FEED = 2500
GRABADO_POWER = 300

#: Configuraciones probadas. El alto es para usar con teclado externo; el
#: bajo, para tipear en la notebook misma sin levantar las manos.
PRESETS: dict[str, dict[str, float]] = {
    "alto": {"altura": 100.0, "fondo": 220.0, "angulo": 15.0},
    "bajo": {"altura": 55.0, "fondo": 200.0, "angulo": 14.0},
}


@dataclass
class SoporteSpec:
    """Todo el soporte, en parámetros. Ninguna medida está en el código."""

    #: Largo de la transversal. Conviene menor que el ancho de la notebook.
    ancho: float = 300.0
    #: Largo de la longitudinal, o sea la profundidad de la base.
    fondo: float = 220.0
    #: Altura en el punto de cruce. Es la elevación efectiva del soporte.
    altura: float = 100.0
    #: Inclinación del apoyo, en grados.
    angulo: float = 15.0

    #: Espesor REAL de la plancha, medido con calibre. Varía entre lotes de
    #: MDF más de lo que uno espera, así que es parámetro por tirada y no un
    #: valor fijo del perfil.
    espesor: float = 2.9
    kerf: float = 0.25
    #: Alivio en la raíz de cada muesca. Tiene que ser mayor que el espesor
    #: o no asoma y no sirve de nada.
    alivio: float = 3.5

    nombre: str = ""
    marca: str = ""
    #: "izq" o "der". El nombre NO va centrado en la pieza: el centro es
    #: justo donde se para la otra mitad del encastre y el texto queda
    #: partido al medio y tapado. Va centrado en un ala.
    nombre_lado: str = "izq"
    grabado_alto_max: float = 20.0
    grabado_alto_min: float = 8.0
    marca_alto: float = 7.0
    #: Ancho agregado al trazo, en mm. La fuente es de trazo único y sin esto
    #: la letra queda del ancho del kerf: se ve si la buscás.
    grosor: float = 0.0

    pasa_cables: bool = True
    pasa_cables_mm: tuple[float, float] = (45.0, 12.0)

    margen: float = 10.0
    separacion: float = 12.0

    # ------------------------------------------------------------ derivados

    @property
    def desnivel(self) -> float:
        """Cuánto sube el canto de la L entre el frente y el fondo."""
        return self.fondo * math.tan(math.radians(self.angulo))

    @property
    def altura_frente(self) -> float:
        return self.altura - self.desnivel / 2.0

    @property
    def altura_fondo(self) -> float:
        return self.altura + self.desnivel / 2.0

    @property
    def profundidad_muesca(self) -> float:
        """Media altura: las dos piezas se parten por la mitad en el cruce."""
        return self.altura / 2.0

    @property
    def ranura_dibujada(self) -> float:
        """Ancho real del camino después de compensar. Solo informativo."""
        return round(self.espesor - self.kerf, 3)

    @property
    def grabado_ancho(self) -> float:
        """Ancho útil del ala donde va el nombre."""
        return self.ancho / 2 * 0.82

    @property
    def grabado_centro_x(self) -> float:
        """Centro del ala elegida, medido desde el borde de la pieza."""
        return self.ancho * (0.75 if self.nombre_lado == "der" else 0.25)

    @property
    def plancha(self) -> tuple[float, float]:
        """Rectángulo que ocupan las dos piezas juntas, con márgenes."""
        ancho = 2 * self.margen + max(self.ancho, self.fondo)
        alto = 2 * self.margen + self.altura + self.separacion + self.altura_fondo
        return ancho, alto

    # ------------------------------------------------------------ chequeos

    def problemas(self) -> list[str]:
        """Errores que impiden generar la pieza."""
        malas: list[str] = []
        if self.espesor <= self.kerf:
            malas.append(
                f"el kerf ({self.kerf:g}) se come el espesor ({self.espesor:g}): "
                f"no queda ranura que cortar"
            )
        if self.altura_frente < 12:
            malas.append(
                f"con {self.angulo:g}° y {self.fondo:g} mm de fondo el frente de la L "
                f"queda en {self.altura_frente:.1f} mm y apoya sobre un filo. "
                f"Bajá el ángulo, acortá el fondo o subí la altura."
            )
        if self.profundidad_muesca < 12:
            malas.append(
                f"la muesca queda de {self.profundidad_muesca:.1f} mm y la unión no "
                f"agarra. La altura al cruce no puede bajar de 24 mm."
            )
        if self.nombre_lado not in ("izq", "der"):
            malas.append(f"nombre_lado tiene que ser 'izq' o 'der', no {self.nombre_lado!r}")
        if self.alivio <= self.espesor:
            malas.append(
                f"el alivio ({self.alivio:g}) tiene que ser mayor que el espesor "
                f"({self.espesor:g}) o no asoma de la ranura"
            )
        for texto, donde in ((self.nombre, "nombre"), (self.marca, "marca")):
            faltantes = unsupported(texto) if texto else []
            if faltantes:
                malas.append(
                    f"la fuente no tiene {', '.join(repr(c) for c in faltantes)} "
                    f"para el {donde} {texto!r}"
                )
        return malas

    def advertencias(self) -> list[str]:
        """Cosas que se pueden cortar igual pero conviene saber."""
        avisos: list[str] = []
        if self.pasa_cables:
            ancho_ojal, alto_ojal = self.pasa_cables_mm
            centro_x = self.fondo - ancho_ojal / 2 - 32.5
            borde_muesca = self.fondo / 2 + self.alivio / 2
            if centro_x - ancho_ojal / 2 < borde_muesca + 6:
                avisos.append(
                    "el pasa-cables queda pegado a la muesca de la L; "
                    "achicalo o alargá el fondo"
                )
            alto_local = self.altura_frente + centro_x * math.tan(math.radians(self.angulo))
            if centro_x + ancho_ojal / 2 > self.fondo - 8 or \
                    alto_ojal / 2 + 8 > alto_local:
                avisos.append("el pasa-cables no entra holgado en el brazo trasero")
        if self.nombre:
            alto = _alto_que_entra(
                self.nombre, self.grabado_ancho, self.grabado_alto_max, self.grabado_alto_min
            )
            if alto <= self.grabado_alto_min + 1e-9 and \
                    text_width(self.nombre, alto) > self.grabado_ancho:
                avisos.append(
                    f"{self.nombre!r} no entra en la T ni al mínimo de "
                    f"{self.grabado_alto_min:g} mm: va a salir cortado"
                )
        return avisos


# ------------------------------------------------------------------ helpers


def _alto_que_entra(texto: str, ancho_max: float, alto_max: float, alto_min: float) -> float:
    """Baja la altura de la tipografía hasta que el texto entre en el ancho.

    Un "MARÍA" sale grande y un "GUADALUPE" un poco más chico, pero los dos
    salen centrados y completos, que es lo que le importa a quien lo recibe.
    """
    if not texto:
        return 0.0
    ancho = text_width(texto, alto_max)
    if ancho <= ancho_max or ancho <= 0:
        return alto_max
    return max(alto_min, alto_max * ancho_max / ancho)


def _obround(cx: float, cy: float, ancho: float, alto: float) -> list[Point]:
    """Óvalo alargado (rectángulo con las puntas redondeadas)."""
    radio = alto / 2.0
    recta = ancho - alto
    if recta <= 0:
        raise ValueError("el pasa-cables tiene que ser más largo que alto")
    izq, der = cx - recta / 2, cx + recta / 2
    return (
        [(izq, cy - radio)]
        + arc_points(der, cy, radio, -math.pi / 2, math.pi / 2, 0.0)
        + arc_points(izq, cy, radio, math.pi / 2, -math.pi / 2, math.pi)[:-1]
    )


# ------------------------------------------------------------------ piezas


def perfil_transversal(spec: SoporteSpec, x0: float, y0: float) -> list[Point]:
    """Contorno de la T, en medidas finales y sentido antihorario."""
    muesca = notch(
        x0 + spec.ancho / 2,
        y0 + spec.altura,
        y0 + spec.altura - spec.profundidad_muesca,
        spec.espesor,
        relief_diameter=spec.alivio,
    )
    return (
        [(x0, y0), (x0 + spec.ancho, y0), (x0 + spec.ancho, y0 + spec.altura)]
        + list(reversed(muesca))          # recorriendo el canto de derecha a izquierda
        + [(x0, y0 + spec.altura)]
    )


def perfil_longitudinal(spec: SoporteSpec, x0: float, y0: float) -> list[Point]:
    """Contorno de la L. La muesca sube desde la base, al revés que la T."""
    muesca = notch(
        x0 + spec.fondo / 2,
        y0,
        y0 + spec.profundidad_muesca,
        spec.espesor,
        relief_diameter=spec.alivio,
    )
    return (
        [(x0, y0)]
        + muesca
        + [
            (x0 + spec.fondo, y0),
            (x0 + spec.fondo, y0 + spec.altura_fondo),
            (x0, y0 + spec.altura_frente),
        ]
    )


@dataclass
class Medidas:
    """Lo que hace falta saber antes de apretar run."""

    ancho_frente: float
    altura_frente: float
    altura_fondo: float
    ranura: float
    plancha: tuple[float, float]
    corte_mm: float
    pasadas: int
    minutos: float
    grabado_alto: float
    avisos: list[str] = field(default_factory=list)


def _largo(points: list[Point], cerrado: bool = True) -> float:
    total = 0.0
    for index in range(1, len(points)):
        total += math.dist(points[index - 1], points[index])
    if cerrado and len(points) > 2:
        total += math.dist(points[-1], points[0])
    return total


def medidas(spec: SoporteSpec, options: CutOptions) -> Medidas:
    """Calcula las medidas y el tiempo sin generar el G-code."""
    contornos = _contornos(spec)
    corte = sum(_largo(c.points, c.closed) for c in contornos)
    return Medidas(
        ancho_frente=spec.ancho,
        altura_frente=spec.altura_frente,
        altura_fondo=spec.altura_fondo,
        ranura=spec.ranura_dibujada,
        plancha=spec.plancha,
        corte_mm=corte,
        pasadas=options.passes,
        minutos=corte * options.passes / max(1, options.speed),
        grabado_alto=_alto_que_entra(
            spec.nombre, spec.grabado_ancho, spec.grabado_alto_max, spec.grabado_alto_min
        ),
        avisos=spec.advertencias(),
    )


def _contornos(spec: SoporteSpec) -> list[Contour]:
    """Los contornos de corte, ya compensados, en coordenadas de plancha."""
    t_x, t_y = spec.margen, spec.margen
    l_x, l_y = spec.margen, spec.margen + spec.altura + spec.separacion

    contornos = [
        Contour(compensate(perfil_transversal(spec, t_x, t_y), kerf=spec.kerf, role=PART),
                role=PART),
        Contour(compensate(perfil_longitudinal(spec, l_x, l_y), kerf=spec.kerf, role=PART),
                role=PART),
    ]

    if spec.pasa_cables:
        ancho_ojal, alto_ojal = spec.pasa_cables_mm
        cx = l_x + spec.fondo - ancho_ojal / 2 - 32.5
        cy = l_y + spec.altura * 0.55
        contornos.insert(
            0,
            Contour(
                compensate(_obround(cx, cy, ancho_ojal, alto_ojal),
                           kerf=spec.kerf, role=HOLE),
                role=HOLE,
            ),
        )
    return contornos


def build_soporte(
    spec: SoporteSpec,
    options: CutOptions,
    *,
    grabado_feed: int = GRABADO_FEED,
    grabado_power: int = GRABADO_POWER,
) -> GcodeProgram:
    """Genera el programa completo: primero graba, después corta.

    El orden no es un detalle de estilo. Una pieza recién cortada está suelta
    sobre el panal, y grabar después implica pasar el cabezal por encima de
    algo que ya se puede mover. Se graba todo, se corta todo.
    """
    problemas = spec.problemas()
    if problemas:
        raise ValueError("no se puede generar el soporte:\n  - " + "\n  - ".join(problemas))

    program = GcodeProgram(GcodeOptions(dynamic_power=True, air_assist=True))
    program.preamble(f"soporte notebook {spec.ancho:g}x{spec.fondo:g}")
    program.comment(f"espesor {spec.espesor:g} kerf {spec.kerf:g} "
                    f"-> ranura dibujada {spec.ranura_dibujada:g}")
    program.comment(f"altura al cruce {spec.altura:g}, frente {spec.altura_frente:.1f}, "
                    f"fondo {spec.altura_fondo:.1f}, angulo {spec.angulo:g} grados")
    program.comment(f"muesca {spec.profundidad_muesca:g} de profundidad, "
                    f"alivio {spec.alivio:g}")
    if spec.nombre:
        program.comment(f"grabado: {spec.nombre}")
    program.comment("ATENCION: primero graba y despues corta. No reordenar.")

    t_x, t_y = spec.margen, spec.margen
    l_x, l_y = spec.margen, spec.margen + spec.altura + spec.separacion

    # --- grabado, antes de que nada quede suelto
    if spec.nombre:
        alto = _alto_que_entra(
            spec.nombre, spec.grabado_ancho, spec.grabado_alto_max, spec.grabado_alto_min
        )
        # Centrado en el ala y a media altura de la pieza: en el ala no hay
        # muesca, así que se puede usar todo el alto.
        trazos = text_polylines(
            spec.nombre,
            t_x + spec.grabado_centro_x,
            t_y + (spec.altura - alto) / 2,
            alto,
            center=True,
        )
        for trazo in thicken(trazos, spec.grosor):
            program.polyline(trazo, feed=grabado_feed, power=grabado_power)

    if spec.marca:
        ancho_marca = text_width(spec.marca, spec.marca_alto)
        trazos = text_polylines(
            spec.marca, l_x + spec.fondo - 8 - ancho_marca, l_y + 8, spec.marca_alto
        )
        for trazo in thicken(trazos, spec.grosor):
            program.polyline(trazo, feed=grabado_feed, power=grabado_power)

    # --- corte: interiores primero, perímetros al final
    cut_contours(program, _contornos(spec), options)

    program.postamble()
    return program
