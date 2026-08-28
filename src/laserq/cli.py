"""Interfaz de línea de comandos.

    laserq status                     estado de la máquina
    laserq settings [--apply]         verifica (y opcionalmente corrige) los $N
    laserq home                       ciclo de homing
    laserq jog --x 50 --y 30          mueve el cabezal para alinearlo con el material
    laserq set-origin                 fija la posición actual como (0,0) del próximo job
    laserq testcard --material mdf3   genera la placa de test
    laserq focus-ramp                 genera la rampa de búsqueda de foco
    laserq raster foto.png -w 80      imagen -> G-code
    laserq rotary-info -d 80          números del rotativo para un objeto
    laserq preview archivo.gcode      dibuja el recorrido a PNG
    laserq check archivo.gcode        bounding box y validación sin grabar
    laserq run archivo.gcode          graba un archivo
    laserq queue add|list|work        cola de jobs
    laserq queue work --no-home       igual, sin homear (rotativo, set-origin)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .driver import Connection, ConnectionConfig, FakeConnection, Machine
from .driver.machine import REQUIRED_SETTINGS, SETTING_NAMES
from .gcode.builder import measure
from .jobs import HOME_POLICIES, Job, JobQueue, JobState, Worker
from .profiles import list_materials, load_machine, load_material


def _connect(args) -> Machine:
    if getattr(args, "fake", False):
        connection = FakeConnection()
    else:
        machine_profile = load_machine(args.profiles)
        port = args.port or machine_profile.port
        connection = Connection(ConnectionConfig(port=port, baudrate=machine_profile.baudrate))
    connection.open()
    return Machine(connection)


# ------------------------------------------------------------------ comandos


def cmd_status(args) -> int:
    machine = _connect(args)
    print(machine.status())
    return 0


def cmd_settings(args) -> int:
    machine = _connect(args)
    machine.read_settings()
    mismatches = machine.check_settings()

    if not mismatches:
        print("todos los parámetros críticos están bien")
        return 0

    print("parámetros que no coinciden con lo esperado:\n")
    for number, (actual, expected) in sorted(mismatches.items()):
        name = SETTING_NAMES.get(number, "")
        shown = "sin definir" if actual is None else f"{actual:g}"
        print(f"  ${number:<4} {name:<28} actual={shown:<12} esperado={expected:g}")

    if args.apply:
        print("\naplicando...")
        machine.apply_settings({n: v for n, (_, v) in mismatches.items()})
        print("listo. Los cambios quedan en la EEPROM.")
    else:
        print("\ncorré con --apply para corregirlos")
    return 0


def cmd_home(args) -> int:
    machine = _connect(args)
    print("homing...")
    machine.home()
    print(machine.status())
    return 0


def cmd_testcard(args) -> int:
    from .calibration import TestCardSpec, build_test_card

    spec = TestCardSpec()
    if args.powers:
        spec.powers = [int(v) for v in args.powers.split(",")]
    if args.speeds:
        spec.speeds = [int(v) for v in args.speeds.split(",")]
    if args.cell:
        spec.cell_mm = args.cell

    program = build_test_card(spec, material=args.material or "")
    width, height = spec.total_size
    program.save(args.out)
    print(f"{args.out}: {len(program)} líneas, placa de ~{width + 20:.0f}x{height + 15:.0f} mm")
    print(f"potencias {spec.powers}")
    print(f"velocidades {spec.speeds}")
    return 0


def cmd_focus_ramp(args) -> int:
    from .calibration import build_focus_ramp

    program = build_focus_ramp(length_mm=args.length, power=args.power, speed=args.speed)
    program.save(args.out)
    print(f"{args.out}: {len(program)} líneas")
    print("apoyá la pieza inclinada con un desnivel conocido a lo largo de la línea")
    return 0


def cmd_raster(args) -> int:
    from .gcode.raster import RasterOptions, engrave_image, estimate_time

    options = RasterOptions(
        dpi=args.dpi,
        speed=args.speed,
        max_power=args.power,
        mode=args.dither,
        gamma=args.gamma,
        invert=args.invert,
        overscan_mm=args.overscan,
    )
    if args.material:
        profile = load_material(args.material, args.profiles)
        options.speed = profile.speed
        options.max_power = profile.power
        options.dpi = profile.effective_dpi
        options.mode = profile.dither
        options.gamma = profile.gamma
        print(f"usando perfil {profile.name}: F{profile.speed} S{profile.power} {profile.dither}")

    program = engrave_image(args.image, options, width_mm=args.width, height_mm=args.height)
    program.save(args.out)
    seconds = estimate_time(program, options)
    print(f"{args.out}: {len(program)} líneas")
    print(f"extensión: {measure(list(program))}")
    print(f"tiempo estimado: {seconds / 60:.1f} min (sin contar aceleración)")
    return 0


def cmd_rotary_info(args) -> int:
    from .gcode.rotary import ConeMapping, focus_band_width, full_turn_mm

    mapping = ConeMapping(
        diameter_start=args.diameter,
        diameter_end=args.diameter_end or args.diameter,
        length=args.length,
    )
    print(f"objeto: {mapping.diameter_start:g} -> {mapping.diameter_end:g} mm "
          f"en {mapping.length:g} mm")
    print(f"vuelta completa: {full_turn_mm(mapping.contact_diameter):.2f} mm de Y")
    print(f"franja útil de foco: {focus_band_width(mapping.diameter_start):.1f} mm de arco")
    if mapping.is_conical:
        print(f"CÓNICO: semiángulo {mapping.taper_angle_deg:.2f}°, hace falta corrección de arco")
        u = args.width / 2 if args.width else 20.0
        _, y_base = mapping.to_machine(u, 0.0)
        _, y_top = mapping.to_machine(u, mapping.length)
        print(f"un punto a {u:g} mm del centro se desplaza "
              f"{abs(y_top - y_base):.2f} mm de Y entre la base y el tope")
        print("(ese es exactamente el error que tendrías sin corregir)")
    else:
        print("cilíndrico: no hace falta corrección")
    return 0


def cmd_preview(args) -> int:
    from .gcode.preview import parse_segments, render, travel_distance

    lines = Path(args.file).read_text(encoding="ascii", errors="replace").splitlines()
    segments = parse_segments(lines)
    burn, travel = travel_distance(segments)
    out = render(args.file, args.out, show_travel=not args.no_travel)
    print(f"{out}: {len(segments)} segmentos")
    print(f"grabando {burn / 1000:.2f} m, trasladando {travel / 1000:.2f} m")
    if travel > burn:
        print("los traslados superan al grabado: hay orden de recorrido para optimizar")
    return 0


def cmd_check(args) -> int:
    lines = Path(args.file).read_text(encoding="ascii", errors="replace").splitlines()
    box = measure(lines)
    machine_profile = load_machine(args.profiles)
    print(f"{args.file}: {len(lines)} líneas")
    print(f"extensión: {box}")
    if box.is_empty:
        print("ADVERTENCIA: no hay movimientos en el archivo")
        return 1
    if box.min_x < 0 or box.min_y < 0:
        print("ADVERTENCIA: hay coordenadas negativas")
    if not machine_profile.fits(box.max_x, box.max_y):
        print(f"ADVERTENCIA: se sale del área de trabajo {machine_profile.work_area_mm}")
        return 1
    print("entra en el área de trabajo")
    return 0


def cmd_jog(args) -> int:
    machine = _connect(args)
    machine.jog(args.x, args.y, relative=args.relative, feed=args.feed)
    print(machine.status())
    return 0


def cmd_set_origin(args) -> int:
    machine = _connect(args)
    if args.clear:
        machine.clear_origin()
        print("origen de trabajo borrado, usando coordenadas absolutas de máquina")
    else:
        machine.set_origin()
        print("origen de trabajo fijado en la posición actual del cabezal")
    return 0


def cmd_run(args) -> int:
    lines = Path(args.file).read_text(encoding="ascii", errors="replace").splitlines()
    box = measure(lines)
    print(f"{args.file}: {len(lines)} líneas, extensión {box}")

    if not args.yes:
        answer = input("¿arrancar? [s/N] ").strip().lower()
        if answer not in ("s", "si", "sí", "y", "yes"):
            print("cancelado")
            return 1

    machine = _connect(args)
    if not args.no_home:
        machine.home()

    def on_progress(progress) -> None:
        fraction = progress.fraction
        if fraction is not None:
            print(f"\r{fraction * 100:5.1f}%  ETA {(progress.eta or 0) / 60:.1f} min",
                  end="", flush=True)

    from .driver.machine import wait_until_idle

    progress = machine.run(lines, total=len(lines), on_progress=on_progress)
    wait_until_idle(machine)
    print(f"\nlisto en {progress.elapsed / 60:.1f} min")
    return 0


def cmd_queue(args) -> int:
    queue = JobQueue(args.db)

    if args.queue_command == "add":
        path = Path(args.file).resolve()
        lines = len(path.read_text(encoding="ascii", errors="replace").splitlines())
        job = queue.add(Job(
            name=args.name or path.stem,
            gcode_path=str(path),
            material=args.material or "",
            priority=args.priority,
            lines_total=lines,
        ))
        print(f"job #{job.id} encolado: {job.name}")
        return 0

    if args.queue_command == "list":
        state = JobState(args.state) if args.state else None
        jobs = queue.list(state)
        if not jobs:
            print("la cola está vacía")
            return 0
        for job in jobs:
            extra = f" ({job.error})" if job.error else ""
            print(f"#{job.id:<5} {job.state.value:<10} {job.name:<28} {job.material}{extra}")
        print()
        print("  ".join(f"{k}={v}" for k, v in sorted(queue.counts().items())))
        return 0

    if args.queue_command == "work":
        machine = _connect(args)
        machine_profile = load_machine(args.profiles)
        worker = Worker(
            machine, queue,
            confirm_each=not args.no_confirm,
            home_policy=args.home,
            work_area=machine_profile.work_area_mm,
        )
        if args.home == "never":
            print("sin homing: asegurate de que el origen ya esté donde corresponde")
        stats = worker.run_forever(max_jobs=args.max_jobs)
        print(f"\nlistos={stats.completed} fallados={stats.failed} salteados={stats.skipped}")
        return 0

    return 1


def cmd_materials(args) -> int:
    names = list_materials(args.profiles)
    if not names:
        print(f"no hay perfiles en {args.profiles}/materials")
        return 1
    for name in names:
        profile = load_material(name, args.profiles)
        verified = f" (verificado {profile.verified_on})" if profile.verified_on else " (SIN VERIFICAR)"
        print(f"{name:<24} {profile.operation:<8} F{profile.speed:<6} S{profile.power:<5} "
              f"x{profile.passes}{verified}")
    return 0


# -------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="laserq", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", help="puerto serie (pisa el de machine.yaml)")
    parser.add_argument("--profiles", default="profiles", help="directorio de perfiles")
    parser.add_argument("--fake", action="store_true",
                        help="usa una máquina simulada, sin hardware")
    parser.add_argument("--db", default="laserq.db", help="base de datos de la cola")

    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="estado de la máquina").set_defaults(func=cmd_status)

    p = sub.add_parser("settings", help="verifica los parámetros $N")
    p.add_argument("--apply", action="store_true", help="corrige los que no coinciden")
    p.set_defaults(func=cmd_settings)

    sub.add_parser("home", help="ciclo de homing").set_defaults(func=cmd_home)

    p = sub.add_parser("jog", help="mueve el cabezal sin grabar (alinear con el material)")
    p.add_argument("--x", type=float, help="X destino en mm")
    p.add_argument("--y", type=float, help="Y destino en mm")
    p.add_argument("--rel", dest="relative", action="store_true",
                   help="mover relativo a la posición actual en vez de absoluto")
    p.add_argument("--feed", type=float, default=1500.0, help="velocidad de traslado (mm/min)")
    p.set_defaults(func=cmd_jog)

    p = sub.add_parser(
        "set-origin",
        help="fija la posición actual del cabezal como (0,0) del próximo job",
    )
    p.add_argument("--clear", action="store_true",
                   help="volver a coordenadas absolutas de máquina en vez de fijar")
    p.set_defaults(func=cmd_set_origin)

    p = sub.add_parser("testcard", help="genera una placa de test potencia/velocidad")
    p.add_argument("-o", "--out", default="testcard.gcode")
    p.add_argument("-m", "--material", help="nombre para el encabezado")
    p.add_argument("--powers", help="lista separada por comas, ej: 200,400,600,800,1000")
    p.add_argument("--speeds", help="lista separada por comas, ej: 1000,3000,6000")
    p.add_argument("--cell", type=float, help="lado de la celda en mm")
    p.set_defaults(func=cmd_testcard)

    p = sub.add_parser("focus-ramp", help="línea única para encontrar el foco")
    p.add_argument("-o", "--out", default="focus.gcode")
    p.add_argument("--length", type=float, default=80.0)
    p.add_argument("--power", type=int, default=500)
    p.add_argument("--speed", type=int, default=2000)
    p.set_defaults(func=cmd_focus_ramp)

    p = sub.add_parser("raster", help="imagen -> G-code")
    p.add_argument("image")
    p.add_argument("-o", "--out", default="raster.gcode")
    p.add_argument("-w", "--width", type=float, help="ancho final en mm")
    p.add_argument("--height", type=float, help="alto final en mm")
    p.add_argument("-m", "--material", help="perfil de material a usar")
    p.add_argument("--dpi", type=int, default=254)
    p.add_argument("--speed", type=int, default=3000)
    p.add_argument("--power", type=int, default=800)
    p.add_argument("--dither", default="jarvis",
                   choices=["floyd-steinberg", "jarvis", "atkinson", "threshold", "grayscale"])
    p.add_argument("--gamma", type=float, default=1.0)
    p.add_argument("--invert", action="store_true")
    p.add_argument("--overscan", type=float, default=3.0)
    p.set_defaults(func=cmd_raster)

    p = sub.add_parser("rotary-info", help="números del rotativo para un objeto")
    p.add_argument("-d", "--diameter", type=float, required=True, help="diámetro base en mm")
    p.add_argument("--diameter-end", type=float, help="diámetro del otro extremo (cónico)")
    p.add_argument("-l", "--length", type=float, default=100.0, help="largo axial en mm")
    p.add_argument("-w", "--width", type=float, help="ancho del diseño en mm")
    p.set_defaults(func=cmd_rotary_info)

    p = sub.add_parser("preview", help="dibuja un G-code a PNG antes de grabarlo")
    p.add_argument("file")
    p.add_argument("-o", "--out", default="preview.png")
    p.add_argument("--no-travel", action="store_true", help="no dibujar los traslados")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("check", help="valida un G-code sin grabarlo")
    p.add_argument("file")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="graba un archivo de G-code")
    p.add_argument("file")
    p.add_argument("-y", "--yes", action="store_true", help="no pedir confirmación")
    p.add_argument("--no-home", action="store_true")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("materials", help="lista los perfiles de material")
    p.set_defaults(func=cmd_materials)

    p = sub.add_parser("queue", help="cola de jobs")
    qsub = p.add_subparsers(dest="queue_command", required=True)
    q = qsub.add_parser("add")
    q.add_argument("file")
    q.add_argument("--name")
    q.add_argument("--material")
    q.add_argument("--priority", type=int, default=0)
    q = qsub.add_parser("list")
    q.add_argument("--state", choices=[s.value for s in JobState])
    q = qsub.add_parser("work")
    q.add_argument("--no-confirm", action="store_true",
                   help="NO usar sin gabinete cerrado y enclavamiento")
    q.add_argument("--home", choices=HOME_POLICIES, default="once",
                   help="once: homea antes del primer job (por defecto). "
                        "each: antes de cada uno. never: nunca")
    q.add_argument("--no-home", dest="home", action="store_const", const="never",
                   help="atajo de --home never. OBLIGATORIO con el rotativo "
                        "montado y con set-origin")
    q.add_argument("--max-jobs", type=int)
    p.set_defaults(func=cmd_queue)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\ninterrumpido")
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
