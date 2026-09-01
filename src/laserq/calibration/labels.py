"""Etiquetas grabadas al lado de cada celda de una placa de test.

Viven aparte porque las comparten las tres placas, y porque el criterio es
el mismo en todas: la etiqueta se graba **siempre con los mismos valores**,
aunque la celda que rotula use otros. Si la etiqueta cambiara junto con la
celda, en la mitad de la placa no se podría leer qué dice.
"""

from __future__ import annotations

from ..gcode.builder import GcodeProgram
from ..gcode.font import text_polylines

DEFAULT_LABEL_HEIGHT = 3.0
DEFAULT_LABEL_POWER = 350
DEFAULT_LABEL_SPEED = 2000


def engrave_label(
    program: GcodeProgram,
    text: str,
    x: float,
    y: float,
    height: float = DEFAULT_LABEL_HEIGHT,
    *,
    power: int = DEFAULT_LABEL_POWER,
    speed: int = DEFAULT_LABEL_SPEED,
    center: bool = False,
) -> None:
    """Graba un rótulo. Conservador a propósito: una etiqueta quemada no se lee."""
    for polyline in text_polylines(text, x, y, height, center=center):
        program.polyline(polyline, feed=speed, power=power)
