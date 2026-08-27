"""Grabado raster: imagen -> líneas de barrido con potencia modulada.

Decisiones que afectan directamente la calidad de la pieza:

**Overscan.** El cabezal necesita distancia para acelerar y frenar. Si la
línea de grabado arranca justo en el borde de la imagen, los primeros
milímetros se graban mientras todavía está acelerando: con M4 la potencia
sigue a la velocidad, así que salen más claros, y se ve como un degradé en
los bordes izquierdo y derecho. La solución es empezar el movimiento unos
milímetros afuera, con el láser apagado.

**Barrido bidireccional.** Grabar solo de izquierda a derecha desperdicia
la mitad del tiempo en viajes de retorno. Yendo y viniendo se duplica el
throughput, a costa de que cualquier juego mecánico en la correa aparezca
como un desfasaje entre líneas pares e impares (el clásico "efecto
fantasma"). Para eso está `backlash_mm`: se mide una vez con una placa de
test y se compensa.

**Agrupar píxeles iguales.** Un G1 por píxel a 254 DPI son 10 líneas por
milímetro. Agrupando los tramos de igual potencia en un solo movimiento se
reduce el G-code en un orden de magnitud, y eso es directamente más
lookahead disponible en el buffer de GRBL.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from .builder import GcodeOptions, GcodeProgram

# --------------------------------------------------------------------- dither

#: Matrices de difusión de error: (dx, dy, peso). El divisor es la suma.
DIFFUSION_KERNELS: dict[str, tuple[tuple[int, int, int], ...]] = {
    # Floyd-Steinberg: el clásico. Rápido y con buen detalle.
    "floyd-steinberg": (
        (1, 0, 7),
        (-1, 1, 3),
        (0, 1, 5),
        (1, 1, 1),
    ),
    # Jarvis-Judice-Ninke: difunde más lejos. Degradés más suaves, un poco
    # menos de nitidez. Suele ser el mejor para fotos sobre madera.
    "jarvis": (
        (1, 0, 7), (2, 0, 5),
        (-2, 1, 3), (-1, 1, 5), (0, 1, 7), (1, 1, 5), (2, 1, 3),
        (-2, 2, 1), (-1, 2, 3), (0, 2, 5), (1, 2, 3), (2, 2, 1),
    ),
    # Atkinson: solo difunde 3/4 del error. Más contraste, menos "sucio".
    # Va muy bien en materiales que se saturan rápido, como el cuero.
    "atkinson": (
        (1, 0, 1), (2, 0, 1),
        (-1, 1, 1), (0, 1, 1), (1, 1, 1),
        (0, 2, 1),
    ),
}
ATKINSON_DIVISOR = 8  # difunde 6/8: el resto del error se descarta a propósito


@dataclass
class RasterOptions:
    """Parámetros de un grabado raster."""

    dpi: int = 254  # 254 DPI = 0.1 mm por píxel, un buen punto de partida
    speed: int = 3000  # mm/min
    max_power: int = 800  # 0..$30
    min_power: int = 0
    #: "floyd-steinberg" | "jarvis" | "atkinson" | "threshold" | "grayscale"
    mode: str = "jarvis"
    threshold: int = 128
    invert: bool = False
    #: Gamma > 1 aclara los medios tonos. La madera oscurece de forma no
    #: lineal con la energía; 1.4-1.8 suele acercar bastante.
    gamma: float = 1.0
    overscan_mm: float = 3.0
    bidirectional: bool = True
    backlash_mm: float = 0.0
    #: Salta filas completamente vacías con un solo G0.
    skip_blank: bool = True
    line_interval_mm: float | None = None  # si se define, pisa el dpi

    @property
    def pixel_mm(self) -> float:
        if self.line_interval_mm:
            return self.line_interval_mm
        return 25.4 / self.dpi


# ------------------------------------------------------------------ pipeline


def load_grayscale(path: str | Path, options: RasterOptions, width_mm: float | None = None,
                   height_mm: float | None = None) -> tuple[list[list[float]], int, int]:
    """Abre una imagen y la deja como matriz de floats 0..1 (0 = sin grabar).

    Devuelve (filas, ancho_px, alto_px). La fila 0 es la de arriba.
    """
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("hace falta Pillow: pip install pillow") from exc

    image = Image.open(path)
    if image.mode in ("RGBA", "LA", "P"):
        # Aplanar sobre blanco: la transparencia debe quedar sin grabar,
        # no negra, que es lo que pasa si convertís directo a "L".
        image = image.convert("RGBA")
        background = Image.new("RGBA", image.size, (255, 255, 255, 255))
        image = Image.alpha_composite(background, image)
    image = image.convert("L")

    pixel_mm = options.pixel_mm
    if width_mm:
        target_w = max(1, round(width_mm / pixel_mm))
        target_h = round(target_w * image.height / image.width)
    elif height_mm:
        target_h = max(1, round(height_mm / pixel_mm))
        target_w = round(target_h * image.width / image.height)
    else:
        target_w, target_h = image.width, image.height

    from PIL import Image as _Image

    image = image.resize((max(1, target_w), max(1, target_h)), _Image.LANCZOS)

    rows: list[list[float]] = []
    data = list(image.getdata())
    for y in range(image.height):
        row = data[y * image.width : (y + 1) * image.width]
        converted = []
        for value in row:
            # 0..255 (255 = blanco) -> 0..1 (1 = grabar a fondo)
            level = 1.0 - value / 255.0
            if options.invert:
                level = 1.0 - level
            if options.gamma != 1.0:
                level = level ** (1.0 / options.gamma)
            converted.append(level)
        rows.append(converted)
    return rows, image.width, image.height


def dither(rows: list[list[float]], options: RasterOptions) -> list[list[float]]:
    """Aplica el algoritmo elegido. Devuelve una matriz nueva de 0..1.

    En modo binario los valores salen 0.0 o 1.0; en "grayscale" salen tal cual
    y la modulación la hace la potencia del láser.
    """
    if options.mode == "grayscale":
        return [row[:] for row in rows]

    height = len(rows)
    width = len(rows[0]) if height else 0

    if options.mode == "threshold":
        cut = options.threshold / 255.0
        return [[1.0 if v >= cut else 0.0 for v in row] for row in rows]

    kernel = DIFFUSION_KERNELS.get(options.mode)
    if kernel is None:
        raise ValueError(
            f"modo de dithering desconocido: {options.mode!r}. "
            f"Opciones: {', '.join(sorted(DIFFUSION_KERNELS))}, threshold, grayscale"
        )
    divisor = ATKINSON_DIVISOR if options.mode == "atkinson" else sum(w for _, _, w in kernel)

    # Copia de trabajo en float: el error se acumula acá.
    work = [row[:] for row in rows]
    out = [[0.0] * width for _ in range(height)]

    for y in range(height):
        for x in range(width):
            old = work[y][x]
            new = 1.0 if old >= 0.5 else 0.0
            out[y][x] = new
            error = old - new
            if error == 0.0:
                continue
            for dx, dy, weight in kernel:
                nx, ny = x + dx, y + dy
                if 0 <= nx < width and 0 <= ny < height:
                    work[ny][nx] += error * weight / divisor
    return out


def _runs(values: Sequence[float], quantize: Callable[[float], int]) -> list[tuple[int, int, int]]:
    """Agrupa la fila en tramos (inicio, fin_exclusivo, potencia)."""
    runs: list[tuple[int, int, int]] = []
    if not values:
        return runs
    start = 0
    current = quantize(values[0])
    for index in range(1, len(values)):
        power = quantize(values[index])
        if power != current:
            runs.append((start, index, current))
            start, current = index, power
    runs.append((start, len(values), current))
    return runs


def raster_to_gcode(
    rows: list[list[float]],
    options: RasterOptions,
    *,
    origin: tuple[float, float] = (0.0, 0.0),
    program: GcodeProgram | None = None,
    title: str = "raster",
) -> GcodeProgram:
    """Convierte la matriz ya ditherizada en un programa de barrido."""
    program = program or GcodeProgram(
        GcodeOptions(max_power=options.max_power, dynamic_power=True)
    )
    if not rows:
        return program

    pixel = options.pixel_mm
    height_px = len(rows)
    width_px = len(rows[0])
    origin_x, origin_y = origin
    span = options.max_power - options.min_power

    def quantize(level: float) -> int:
        if level <= 0.0:
            return 0
        power = options.min_power + span * min(1.0, level)
        return int(round(power))

    program.preamble(f"{title} · {width_px}x{height_px}px @ {options.dpi}dpi · "
                     f"{width_px * pixel:.1f}x{height_px * pixel:.1f}mm")
    program.comment(f"modo={options.mode} F={options.speed} S={options.min_power}..{options.max_power}")

    left_to_right = True
    for row_index in range(height_px):
        row = rows[row_index]
        # La fila 0 de la imagen es la de arriba; la máquina crece hacia arriba en Y.
        y = origin_y + (height_px - 1 - row_index) * pixel

        runs = _runs(row, quantize)
        burning = [run for run in runs if run[2] > 0]
        if not burning:
            if options.skip_blank:
                continue
            burning = []

        if not left_to_right:
            runs = list(reversed(runs))

        first_burn = next((run for run in runs if run[2] > 0), None)
        last_burn = next((run for run in reversed(runs) if run[2] > 0), None)
        if first_burn is None or last_burn is None:
            continue

        backlash = 0.0 if left_to_right else -options.backlash_mm

        if left_to_right:
            start_x = origin_x + first_burn[0] * pixel - options.overscan_mm
            program.rapid(start_x + backlash, y)
            program.rapid(origin_x + first_burn[0] * pixel + backlash, y)
            for run_start, run_end, power in runs:
                if run_end <= first_burn[0] or run_start >= last_burn[1]:
                    continue
                x_end = origin_x + run_end * pixel + backlash
                program.cut(x_end, feed=options.speed, power=power)
        else:
            start_x = origin_x + first_burn[1] * pixel + options.overscan_mm
            program.rapid(start_x + backlash, y)
            program.rapid(origin_x + first_burn[1] * pixel + backlash, y)
            for run_start, run_end, power in runs:
                if run_start >= first_burn[1] or run_end <= last_burn[0]:
                    continue
                x_end = origin_x + run_start * pixel + backlash
                program.cut(x_end, feed=options.speed, power=power)

        program.set_power(0)
        if options.bidirectional:
            left_to_right = not left_to_right

    program.postamble()
    return program


def engrave_image(
    path: str | Path,
    options: RasterOptions,
    *,
    width_mm: float | None = None,
    height_mm: float | None = None,
    origin: tuple[float, float] = (0.0, 0.0),
) -> GcodeProgram:
    """Atajo: archivo de imagen -> programa de G-code listo para mandar."""
    rows, _, _ = load_grayscale(path, options, width_mm=width_mm, height_mm=height_mm)
    dithered = dither(rows, options)
    return raster_to_gcode(
        dithered, options, origin=origin, title=Path(path).name
    )


def estimate_time(program, options: RasterOptions) -> float:
    """Estimación grosera de duración en segundos, sin considerar aceleración.

    Sirve para saber si un job son 4 minutos o 4 horas. Para el número real
    hay que modelar el planificador de GRBL, y no vale la pena.
    """
    from .builder import measure

    lines = list(program)
    box = measure(lines)
    if box.is_empty:
        return 0.0
    rows = max(1, int(box.height / options.pixel_mm))
    distance = rows * (box.width + 2 * options.overscan_mm)
    return distance / (options.speed / 60.0)
