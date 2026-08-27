"""De un CSV de nombres a N piezas grabadas.

Este es el primer producto vendible del sistema: 200 termos con 200 nombres.
La competencia cotiza 200 diseños manuales; acá son 200 archivos generados
en unos segundos y encolados de una.

    python examples/lote_desde_csv.py nombres.csv --diametro 80 --largo 90

El CSV solo necesita una columna `nombre`. Cualquier otra columna se guarda
en el `meta` del job, así que después podés cruzar la pieza con el pedido.
"""

from __future__ import annotations

import argparse
import csv
import re
from pathlib import Path

from laserq.gcode.builder import GcodeOptions, GcodeProgram
from laserq.gcode.font import text_polylines, text_width
from laserq.gcode.rotary import ConeMapping, focus_band_width, rotary_preamble_notes
from laserq.gcode.rotary import RotaryConfig
from laserq.jobs import Job, JobQueue
from laserq.profiles import load_material


def slug(texto: str) -> str:
    limpio = re.sub(r"[^\w\s-]", "", texto, flags=re.UNICODE).strip().lower()
    return re.sub(r"[\s_-]+", "-", limpio) or "sin-nombre"


def generar_pieza(
    nombre: str,
    mapping: ConeMapping,
    *,
    speed: int,
    power: int,
    altura_texto: float,
    posicion_axial: float,
) -> GcodeProgram:
    """Genera el G-code de una pieza con el nombre centrado y corregido.

    La tipografía de trazo del proyecto es mínima a propósito. Para
    producción real acá va una fuente de verdad o un SVG convertido; lo que
    importa del ejemplo es el paso por `warp_polyline`, que es donde vive
    la corrección cónica.
    """
    program = GcodeProgram(GcodeOptions(dynamic_power=True, air_assist=True))
    program.preamble(f"pieza: {nombre}")
    for nota in rotary_preamble_notes(RotaryConfig(), mapping):
        program.comment(nota)

    ancho = text_width(nombre, altura_texto)
    banda = focus_band_width(mapping.diameter_start)
    if ancho > banda:
        program.comment(
            f"CUIDADO: el texto mide {ancho:.1f}mm y la franja de foco es "
            f"{banda:.1f}mm. Los extremos van a salir lavados."
        )

    # Coordenadas de diseño: u = arco desde el centro, v = posición axial.
    u0 = -ancho / 2
    v0 = posicion_axial - altura_texto / 2

    for polilinea in text_polylines(nombre, u0, v0, altura_texto):
        # (x=u, y=v) en el espacio del texto -> (u, v) en el del objeto.
        en_diseno = [(px, py) for px, py in polilinea]
        # El texto se genera con x horizontal; en el rotativo el horizontal
        # es el arco (u) y el vertical es el eje (v).
        en_objeto = [(u, v) for u, v in en_diseno]
        en_maquina = mapping.warp_polyline(en_objeto, max_segment_mm=0.8)
        program.polyline(en_maquina, feed=speed, power=power)

    program.postamble(park=None)  # sin park: el rotativo no tiene home útil en Y
    return program


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="CSV con una columna 'nombre'")
    parser.add_argument("--diametro", type=float, required=True, help="diámetro en la base")
    parser.add_argument("--diametro-tope", type=float, help="diámetro arriba (si es cónico)")
    parser.add_argument("--largo", type=float, default=90.0, help="largo axial en mm")
    parser.add_argument("--altura-texto", type=float, default=8.0)
    parser.add_argument("--material", default="termo_acero_rotativo")
    parser.add_argument("--salida", default="out/lote", help="directorio de G-code")
    parser.add_argument("--db", default="laserq.db")
    parser.add_argument("--encolar", action="store_true", help="además de generar, encola")
    args = parser.parse_args()

    perfil = load_material(args.material)
    mapping = ConeMapping(
        diameter_start=args.diametro,
        diameter_end=args.diametro_tope or args.diametro,
        length=args.largo,
    )

    destino = Path(args.salida)
    destino.mkdir(parents=True, exist_ok=True)

    filas = list(csv.DictReader(Path(args.csv).open(encoding="utf-8")))
    if not filas or "nombre" not in filas[0]:
        print("el CSV tiene que tener una columna 'nombre'")
        return 1

    jobs: list[Job] = []
    for indice, fila in enumerate(filas, start=1):
        nombre = (fila.get("nombre") or "").strip()
        if not nombre:
            continue
        program = generar_pieza(
            nombre,
            mapping,
            speed=perfil.speed,
            power=perfil.power,
            altura_texto=args.altura_texto,
            posicion_axial=args.largo / 2,
        )
        ruta = destino / f"{indice:03d}-{slug(nombre)}.gcode"
        program.save(ruta)
        jobs.append(Job(
            name=nombre,
            gcode_path=str(ruta.resolve()),
            material=args.material,
            lines_total=len(program),
            meta={k: v for k, v in fila.items() if k != "nombre"},
        ))

    print(f"{len(jobs)} piezas generadas en {destino}/")
    if mapping.is_conical:
        print(f"cónico: corrección de arco aplicada "
              f"(semiángulo {mapping.taper_angle_deg:.2f}°)")

    if args.encolar:
        with JobQueue(args.db) as queue:
            queue.add_batch(jobs)
        print(f"encoladas. Corré: laserq queue work")
    else:
        print("agregá --encolar para mandarlas a la cola")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
