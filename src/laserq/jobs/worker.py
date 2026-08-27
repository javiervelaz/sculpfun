"""Worker: saca jobs de la cola y los ejecuta en la máquina.

Modo operador presente (el de ahora): `confirm_each=True`. El worker te
muestra el bounding box y el tiempo estimado y espera un enter antes de
encender el láser. Vos ponés la pieza, revisás que esté donde tiene que
estar, y confirmás.

Modo desatendido (más adelante): `confirm_each=False` más un enclavamiento
físico. No lo pongas en False hasta tener gabinete cerrado, extracción y
un interruptor de puerta cableado, porque en ese modo la máquina enciende
20W sin que nadie esté mirando.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..driver.errors import GrblAlarm, GrblError, JobAborted, LaserqError
from ..driver.machine import Machine, wait_until_idle
from ..gcode.builder import measure
from .queue import Job, JobQueue

ConfirmFn = Callable[[Job, str], bool]


def _default_confirm(job: Job, summary: str) -> bool:
    print(f"\n--- job #{job.id}: {job.name}")
    print(summary)
    answer = input("¿arrancar? [s/N] ").strip().lower()
    return answer in ("s", "si", "sí", "y", "yes")


@dataclass
class WorkerStats:
    completed: int = 0
    failed: int = 0
    skipped: int = 0


class Worker:
    def __init__(
        self,
        machine: Machine,
        queue: JobQueue,
        *,
        confirm_each: bool = True,
        confirm_fn: ConfirmFn | None = None,
        home_before_each: bool = True,
        work_area: tuple[float, float] | None = None,
    ):
        self.machine = machine
        self.queue = queue
        self.confirm_each = confirm_each
        self.confirm_fn = confirm_fn or _default_confirm
        self.home_before_each = home_before_each
        self.work_area = work_area
        self.stats = WorkerStats()

    def run_forever(self, poll_interval: float = 2.0, max_jobs: int | None = None) -> WorkerStats:
        recovered = self.queue.recover_stale()
        if recovered:
            print(f"se devolvieron {recovered} job(s) interrumpidos a la cola")

        processed = 0
        while max_jobs is None or processed < max_jobs:
            job = self.queue.claim_next()
            if job is None:
                if max_jobs is not None:
                    break
                time.sleep(poll_interval)
                continue
            self.run_job(job)
            processed += 1
        return self.stats

    def run_job(self, job: Job) -> None:
        path = Path(job.gcode_path)
        if not path.exists():
            self.queue.finish(job.id, error=f"no existe el archivo {path}")
            self.stats.failed += 1
            return

        lines = path.read_text(encoding="ascii", errors="replace").splitlines()
        box = measure(lines)
        summary = f"  archivo: {path.name}\n  líneas: {len(lines)}\n  extensión: {box}"

        if self.work_area and not box.is_empty:
            over_x = box.max_x > self.work_area[0] or box.min_x < 0
            over_y = box.max_y > self.work_area[1] or box.min_y < 0
            if over_x or over_y:
                # Esto sería un ALARM:2 en medio del job. Mejor pararlo acá.
                error = f"el job se sale del área de trabajo: {box}"
                self.queue.finish(job.id, error=error)
                self.stats.failed += 1
                print(f"job #{job.id} rechazado: {error}")
                return

        if self.confirm_each and not self.confirm_fn(job, summary):
            self.queue.requeue(job.id)
            self.stats.skipped += 1
            return

        try:
            if self.home_before_each:
                self.machine.home()

            def on_progress(progress) -> None:
                if job.id is not None:
                    self.queue.update_progress(job.id, progress.acked)
                fraction = progress.fraction
                if fraction is not None:
                    eta = progress.eta or 0
                    print(
                        f"\r  {fraction * 100:5.1f}%  "
                        f"{progress.acked}/{progress.total}  "
                        f"ETA {eta / 60:.1f} min",
                        end="",
                        flush=True,
                    )

            progress = self.machine.run(lines, total=len(lines), on_progress=on_progress)
            # El último `ok` significa "recibí la línea", no "terminé de moverme".
            wait_until_idle(self.machine)
            print()
            self.queue.finish(job.id, lines_done=progress.acked)
            self.stats.completed += 1
            print(f"job #{job.id} listo en {progress.elapsed / 60:.1f} min")

        except JobAborted:
            self.machine.laser_off()
            self.queue.finish(job.id, error="cortado por el operador")
            self.stats.failed += 1
            print(f"\njob #{job.id} cortado. La máquina necesita homing antes de seguir.")
            raise
        except (GrblError, GrblAlarm, LaserqError) as exc:
            self.machine.emergency_stop()
            self.queue.finish(job.id, error=str(exc))
            self.stats.failed += 1
            print(f"\njob #{job.id} falló: {exc}")
