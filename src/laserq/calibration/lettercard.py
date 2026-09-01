"""Placa de letras: calibrar el grabado de texto, que no es el de relleno.

La placa de relleno (`testcard.py`) mide otra cosa. Ahí cada celda es un
barrido con las líneas a 0.1 mm, y el calor de una línea oscurece a la de al
lado. Un trazo suelto no tiene vecinos que lo ayuden, así que con los mismos
F y S sale bastante más claro. Por eso las letras necesitan su propia placa y
no se pueden deducir de la otra — que es exactamente el error que hace que un
nombre grabado quede casi invisible sobre una pieza que corta perfecto.

Los dos ejes son los que deciden si un nombre se lee:

* **velocidad**, que gobierna cuánto se quema el trazo;
* **grosor**, que es cuánto se repite el recorrido en cruz para que la letra
  tenga cuerpo. Una tipografía de trazo único deja un pelo del ancho del kerf.

El alto de la letra no cambia qué tan oscuro sale el trazo, así que medir a
8 mm vale para grabar a 20.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..gcode.builder import GcodeOptions, GcodeProgram
from ..gcode.font import text_polylines, text_width, thicken
from .labels import DEFAULT_LABEL_HEIGHT, engrave_label


@dataclass
class LetterTestSpec:
    """Grilla grosor x velocidad, a potencia fija."""

    texto: str = "ABZ 28"
    alto_letra: float = 8.0
    #: Ancho agregado al trazo, en mm. 0 es el trazo pelado de la fuente.
    grosores: list[float] = field(default_factory=lambda: [0.0, 0.2, 0.4, 0.6])
    speeds: list[int] = field(default_factory=lambda: [600, 1000, 1500, 2500])
    power: int = 500
    gap_x: float = 10.0
    gap_y: float = 9.0
    origin: tuple[float, float] = (22.0, 14.0)
    label_height_mm: float = DEFAULT_LABEL_HEIGHT

    @property
    def paso_x(self) -> float:
        return text_width(self.texto, self.alto_letra) + self.gap_x

    @property
    def paso_y(self) -> float:
        return self.alto_letra + self.gap_y

    @property
    def total_size(self) -> tuple[float, float]:
        return (len(self.speeds) * self.paso_x - self.gap_x,
                len(self.grosores) * self.paso_y - self.gap_y)


def build_letter_test(spec: LetterTestSpec, *, material: str = "") -> GcodeProgram:
    """La misma palabra en cada combinación de grosor y velocidad."""
    program = GcodeProgram(GcodeOptions(dynamic_power=True, air_assist=True))
    width, height = spec.total_size
    origin_x, origin_y = spec.origin

    program.preamble(f"placa de letras {material}".strip())
    program.comment(f"filas = grosor agregado mm: {spec.grosores}")
    program.comment(f"columnas = velocidad mm/min: {spec.speeds}")
    program.comment(f"potencia fija S{spec.power}, letra de {spec.alto_letra:g} mm")
    program.comment("como se lee: la celda que se lee de un metro, con el trazo mas")
    program.comment("fino que todavia se lee. La velocidad va al perfil de grabado")
    program.comment("y el grosor al parametro --grosor del soporte.")
    program.comment(f"tamano total con etiquetas: ~{width + 30:.0f} x {height + 22:.0f} mm")

    for fila, grosor in enumerate(spec.grosores):
        for columna, speed in enumerate(spec.speeds):
            x = origin_x + columna * spec.paso_x
            y = origin_y + fila * spec.paso_y
            program.comment(f"celda grosor {grosor:g} F{speed}")
            for polyline in thicken(text_polylines(spec.texto, x, y, spec.alto_letra),
                                    grosor):
                program.polyline(polyline, feed=speed, power=spec.power)

    for fila, grosor in enumerate(spec.grosores):
        etiqueta = f"{grosor:.1f}"
        y = origin_y + fila * spec.paso_y + (spec.alto_letra - spec.label_height_mm) / 2
        x = origin_x - text_width(etiqueta, spec.label_height_mm) - 5.0
        engrave_label(program, etiqueta, x, y, spec.label_height_mm)

    for columna, speed in enumerate(spec.speeds):
        engrave_label(program, str(speed), origin_x + columna * spec.paso_x,
                      origin_y - spec.label_height_mm - 5.0, spec.label_height_mm)

    engrave_label(program, "GROSOR", origin_x - 20.0, origin_y + height + 6.0,
                  spec.label_height_mm)
    engrave_label(program, f"S{spec.power}", origin_x + width - 12.0,
                  origin_y + height + 6.0, spec.label_height_mm)

    program.postamble()
    return program
