"""Streaming de G-code hacia GRBL con control de flujo por conteo de caracteres.

Por qué esto y no el protocolo simple
-------------------------------------
El método que aparece en el 90% de los tutoriales es: mandar una línea,
esperar el `ok`, mandar la siguiente. Funciona, pero deja la máquina sin
trabajo encolado entre línea y línea. GRBL tiene un planificador que mira
hacia adelante para decidir cuánto puede acelerar: si solo conoce el
movimiento actual, tiene que frenar hasta cero al final de cada segmento
por si el próximo cambia de dirección.

En grabado raster eso es fatal. Una imagen son miles de segmentos cortos,
y a 25.000 mm/min el cabezal termina moviéndose a tirones. Con el láser en
modo dinámico (M4) la potencia sigue a la velocidad real, así que cada
frenada queda **grabada en la pieza** como una banda más clara. Ese es el
patrón de rayas verticales que la gente atribuye al material o al foco.

La solución es mantener el buffer de recepción de GRBL siempre lleno.
Como GRBL no nos dice cuánto le queda libre, llevamos la cuenta nosotros:
guardamos el largo en bytes de cada línea enviada y solo mandamos una
nueva si la suma de las pendientes más la nueva entra en el buffer. Cada
`ok` o `error` que vuelve corresponde, **en orden**, a la línea más vieja
sin responder, así que la sacamos de la cola y liberamos su espacio.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Iterable, Sequence

from .connection import (
    CMD_FEED_HOLD,
    CMD_RESUME,
    CMD_SOFT_RESET,
    CMD_STATUS,
    Connection,
)
from .errors import GrblAlarm, GrblError, JobAborted
from .state import Status, parse_status

#: Tamaño del buffer de recepción de GRBL 1.1, en bytes. Dejamos uno de
#: margen porque el firmware reserva un byte para el terminador.
RX_BUFFER_SIZE = 128
RX_USABLE = RX_BUFFER_SIZE - 1


@dataclass
class Progress:
    """Estado de avance de un job, para mostrar en pantalla."""

    sent: int = 0
    acked: int = 0
    total: int | None = None
    started_at: float = field(default_factory=time.monotonic)
    last_status: Status | None = None

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started_at

    @property
    def fraction(self) -> float | None:
        if not self.total:
            return None
        return self.acked / self.total

    @property
    def eta(self) -> float | None:
        """Segundos restantes estimados a partir del ritmo promedio de acks."""
        frac = self.fraction
        if not frac or frac <= 0.0:
            return None
        return self.elapsed * (1.0 - frac) / frac


StatusCallback = Callable[[Status], None]
ProgressCallback = Callable[[Progress], None]


def strip_comments(line: str) -> str:
    """Saca comentarios `;...` y `(...)` y espacios sobrantes.

    Vale la pena hacerlo del lado nuestro: cada byte de comentario que
    mandamos ocupa lugar en el buffer de 128 bytes y desperdicia lookahead.
    """
    if "(" in line:
        out, depth = [], 0
        for char in line:
            if char == "(":
                depth += 1
            elif char == ")":
                depth = max(0, depth - 1)
            elif depth == 0:
                out.append(char)
        line = "".join(out)
    line = line.split(";", 1)[0]
    # Colapsar espacios internos: GRBL los ignora, pero cada uno ocupa lugar
    # en el buffer de 128 bytes y son bytes que le sacás al lookahead.
    return " ".join(line.split())


class Streamer:
    """Envía un programa de G-code a GRBL manteniendo el buffer lleno."""

    def __init__(
        self,
        connection: Connection,
        *,
        status_interval: float = 0.2,
        on_status: StatusCallback | None = None,
        on_progress: ProgressCallback | None = None,
        progress_interval: float = 0.25,
    ):
        self.conn = connection
        self.status_interval = status_interval
        self.on_status = on_status
        self.on_progress = on_progress
        self.progress_interval = progress_interval

        self._pending: deque[tuple[int, str, int]] = deque()  # (bytes, línea, nro)
        self._aborted = False
        self.progress = Progress()

    # ------------------------------------------------------------- control

    def abort(self) -> None:
        """Corta el job: feed hold inmediato y después soft reset.

        El orden importa. El feed hold desacelera de forma controlada y
        apaga el láser; el soft reset solo, con la máquina a máxima
        velocidad, hace perder pasos y por lo tanto la posición.
        """
        self._aborted = True
        try:
            self.conn.write_realtime(CMD_FEED_HOLD)
            time.sleep(0.3)
            self.conn.write_realtime(CMD_SOFT_RESET)
        except Exception:  # el puerto puede haberse caído; no ocultar el abort
            pass

    def pause(self) -> None:
        self.conn.write_realtime(CMD_FEED_HOLD)

    def resume(self) -> None:
        self.conn.write_realtime(CMD_RESUME)

    # ------------------------------------------------------------ streaming

    def run(self, lines: Iterable[str], *, total: int | None = None) -> Progress:
        """Envía todas las líneas y vuelve cuando GRBL confirmó la última.

        Levanta GrblError si una línea fue rechazada, GrblAlarm si la
        máquina entró en alarma, o JobAborted si se llamó a abort().

        **Ante cualquier falla frena la máquina antes de propagar el error.**
        Un `error:N` a mitad de job no detiene nada por sí solo: GRBL sigue
        ejecutando los ~128 bytes que ya tenía en el buffer, con el láser
        encendido, mientras el proceso de Python se muere por la excepción.
        Frenar acá y no en cada llamador es lo único que garantiza que
        `laserq run` y el worker se comporten igual.
        """
        try:
            return self._stream(lines, total=total)
        except JobAborted:
            raise  # abort() ya frenó la máquina
        except BaseException:
            self.abort()
            raise

    def _stream(self, lines: Iterable[str], *, total: int | None = None) -> Progress:
        if total is None and isinstance(lines, Sequence):
            total = len(lines)

        self._pending.clear()
        self._aborted = False
        self.progress = Progress(total=total)

        source = iter(lines)
        next_line: str | None = None
        exhausted = False
        last_status_poll = 0.0
        last_progress = 0.0
        line_no = 0

        while True:
            if self._aborted:
                raise JobAborted("job cortado por el operador")

            # 1. Conseguir la próxima línea con contenido real.
            if next_line is None and not exhausted:
                while True:
                    try:
                        candidate = strip_comments(next(source))
                    except StopIteration:
                        exhausted = True
                        break
                    if candidate:
                        next_line = candidate
                        line_no += 1
                        break

            # 2. Enviarla si entra en el buffer.
            if next_line is not None:
                size = len(next_line) + 1  # +1 por el \n
                in_flight = sum(item[0] for item in self._pending)
                if in_flight + size <= RX_USABLE:
                    self.conn.write_line(next_line)
                    self._pending.append((size, next_line, line_no))
                    self.progress.sent += 1
                    next_line = None
                    continue  # intentar meter otra línea antes de leer

            # 3. Consumir respuestas.
            self._drain_responses()

            # 4. Terminamos cuando no queda nada por mandar ni por confirmar.
            if exhausted and next_line is None and not self._pending:
                break

            # 5. Pedir status cada tanto.
            now = time.monotonic()
            if now - last_status_poll >= self.status_interval:
                self.conn.write_realtime(CMD_STATUS)
                last_status_poll = now

            if self.on_progress and now - last_progress >= self.progress_interval:
                self.on_progress(self.progress)
                last_progress = now

            time.sleep(0.001)  # no quemar un core entero girando en vacío

        if self.on_progress:
            self.on_progress(self.progress)
        return self.progress

    def _drain_responses(self) -> None:
        for line in self.conn.read_lines():
            if line.startswith("<"):
                status = parse_status(line)
                if status is not None:
                    self.progress.last_status = status
                    if self.on_status:
                        self.on_status(status)
                continue

            if line.startswith("ALARM:"):
                try:
                    code = int(line.split(":", 1)[1])
                except (IndexError, ValueError):
                    code = 0
                raise GrblAlarm(code)

            if line == "ok":
                if self._pending:
                    self._pending.popleft()
                self.progress.acked += 1
                continue

            if line.startswith("error:"):
                try:
                    code = int(line.split(":", 1)[1])
                except (IndexError, ValueError):
                    code = 0
                sent_line, sent_no = "", None
                if self._pending:
                    _, sent_line, sent_no = self._pending.popleft()
                self.progress.acked += 1
                raise GrblError(code, sent_line, sent_no)

            # [MSG:...], banner de arranque, respuestas a $$, etc.: se ignoran acá.


def send_and_wait(
    connection: Connection,
    command: str,
    *,
    timeout: float = 30.0,
    collect: bool = False,
) -> list[str]:
    """Manda un comando suelto y espera su `ok`. Para `$H`, `$$`, `$X`.

    Con collect=True devuelve todas las líneas recibidas antes del `ok`,
    que es como se leen las respuestas de `$$` y `$#`.
    """
    connection.write_line(command)
    deadline = time.monotonic() + timeout
    collected: list[str] = []

    while time.monotonic() < deadline:
        for line in connection.read_lines():
            if line == "ok":
                return collected
            if line.startswith("error:"):
                code = int(line.split(":", 1)[1]) if ":" in line else 0
                raise GrblError(code, command)
            if line.startswith("ALARM:"):
                code = int(line.split(":", 1)[1]) if ":" in line else 0
                raise GrblAlarm(code)
            if collect and not line.startswith("<"):
                collected.append(line)
        time.sleep(0.01)

    raise TimeoutError(f"sin respuesta a {command!r} en {timeout:.0f}s")
