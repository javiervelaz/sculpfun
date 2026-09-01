"""Generador de placas de test: matriz de potencia contra velocidad.

Esta es la primera herramienta que conviene tener funcionando, antes que
cualquier idea de producto. Los parámetros que andan bien para tu máquina,
con tu lente, tu foco, tu ventilación y tu proveedor de MDF no están en
ningún foro: los tenés que medir. Y una vez medidos, esa tabla vale más que
el código, porque es lo único que no se puede googlear ni copiar.

La placa graba una grilla de celdas. Cada fila usa una potencia y cada
columna una velocidad, con las etiquetas grabadas al lado. Cortás una,
mirás a contraluz, elegís la celda que te gusta y guardás ese perfil.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..gcode.builder import GcodeOptions, GcodeProgram
from ..gcode.font import text_polylines, text_width


@dataclass
class TestCardSpec:
    """Parámetros de la placa."""

    powers: list[int] = field(default_factory=lambda: [200, 400, 600, 800, 1000])
    speeds: list[int] = field(default_factory=lambda: [1000, 2000, 3000, 5000, 8000])
    cell_mm: float = 12.0
    gap_mm: float = 4.0
    #: Separación entre pasadas del relleno. Que sea igual o menor al
    #: diámetro del punto para que la celda quede pareja.
    line_interval_mm: float = 0.1
    label_height_mm: float = 3.5
    #: Potencia y velocidad de las etiquetas. Deben ser conservadoras: si
    #: quemás las etiquetas no podés leer la placa.
    label_power: int = 350
    label_speed: int = 2000
    #: Deja lugar a la izquierda y abajo para las etiquetas y el marco,
    #: que se dibujan en coordenadas menores al origen de la grilla.
    origin: tuple[float, float] = (16.0, 12.0)
    draw_border: bool = True
    air_assist: bool = True

    @property
    def pitch(self) -> float:
        return self.cell_mm + self.gap_mm

    @property
    def total_size(self) -> tuple[float, float]:
        width = len(self.speeds) * self.pitch - self.gap_mm
        height = len(self.powers) * self.pitch - self.gap_mm
        return width, height


def _fill_cell(
    program: GcodeProgram,
    x: float,
    y: float,
    size: float,
    *,
    power: int,
    speed: int,
    interval: float,
) -> None:
    """Rellena una celda con barrido bidireccional."""
    lines = max(1, int(round(size / interval)))
    left_to_right = True
    for index in range(lines + 1):
        line_y = y + index * interval
        if line_y > y + size:
            break
        if left_to_right:
            program.rapid(x, line_y)
            program.cut(x + size, feed=speed, power=power)
        else:
            program.rapid(x + size, line_y)
            program.cut(x, feed=speed, power=power)
        left_to_right = not left_to_right
    program.set_power(0)


def _engrave_text(
    program: GcodeProgram, text: str, x: float, y: float, spec: TestCardSpec
) -> None:
    for polyline in text_polylines(text, x, y, spec.label_height_mm):
        program.polyline(polyline, feed=spec.label_speed, power=spec.label_power)


def build_test_card(spec: TestCardSpec, *, material: str = "") -> GcodeProgram:
    """Genera el programa completo de la placa de test."""
    program = GcodeProgram(
        GcodeOptions(dynamic_power=True, air_assist=spec.air_assist)
    )
    width, height = spec.total_size
    program.preamble(f"placa de test {material}".strip())
    program.comment(f"filas = potencia: {spec.powers}")
    program.comment(f"columnas = velocidad mm/min: {spec.speeds}")
    program.comment(f"celda {spec.cell_mm}mm, interval {spec.line_interval_mm}mm")
    program.comment(f"tamano total con etiquetas: ~{width + 20:.0f} x {height + 15:.0f} mm")

    origin_x, origin_y = spec.origin

    # Celdas
    for row, power in enumerate(spec.powers):
        for col, speed in enumerate(spec.speeds):
            x = origin_x + col * spec.pitch
            y = origin_y + row * spec.pitch
            program.comment(f"celda S{power} F{speed}")
            _fill_cell(
                program,
                x,
                y,
                spec.cell_mm,
                power=power,
                speed=speed,
                interval=spec.line_interval_mm,
            )

    # Etiquetas de potencia, a la izquierda de cada fila
    for row, power in enumerate(spec.powers):
        label = str(power)
        y = origin_y + row * spec.pitch + (spec.cell_mm - spec.label_height_mm) / 2
        x = origin_x - text_width(label, spec.label_height_mm) - 3.0
        _engrave_text(program, label, x, y, spec)

    # Etiquetas de velocidad, abajo de cada columna
    for col, speed in enumerate(spec.speeds):
        label = str(speed)
        x = origin_x + col * spec.pitch + (spec.cell_mm - text_width(label, spec.label_height_mm)) / 2
        y = origin_y - spec.label_height_mm - 3.0
        _engrave_text(program, label, x, y, spec)

    # Leyenda de ejes
    _engrave_text(program, "S", origin_x - 10.0, origin_y + height + 4.0, spec)
    _engrave_text(program, "F", origin_x + width + 4.0, origin_y - spec.label_height_mm - 3.0, spec)

    if spec.draw_border:
        program.rectangle(
            origin_x - 14.0,
            origin_y - 9.0,
            width + 20.0,
            height + 15.0,
            feed=spec.label_speed,
            power=spec.label_power,
        )

    program.postamble()
    return program


def build_focus_ramp(
    *,
    length_mm: float = 80.0,
    power: int = 500,
    speed: int = 2000,
    origin: tuple[float, float] = (10.0, 10.0),
    ticks_every_mm: float = 10.0,
) -> GcodeProgram:
    """Línea única para encontrar el foco exacto sobre una pieza inclinada.

    Se apoya una tablita con una inclinación conocida (unos 10 mm de
    desnivel a lo largo de la línea) y se graba una sola pasada. El punto
    donde la línea sale más fina y más oscura es el foco. Las marcas cada
    10 mm sirven para medir a qué altura corresponde.

    Con foco manual como el de la S30 este truco te ahorra mucho tiempo
    perdido, sobre todo cada vez que cambiás de espesor de material.
    """
    program = GcodeProgram(GcodeOptions(dynamic_power=True))
    program.preamble("rampa de foco")
    program.comment(f"apoyar la pieza con desnivel conocido a lo largo de {length_mm:g}mm")
    x0, y0 = origin
    program.rapid(x0, y0)
    program.cut(x0 + length_mm, feed=speed, power=power)
    program.set_power(0)

    position = 0.0
    while position <= length_mm:
        program.rapid(x0 + position, y0 + 2.0)
        program.cut(x0 + position, y0 + 5.0, feed=speed, power=power)
        program.set_power(0)
        position += ticks_every_mm

    program.postamble()
    return program

