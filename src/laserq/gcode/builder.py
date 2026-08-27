"""Construcción de programas de G-code para láser.

Convenciones que respeta todo el proyecto:

* **M4 (potencia dinámica), no M3.** Con `$32=1`, M4 escala la potencia según
  la velocidad real del cabezal. En las esquinas y en los extremos de cada
  línea la máquina desacelera; con M3 la potencia sigue clavada y te quema
  el material justo ahí. Es la diferencia entre bordes limpios y bordes
  con marca oscura.
* **Milímetros y coordenadas absolutas** (G21 G90). El modo incremental
  acumula error de redondeo a lo largo de miles de líneas de raster.
* **S entre 0 y `$30`** (1000 por defecto). Nunca porcentajes.
* **M8/M9 para el aire.** La S30 Pro Max controla la bomba desde la placa,
  así que el soplado es parte del programa y no algo que te olvidás de
  encender.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator


@dataclass
class GcodeOptions:
    max_power: int = 1000
    dynamic_power: bool = True  # M4 vs M3
    air_assist: bool = True
    travel_feed: int = 6000
    #: Cantidad de decimales en las coordenadas. Tres es más que suficiente
    #: para 0.05 mm de precisión y cada decimal de más son bytes que le
    #: sacás al buffer de 128.
    precision: int = 3


class GcodeProgram:
    """Acumulador de líneas con helpers para no escribir strings a mano."""

    def __init__(self, options: GcodeOptions | None = None):
        self.options = options or GcodeOptions()
        self.lines: list[str] = []
        self._current_feed: float | None = None
        self._current_power: float | None = None
        self._laser_on = False

    # ---------------------------------------------------------------- salida

    def __iter__(self) -> Iterator[str]:
        return iter(self.lines)

    def __len__(self) -> int:
        return len(self.lines)

    def emit(self, line: str) -> None:
        self.lines.append(line)

    def comment(self, text: str) -> None:
        """Comentario de una línea. Se filtra antes de mandarlo a la máquina."""
        self.emit(f"; {text}")

    def as_text(self) -> str:
        return "\n".join(self.lines) + "\n"

    def save(self, path) -> None:
        from pathlib import Path

        Path(path).write_text(self.as_text(), encoding="ascii")

    def _fmt(self, value: float) -> str:
        text = f"{value:.{self.options.precision}f}".rstrip("0").rstrip(".")
        return text if text not in ("", "-0") else "0"

    # ------------------------------------------------------------ estructura

    def preamble(self, title: str = "") -> None:
        if title:
            self.comment(title)
        self.comment("generado por laserq")
        self.emit("G21")  # milímetros
        self.emit("G90")  # absolutas
        self.emit("G17")  # plano XY
        self.emit("M5 S0")  # arrancar siempre con el láser apagado
        if self.options.air_assist:
            self.emit("M8")
        mode = "M4" if self.options.dynamic_power else "M3"
        self.emit(f"{mode} S0")
        self._laser_on = True
        self._current_power = 0.0

    def postamble(self, park: tuple[float, float] | None = (0.0, 0.0)) -> None:
        self.emit("M5 S0")
        self._laser_on = False
        if self.options.air_assist:
            self.emit("M9")
        if park is not None:
            self.rapid(park[0], park[1])
        self.emit("M2")

    # ------------------------------------------------------------ movimiento

    def rapid(self, x: float | None = None, y: float | None = None) -> None:
        """Movimiento sin grabar. Fuerza S0 para que no quede rastro."""
        parts = ["G0"]
        if x is not None:
            parts.append(f"X{self._fmt(x)}")
        if y is not None:
            parts.append(f"Y{self._fmt(y)}")
        if self._current_power not in (None, 0.0):
            parts.append("S0")
            self._current_power = 0.0
        self.emit("".join(parts) if len(parts) > 1 else "G0")

    def cut(
        self,
        x: float | None = None,
        y: float | None = None,
        *,
        feed: float | None = None,
        power: float | None = None,
    ) -> None:
        """Movimiento grabando. Omite F y S si no cambiaron desde la línea anterior.

        Esa omisión no es cosmética: en un raster de 50.000 líneas, repetir
        `F3000` en cada una son 250 KB extra por el puerto serie y, sobre
        todo, menos líneas dentro del buffer de 128 bytes, que es lo que
        alimenta el lookahead del planificador.
        """
        parts = ["G1"]
        if x is not None:
            parts.append(f"X{self._fmt(x)}")
        if y is not None:
            parts.append(f"Y{self._fmt(y)}")
        if feed is not None and feed != self._current_feed:
            parts.append(f"F{feed:g}")
            self._current_feed = feed
        if power is not None and power != self._current_power:
            parts.append(f"S{power:g}")
            self._current_power = power
        self.emit("".join(parts))

    def set_power(self, power: float) -> None:
        if power != self._current_power:
            self.emit(f"S{power:g}")
            self._current_power = power

    def dwell(self, seconds: float) -> None:
        self.emit(f"G4 P{seconds:g}")

    # -------------------------------------------------------------- polilíneas

    def polyline(
        self,
        points: list[tuple[float, float]],
        *,
        feed: float,
        power: float,
        closed: bool = False,
    ) -> None:
        """Recorre una lista de puntos: rápido al primero, grabando el resto."""
        if not points:
            return
        self.rapid(*points[0])
        for point in points[1:]:
            self.cut(point[0], point[1], feed=feed, power=power)
        if closed and len(points) > 2:
            self.cut(points[0][0], points[0][1], feed=feed, power=power)
        self.set_power(0)

    def rectangle(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        *,
        feed: float,
        power: float,
    ) -> None:
        self.polyline(
            [(x, y), (x + width, y), (x + width, y + height), (x, y + height)],
            feed=feed,
            power=power,
            closed=True,
        )


@dataclass
class BoundingBox:
    min_x: float = float("inf")
    min_y: float = float("inf")
    max_x: float = float("-inf")
    max_y: float = float("-inf")

    def add(self, x: float, y: float) -> None:
        self.min_x = min(self.min_x, x)
        self.min_y = min(self.min_y, y)
        self.max_x = max(self.max_x, x)
        self.max_y = max(self.max_y, y)

    @property
    def is_empty(self) -> bool:
        return self.min_x > self.max_x

    @property
    def width(self) -> float:
        return 0.0 if self.is_empty else self.max_x - self.min_x

    @property
    def height(self) -> float:
        return 0.0 if self.is_empty else self.max_y - self.min_y

    def __str__(self) -> str:
        if self.is_empty:
            return "(vacío)"
        return (
            f"X[{self.min_x:.2f}..{self.max_x:.2f}] "
            f"Y[{self.min_y:.2f}..{self.max_y:.2f}] "
            f"({self.width:.2f} x {self.height:.2f} mm)"
        )


def measure(lines) -> BoundingBox:
    """Calcula el bounding box de un programa sin ejecutarlo.

    Correlo siempre antes de mandar un job: es la forma barata de darte
    cuenta de que el diseño se sale de la pieza o del área de la máquina.
    """
    box = BoundingBox()
    x = y = 0.0
    for raw in lines:
        line = raw.split(";", 1)[0].strip().upper()
        if not line.startswith(("G0", "G1")):
            continue
        for axis in ("X", "Y"):
            index = line.find(axis)
            if index == -1:
                continue
            number = []
            for char in line[index + 1 :]:
                if char.isdigit() or char in ".-+":
                    number.append(char)
                else:
                    break
            if not number:
                continue
            try:
                value = float("".join(number))
            except ValueError:
                continue
            if axis == "X":
                x = value
            else:
                y = value
        box.add(x, y)
    return box
