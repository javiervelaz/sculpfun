"""Calibración de corte: la placa de pasadas y el peine de kerf.

Son las dos pruebas que hay que quemar antes de cortar la primera pieza
vendible. Ninguna de las dos se puede reemplazar por un número de un foro:
dependen de tu lente, tu foco, tu extracción y la plancha que compraste.

1. `build_cut_test` — ¿con qué velocidad y cuántas pasadas atraviesa?
   Una grilla de líneas cortas: cada fila una cantidad de pasadas, cada
   columna una velocidad, la potencia fija en el máximo. Se corta, se da
   vuelta la plancha y se mira de atrás: las líneas que se ven atravesaron.
   Elegís la celda más rápida que atraviesa limpio y esos valores van al
   perfil del material.

2. `build_kerf_comb` — ¿cuánto se come el láser?
   Una fila de ranuras de ancho creciente en pasos de 0.05 mm, más una
   lengüeta cortada de la misma plancha. Probás la lengüeta en cada ranura;
   la que entra justa —con presión de mano, sin juego— te da el número:

       kerf = espesor medido con calibre - ancho nominal de esa ranura

   Ese valor va a `kerf_mm` en el perfil, y a partir de ahí el generador
   compensa solo.

**El peine se corta sin compensar.** Es la única pieza del sistema donde eso
es correcto: si compensáramos con un kerf que todavía no conocemos, la
medición mediría nuestra suposición.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..gcode.builder import GcodeOptions, GcodeProgram
from ..gcode.cut import Contour, CutOptions, cut_contours, outline, slot
from ..gcode.font import text_width
from .labels import DEFAULT_LABEL_HEIGHT, engrave_label

# ------------------------------------------------------- placa de pasadas


@dataclass
class CutTestSpec:
    """Grilla pasadas x velocidad, a potencia fija.

    La potencia no es un eje: cortando se usa el máximo casi siempre, y lo
    que realmente decide es cuánta energía por milímetro entregás, que se
    gobierna con la velocidad y con la cantidad de pasadas.
    """

    #: Rango pensado para material fino (MDF de 3 mm y similares), donde una
    #: sola pasada ya puede atravesar. Para 6 mm o más, correr con
    #: `--passes 3,4,5,6 --speeds 100,150,250,400`.
    passes: list[int] = field(default_factory=lambda: [1, 2, 3, 4])
    speeds: list[int] = field(default_factory=lambda: [200, 300, 450, 600, 800])
    power: int = 1000
    line_mm: float = 12.0
    pitch_x: float = 14.0
    pitch_y: float = 16.0
    origin: tuple[float, float] = (18.0, 16.0)
    label_height_mm: float = DEFAULT_LABEL_HEIGHT

    @property
    def total_size(self) -> tuple[float, float]:
        width = (len(self.speeds) - 1) * self.pitch_x
        height = (len(self.passes) - 1) * self.pitch_y + self.line_mm
        return width, height


def build_cut_test(spec: CutTestSpec, *, material: str = "") -> GcodeProgram:
    """Genera la placa de corte. Cada celda es una línea cortada N veces."""
    program = GcodeProgram(GcodeOptions(dynamic_power=True, air_assist=True))
    width, height = spec.total_size
    origin_x, origin_y = spec.origin

    program.preamble(f"placa de corte {material}".strip())
    program.comment(f"filas = pasadas: {spec.passes}")
    program.comment(f"columnas = velocidad mm/min: {spec.speeds}")
    program.comment(f"potencia fija S{spec.power}")
    program.comment("como se lee: cortar, dar vuelta la plancha y mirar de atras.")
    program.comment("las lineas que se ven atravesaron. elegi la celda mas rapida")
    program.comment("que atraviesa limpio y cargala en el perfil del material.")
    program.comment(f"tamano total con etiquetas: ~{width + 30:.0f} x {height + 20:.0f} mm")

    contours: list[Contour] = []
    for row, passes in enumerate(spec.passes):
        for col, _speed in enumerate(spec.speeds):
            x = origin_x + col * spec.pitch_x
            y = origin_y + row * spec.pitch_y
            contours.append(
                Contour(
                    [(x, y), (x, y + spec.line_mm)],
                    role="part",
                    closed=False,
                    passes=passes,
                )
            )

    # Una celda por velocidad: cada columna se corta con su propio F.
    for col, speed in enumerate(spec.speeds):
        columna = [c for i, c in enumerate(contours) if i % len(spec.speeds) == col]
        cut_contours(
            program,
            columna,
            CutOptions(speed=speed, power=spec.power, passes=1),
        )

    # Etiquetas: pasadas a la izquierda de cada fila, velocidad abajo.
    for row, passes in enumerate(spec.passes):
        label = str(passes)
        y = origin_y + row * spec.pitch_y + (spec.line_mm - spec.label_height_mm) / 2
        x = origin_x - text_width(label, spec.label_height_mm) - 6.0
        engrave_label(program, label, x, y, spec.label_height_mm)

    for col, speed in enumerate(spec.speeds):
        label = str(speed)
        x = origin_x + col * spec.pitch_x
        y = origin_y - spec.label_height_mm - 4.0
        engrave_label(program, label, x, y, spec.label_height_mm, center=True)

    engrave_label(program, "PASADAS", origin_x - 16.0, origin_y + height + 5.0,
                  spec.label_height_mm)
    engrave_label(program, f"S{spec.power}", origin_x + width - 8.0,
                  origin_y + height + 5.0, spec.label_height_mm)
    engrave_label(program, "F MM/MIN", origin_x + width - 10.0,
                  origin_y - spec.label_height_mm - 11.0, spec.label_height_mm)

    program.postamble()
    return program


# ---------------------------------------------------------- peine de kerf


@dataclass
class KerfCombSpec:
    """Fila de ranuras de ancho creciente alrededor del espesor real.

    `thickness_mm` es el espesor **medido con calibre**, no el nominal. Un
    multilaminado de "6 mm" mide casi siempre entre 5.5 y 5.9, y si centrás
    el barrido en 6.00 se te va todo el peine para un lado.
    """

    thickness_mm: float = 6.0
    #: Cuánto barre a cada lado del espesor medido.
    span_mm: float = 0.30
    step_mm: float = 0.05
    slot_length_mm: float = 35.0
    pitch_mm: float = 16.0
    origin: tuple[float, float] = (12.0, 16.0)
    label_height_mm: float = DEFAULT_LABEL_HEIGHT
    #: Corta una lengüeta de la misma plancha para usar de galga. Sin esto
    #: hay que buscar un recorte, y el recorte nunca es de la misma plancha.
    gauge: bool = True
    gauge_size_mm: tuple[float, float] = (30.0, 18.0)

    @property
    def widths(self) -> list[float]:
        count = int(round(2 * self.span_mm / self.step_mm)) + 1
        start = self.thickness_mm - self.span_mm
        return [round(start + i * self.step_mm, 3) for i in range(count)]

    @property
    def total_size(self) -> tuple[float, float]:
        width = len(self.widths) * self.pitch_mm
        if self.gauge:
            width += self.gauge_size_mm[0] + self.pitch_mm
        return width, self.slot_length_mm


def build_kerf_comb(spec: KerfCombSpec, options: CutOptions) -> GcodeProgram:
    """Genera el peine. Se corta SIN compensar: es lo que se está midiendo."""
    program = GcodeProgram(GcodeOptions(dynamic_power=True, air_assist=True))
    origin_x, origin_y = spec.origin
    widths = spec.widths

    program.preamble(f"peine de kerf para {spec.thickness_mm:g} mm")
    program.comment(f"ranuras: {widths[0]:g} a {widths[-1]:g} mm, paso {spec.step_mm:g}")
    program.comment(f"corte F{options.speed} S{options.power} x{options.passes} pasadas")
    program.comment("SIN compensacion de kerf: es exactamente lo que se esta midiendo")
    program.comment("como se lee: probar la lengueta en cada ranura. la que entra")
    program.comment("con presion de mano y sin juego es la buena. entonces:")
    program.comment(f"  kerf = {spec.thickness_mm:g} (espesor con calibre) - ancho de esa ranura")
    program.comment("ese numero va a kerf_mm en el perfil del material")

    # Las ranuras se cortan sin compensar, y por eso kerf=0 acá es correcto.
    contours: list[Contour] = [
        slot(
            origin_x + index * spec.pitch_mm,
            origin_y,
            width,
            spec.slot_length_mm,
            kerf=0.0,
        )
        for index, width in enumerate(widths)
    ]

    if spec.gauge:
        gauge_x = origin_x + len(widths) * spec.pitch_mm + spec.pitch_mm
        gauge_w, gauge_h = spec.gauge_size_mm
        if gauge_w > spec.slot_length_mm:
            program.comment(
                f"OJO: la lengueta ({gauge_w:g} mm) es mas larga que la ranura "
                f"({spec.slot_length_mm:g} mm) y no va a entrar de plano"
            )
        contours.append(outline(gauge_x, origin_y, gauge_w, gauge_h, kerf=0.0))
        engrave_label(program, "GALGA", gauge_x, origin_y + gauge_h + 4.0,
                      spec.label_height_mm)

    cut_contours(program, contours, options)

    # Etiquetas debajo de cada ranura. El "6" o el "5" de adelante importa:
    # dentro de un mes no vas a acordarte de cuál era el espesor.
    for index, width in enumerate(widths):
        label = f"{width:.2f}"
        x = origin_x + index * spec.pitch_mm + width / 2
        y = origin_y - spec.label_height_mm - 4.0
        engrave_label(program, label, x, y, spec.label_height_mm, center=True)

    program.postamble()
    return program
