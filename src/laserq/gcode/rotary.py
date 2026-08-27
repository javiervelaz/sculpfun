"""Grabado rotativo: cilindros y, sobre todo, cónicos.

Cómo ve GRBL al rotativo
------------------------
GRBL no sabe que hay algo girando. El rotativo reemplaza al eje Y y el
firmware sigue pensando en milímetros. Toda la traducción vive en `$101`
(pasos/mm de Y).

Con un rotativo **de rodillos** (el de la S30) el objeto gira por fricción,
así que la superficie del objeto recorre la misma distancia lineal que la
superficie del rodillo motriz. De ahí sale la relación fundamental:

    Y_máquina (mm) = θ (rad) × R_contacto (mm)

Y la consecuencia práctica: **`$101` se calibra una sola vez**, contra el
rodillo, y no depende del diámetro del objeto. Lo que sí cambia por objeto
es cuánto Y hace falta para una vuelta completa: π × D.

(Con un rotativo de mandril sería al revés: el objeto gira solidario al
plato, el ángulo es lo que se controla, y habría que recalcular pasos/mm
para cada diámetro. Por eso el de rodillos es más cómodo para producción.)

El problema del cónico
----------------------
Un mate, un vaso o un porrón casi nunca son cilindros: son troncos de cono.
Y la superficie lateral de un cono **no se puede desplegar en un
rectángulo**: se despliega en un sector de corona circular.

Si envolvés un diseño rectangular sobre un cónico, a la misma cantidad de
grados le corresponde más arco abajo (donde el radio es mayor) que arriba.
El resultado: el texto sale con las letras de distinto ancho según la
altura, y una línea de base recta se ve curvada sobre la pieza. Es el
defecto que casi todo el mundo acepta como "así salen los mates" y que se
arregla con veinte líneas de trigonometría.

La corrección: en vez de mapear el diseño con un ángulo constante, se pide
que cada punto conserve su **longitud de arco física**. A la posición axial
x le corresponde un radio local r(x), y entonces:

    θ = u / r(x)        →        Y = u × R_contacto / r(x)

donde u es la distancia horizontal deseada sobre la superficie, en mm.
Para un cilindro r(x) es constante y todo se reduce a la identidad.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RotaryConfig:
    """Configuración del rotativo de rodillos."""

    roller_diameter_mm: float = 15.0
    #: `$101` calibrado para que 1 mm de Y = 1 mm de superficie del rodillo.
    steps_per_mm: float | None = None
    #: `$121`. La aceleración de Y hay que bajarla bastante respecto del
    #: valor de la mesa plana: un termo lleno tiene inercia y patina sobre
    #: los rodillos, y un patinazo a mitad de pasada arruina la pieza sin
    #: que la máquina se entere.
    acceleration: float = 200.0
    max_feed: float = 3000.0


def steps_per_mm_for_roller(motor_steps_per_rev: int, microsteps: int,
                            roller_diameter_mm: float) -> float:
    """Valor teórico de `$101` para un rotativo de rodillos.

    Es un punto de partida, no el valor final: el diámetro real del rodillo
    nunca es exactamente el nominal. Usalo para arrancar y después ajustá
    con `calibrate_from_wrap`.
    """
    steps_per_rev = motor_steps_per_rev * microsteps
    roller_circumference = math.pi * roller_diameter_mm
    return steps_per_rev / roller_circumference


def calibrate_from_wrap(current_steps_per_mm: float, object_diameter_mm: float,
                        error_mm: float) -> float:
    """Corrige `$101` a partir de una vuelta completa medida.

    Procedimiento: grabás una línea longitudinal, girás exactamente lo que
    el software cree que es una vuelta (π × D), grabás otra línea. Medís la
    separación entre las dos.

    `error_mm` es positivo si la segunda línea quedó **pasada** (giró de
    más) y negativo si quedó **corta**.
    """
    nominal = math.pi * object_diameter_mm
    actual = nominal + error_mm
    if actual <= 0:
        raise ValueError("el error medido no puede anular la vuelta completa")
    return current_steps_per_mm * actual / nominal


def full_turn_mm(diameter_mm: float) -> float:
    """Milímetros de Y necesarios para una vuelta completa del objeto."""
    return math.pi * diameter_mm


def focus_band_width(diameter_mm: float, focus_tolerance_mm: float = 0.5) -> float:
    """Ancho máximo de grabado, en mm de arco, que queda dentro del foco.

    Sobre una superficie curva solo una franja angosta está a la distancia
    focal correcta. Alejándote del punto más alto, la superficie se hunde
    R(1-cos θ) y el punto del láser se agranda y pierde densidad de
    potencia: el grabado sale lavado hacia los costados.

    Con la lente de la S30 y trabajo fino, una tolerancia de 0.3-0.5 mm es
    razonable. Si el diseño es más ancho que lo que devuelve esta función,
    hay que partirlo en franjas y rotar entre una y otra.

    >>> round(focus_band_width(80, 0.5), 1)   # un termo típico
    12.6
    """
    radius = diameter_mm / 2.0
    if focus_tolerance_mm >= radius:
        return math.pi * diameter_mm
    theta = math.acos(1.0 - focus_tolerance_mm / radius)
    return 2.0 * radius * theta


@dataclass
class ConeMapping:
    """Mapeo de coordenadas de superficie a coordenadas de máquina.

    Sistema de coordenadas del diseño:
      * ``v``: posición a lo largo del eje del objeto, en mm. Coincide con X.
      * ``u``: distancia horizontal sobre la superficie, en mm de arco real,
        medida desde el centro del diseño.

    Un cilindro es el caso particular ``diameter_start == diameter_end``.
    """

    diameter_start: float  # diámetro en v = 0
    diameter_end: float  # diámetro en v = length
    length: float  # largo axial del tramo, en mm
    #: Diámetro con el que el objeto apoya sobre los rodillos. En un cónico
    #: apoyado sin calzar, tomá el diámetro de la zona que efectivamente
    #: toca los rodillos; si dudás, empezá por el promedio y ajustá con una
    #: pieza de prueba.
    contact_diameter: float | None = None
    origin_x: float = 0.0
    origin_y: float = 0.0

    def __post_init__(self) -> None:
        if self.length <= 0:
            raise ValueError("length debe ser positivo")
        if min(self.diameter_start, self.diameter_end) <= 0:
            raise ValueError("los diámetros deben ser positivos")
        if self.contact_diameter is None:
            self.contact_diameter = (self.diameter_start + self.diameter_end) / 2.0

    @property
    def is_conical(self) -> bool:
        return abs(self.diameter_start - self.diameter_end) > 1e-6

    @property
    def taper_angle_deg(self) -> float:
        """Semiángulo del cono, en grados. Útil para saber cuánto hay que calzar."""
        delta_r = (self.diameter_end - self.diameter_start) / 2.0
        return math.degrees(math.atan2(delta_r, self.length))

    def radius_at(self, v: float) -> float:
        """Radio local del objeto en la posición axial v."""
        fraction = v / self.length
        r0 = self.diameter_start / 2.0
        r1 = self.diameter_end / 2.0
        return r0 + (r1 - r0) * fraction

    def to_machine(self, u: float, v: float) -> tuple[float, float]:
        """Convierte un punto del diseño (u, v) a coordenadas de máquina (X, Y)."""
        radius = self.radius_at(v)
        contact_radius = self.contact_diameter / 2.0  # type: ignore[operator]
        y = self.origin_y + u * contact_radius / radius
        return self.origin_x + v, y

    def design_u(self, y_machine: float, v: float) -> float:
        """Mapeo inverso: qué u del diseño cae en esta posición de máquina.

        Es lo que hace falta para el raster: el barrido va a lo largo del
        eje (X) con la rotación fija, así que cada línea de máquina cruza
        el diseño en un arco distinto según el radio local.
        """
        radius = self.radius_at(v)
        contact_radius = self.contact_diameter / 2.0  # type: ignore[operator]
        return (y_machine - self.origin_y) * radius / contact_radius

    def warp_polyline(
        self, points: list[tuple[float, float]], *, max_segment_mm: float = 1.0
    ) -> list[tuple[float, float]]:
        """Convierte una polilínea del diseño a máquina, subdividiendo.

        La subdivisión es obligatoria en cónicos: la relación entre X e Y no
        es lineal (Y depende de 1/r(x), y r es lineal en x), así que un
        segmento recto del diseño es una curva en el espacio de la máquina.
        Sin subdividir, un rectángulo del diseño sale con los lados rectos y
        el error se ve a simple vista en la pieza.
        """
        if not self.is_conical:
            return [self.to_machine(u, v) for u, v in points]

        out: list[tuple[float, float]] = []
        for index, (u, v) in enumerate(points):
            if index == 0:
                out.append(self.to_machine(u, v))
                continue
            prev_u, prev_v = points[index - 1]
            distance = math.hypot(u - prev_u, v - prev_v)
            steps = max(1, math.ceil(distance / max_segment_mm))
            for step in range(1, steps + 1):
                t = step / steps
                out.append(
                    self.to_machine(
                        prev_u + (u - prev_u) * t,
                        prev_v + (v - prev_v) * t,
                    )
                )
        return out


def cylinder(diameter_mm: float, length_mm: float, **kwargs) -> ConeMapping:
    """Atajo para el caso cilíndrico."""
    return ConeMapping(
        diameter_start=diameter_mm,
        diameter_end=diameter_mm,
        length=length_mm,
        contact_diameter=diameter_mm,
        **kwargs,
    )


def rotary_preamble_notes(config: RotaryConfig, mapping: ConeMapping) -> list[str]:
    """Checklist que se escribe como comentario arriba del job.

    Que quede en el archivo tiene una razón práctica: dentro de un mes vas
    a abrir un G-code viejo sin acordarte con qué objeto lo hiciste.
    """
    notes = [
        f"rotativo: rodillo {config.roller_diameter_mm:g}mm, $101={config.steps_per_mm or '?'}",
        f"objeto: {mapping.diameter_start:g} -> {mapping.diameter_end:g} mm "
        f"en {mapping.length:g} mm de largo",
        f"vuelta completa (contacto) = {full_turn_mm(mapping.contact_diameter):.2f} mm de Y",
    ]
    if mapping.is_conical:
        notes.append(
            f"CONICO: semiangulo {mapping.taper_angle_deg:.2f} grados, "
            f"correccion de arco aplicada"
        )
    band = focus_band_width(max(mapping.diameter_start, mapping.diameter_end))
    notes.append(f"franja util de foco ~{band:.1f} mm de arco (tolerancia 0.5mm)")
    return notes
