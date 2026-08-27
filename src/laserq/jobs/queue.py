"""Cola de jobs sobre SQLite.

Por qué una cola desde el día uno, si al principio vas a estar parado al
lado de la máquina: porque la cola es el límite entre "un script que graba
algo" y "un servicio de fabricación". Hoy la dispara un botón; mañana la
dispara un webhook de una tienda, y el núcleo no cambia.

SQLite y no Postgres porque esto corre en la misma máquina que el láser,
tiene que sobrevivir a un corte de luz y no debería necesitar un servidor
adicional para grabar cincuenta llaveros.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

DEFAULT_DB = Path("laserq.db")


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class Job:
    id: int | None = None
    name: str = ""
    gcode_path: str = ""
    material: str = ""
    state: JobState = JobState.PENDING
    priority: int = 0
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    error: str | None = None
    lines_total: int | None = None
    lines_done: int = 0
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def duration(self) -> float | None:
        if self.started_at is None:
            return None
        end = self.finished_at or time.time()
        return end - self.started_at


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL,
    gcode_path   TEXT NOT NULL,
    material     TEXT DEFAULT '',
    state        TEXT NOT NULL DEFAULT 'pending',
    priority     INTEGER NOT NULL DEFAULT 0,
    created_at   REAL NOT NULL,
    started_at   REAL,
    finished_at  REAL,
    error        TEXT,
    lines_total  INTEGER,
    lines_done   INTEGER NOT NULL DEFAULT 0,
    meta         TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, priority DESC, id ASC);
"""


class JobQueue:
    def __init__(self, path: Path | str = DEFAULT_DB):
        self.path = Path(path)
        self._conn = sqlite3.connect(self.path, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        # WAL para que un lector (el dashboard) no bloquee al que graba.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "JobQueue":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    # ------------------------------------------------------------ escritura

    def add(self, job: Job) -> Job:
        cursor = self._conn.execute(
            """INSERT INTO jobs
               (name, gcode_path, material, state, priority, created_at, lines_total, meta)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                job.name,
                str(job.gcode_path),
                job.material,
                job.state.value,
                job.priority,
                job.created_at,
                job.lines_total,
                json.dumps(job.meta),
            ),
        )
        job.id = cursor.lastrowid
        return job

    def add_batch(self, jobs: list[Job]) -> list[Job]:
        """Encola varios en una sola transacción.

        Es el camino de "CSV de 200 nombres" a "200 piezas": generás los
        G-code, los encolás de una, y después la máquina come de la cola.
        """
        self._conn.execute("BEGIN")
        try:
            for job in jobs:
                self.add(job)
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        return jobs

    def claim_next(self) -> Job | None:
        """Toma el próximo pendiente y lo marca RUNNING de forma atómica.

        La atomicidad importa aunque hoy haya un solo proceso: el día que
        agregues una segunda máquina, dos workers no pueden agarrar el
        mismo job. Resolverlo ahora cuesta una línea de SQL.
        """
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                """SELECT * FROM jobs WHERE state='pending'
                   ORDER BY priority DESC, id ASC LIMIT 1"""
            ).fetchone()
            if row is None:
                self._conn.execute("COMMIT")
                return None
            now = time.time()
            self._conn.execute(
                "UPDATE jobs SET state=?, started_at=? WHERE id=?",
                (JobState.RUNNING.value, now, row["id"]),
            )
            self._conn.execute("COMMIT")
        except Exception:
            self._conn.execute("ROLLBACK")
            raise
        job = _row_to_job(row)
        job.state = JobState.RUNNING
        job.started_at = now
        return job

    def finish(self, job_id: int, *, error: str | None = None, lines_done: int = 0) -> None:
        state = JobState.FAILED if error else JobState.DONE
        self._conn.execute(
            "UPDATE jobs SET state=?, finished_at=?, error=?, lines_done=? WHERE id=?",
            (state.value, time.time(), error, lines_done, job_id),
        )

    def cancel(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE jobs SET state=?, finished_at=? WHERE id=? AND state='pending'",
            (JobState.CANCELLED.value, time.time(), job_id),
        )

    def requeue(self, job_id: int) -> None:
        """Vuelve a poner en pendiente un job fallado o interrumpido."""
        self._conn.execute(
            """UPDATE jobs SET state='pending', started_at=NULL,
               finished_at=NULL, error=NULL, lines_done=0 WHERE id=?""",
            (job_id,),
        )

    def update_progress(self, job_id: int, lines_done: int) -> None:
        self._conn.execute(
            "UPDATE jobs SET lines_done=? WHERE id=?", (lines_done, job_id)
        )

    def recover_stale(self) -> int:
        """Devuelve a pendiente los jobs que quedaron RUNNING tras una caída.

        Correlo al arrancar el worker. Un corte de luz a mitad de un job
        deja la fila en RUNNING para siempre si nadie la limpia.
        """
        cursor = self._conn.execute(
            """UPDATE jobs SET state='pending', started_at=NULL,
               error='interrumpido: el worker se cayó' WHERE state='running'"""
        )
        return cursor.rowcount

    # ------------------------------------------------------------- lectura

    def get(self, job_id: int) -> Job | None:
        row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _row_to_job(row) if row else None

    def list(self, state: JobState | None = None, limit: int = 50) -> list[Job]:
        if state:
            rows = self._conn.execute(
                "SELECT * FROM jobs WHERE state=? ORDER BY id DESC LIMIT ?",
                (state.value, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_job(row) for row in rows]

    def pending(self) -> Iterator[Job]:
        while True:
            job = self.claim_next()
            if job is None:
                return
            yield job

    def counts(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT state, COUNT(*) AS n FROM jobs GROUP BY state"
        ).fetchall()
        return {row["state"]: row["n"] for row in rows}


def _row_to_job(row: sqlite3.Row) -> Job:
    return Job(
        id=row["id"],
        name=row["name"],
        gcode_path=row["gcode_path"],
        material=row["material"],
        state=JobState(row["state"]),
        priority=row["priority"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        lines_total=row["lines_total"],
        lines_done=row["lines_done"],
        meta=json.loads(row["meta"] or "{}"),
    )
