"""Previsualización de G-code: dibuja el recorrido antes de quemar nada.

Mirar el archivo antes de mandarlo a la máquina es la forma más barata de
encontrar errores. Un diseño espejado, un texto que se sale de la pieza o
una corrección cónica mal parametrizada se ven de una en la imagen y son
media hora de material y de tiempo si te enterás después.

Los movimientos con láser encendido se dibujan con la intensidad de su
potencia; los traslados en gris tenue. Si ves gris cruzando el dibujo,
hay recorrido desperdiciado que se puede optimizar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

_WORD_RE = re.compile(r"([A-Za-z])\s*(-?\d*\.?\d+)")


@dataclass
class Segment:
    x0: float
    y0: float
    x1: float
    y1: float
    power: float  # 0 = traslado


def parse_segments(lines: Iterable[str], max_power: float = 1000.0) -> list[Segment]:
    """Convierte el programa en segmentos con su potencia.

    Es un intérprete deliberadamente mínimo: G0/G1, modales de F y S, M3/M4/M5.
    No maneja arcos (G2/G3) ni cambios de sistema de coordenadas, porque el
    generador de este proyecto no los emite. Si algún día se agregan, esto
    hay que ampliarlo o va a mentir.
    """
    segments: list[Segment] = []
    x = y = 0.0
    power = 0.0
    laser_enabled = False

    for raw in lines:
        line = raw.split(";", 1)[0].strip()
        if not line:
            continue
        words = {letter.upper(): float(value) for letter, value in _WORD_RE.findall(line)}
        upper = line.upper()

        if "M5" in upper:
            laser_enabled = False
        if "M3" in upper or "M4" in upper:
            laser_enabled = True
        if "S" in words:
            power = words["S"]

        motion = None
        if "G" in words:
            code = words["G"]
            if code in (0.0, 1.0):
                motion = int(code)
        if motion is None:
            continue

        new_x = words.get("X", x)
        new_y = words.get("Y", y)
        if new_x != x or new_y != y:
            effective = power if (motion == 1 and laser_enabled) else 0.0
            segments.append(Segment(x, y, new_x, new_y, effective / max_power))
            x, y = new_x, new_y

    return segments


def render(
    path: str | Path,
    out: str | Path,
    *,
    max_power: float = 1000.0,
    show_travel: bool = True,
    dpi: int = 150,
    width_in: float = 8.0,
) -> Path:
    """Dibuja un archivo de G-code a PNG. Devuelve la ruta de la imagen."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.collections import LineCollection
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "la previsualización necesita matplotlib: pip install matplotlib"
        ) from exc

    lines = Path(path).read_text(encoding="ascii", errors="replace").splitlines()
    segments = parse_segments(lines, max_power=max_power)
    if not segments:
        raise ValueError(f"{path}: no hay movimientos para dibujar")

    burns = [s for s in segments if s.power > 0]
    travels = [s for s in segments if s.power <= 0]

    xs = [v for s in segments for v in (s.x0, s.x1)]
    ys = [v for s in segments for v in (s.y0, s.y1)]
    span_x = max(max(xs) - min(xs), 1.0)
    span_y = max(max(ys) - min(ys), 1.0)

    figure, axes = plt.subplots(figsize=(width_in, width_in * span_y / span_x))

    if show_travel and travels:
        axes.add_collection(LineCollection(
            [[(s.x0, s.y0), (s.x1, s.y1)] for s in travels],
            colors="#c8d4e0", linewidths=0.4, zorder=1,
        ))
    if burns:
        axes.add_collection(LineCollection(
            [[(s.x0, s.y0), (s.x1, s.y1)] for s in burns],
            colors=[(0.1, 0.1, 0.1, min(1.0, 0.25 + 0.75 * s.power)) for s in burns],
            linewidths=0.7, zorder=2,
        ))

    axes.set_xlim(min(xs) - span_x * 0.03, max(xs) + span_x * 0.03)
    axes.set_ylim(min(ys) - span_y * 0.03, max(ys) + span_y * 0.03)
    axes.set_aspect("equal")
    axes.set_xlabel("X (mm)")
    axes.set_ylabel("Y (mm)")
    axes.grid(True, alpha=0.2, linewidth=0.4)
    axes.set_title(
        f"{Path(path).name} — {len(burns)} grabados, {len(travels)} traslados",
        fontsize=10,
    )

    out_path = Path(out)
    figure.savefig(out_path, dpi=dpi, bbox_inches="tight")
    plt.close(figure)
    return out_path


def travel_distance(segments: list[Segment]) -> tuple[float, float]:
    """(distancia grabando, distancia en traslados), en mm.

    La proporción entre las dos es la métrica de eficiencia del job. Si los
    traslados superan al grabado, hay orden de recorrido para optimizar.
    """
    import math

    burn = travel = 0.0
    for segment in segments:
        length = math.hypot(segment.x1 - segment.x0, segment.y1 - segment.y0)
        if segment.power > 0:
            burn += length
        else:
            travel += length
    return burn, travel
