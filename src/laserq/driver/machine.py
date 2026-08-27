"""Control de alto nivel de la máquina: homing, parámetros, ejecución de jobs."""

from __future__ import annotations

import signal
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterable

from .connection import CMD_SOFT_RESET, CMD_STATUS, Connection
from .errors import GrblAlarm, LaserqError
from .state import MachineState, Settings, Status, parse_setting, parse_status
from .streamer import Progress, Streamer, send_and_wait

#: Parámetros que deben estar sí o sí antes de grabar. Cada uno tiene una
#: razón concreta; ver docs/parametros.md.
REQUIRED_SETTINGS: dict[int, float] = {
    # Laser mode: sincroniza la potencia con el movimiento en lugar de
    # esperar a que la máquina llegue a velocidad. Sin esto, M4 no sirve.
    32: 1,
    # Valor máximo de S. Todo el código genera potencias 0..$30.
    30: 1000,
    31: 0,
    # Homing habilitado. Es la precondición de todo lo automatizable:
    # sin origen absoluto repetible no hay cola de jobs que valga.
    22: 1,
}

SETTING_NAMES: dict[int, str] = {
    22: "homing habilitado",
    30: "S máximo",
    31: "S mínimo",
    32: "laser mode",
    100: "X pasos/mm",
    101: "Y pasos/mm",
    110: "X velocidad máxima (mm/min)",
    111: "Y velocidad máxima (mm/min)",
    120: "X aceleración (mm/s²)",
    121: "Y aceleración (mm/s²)",
    130: "X recorrido máximo (mm)",
    131: "Y recorrido máximo (mm)",
}


@dataclass
class MachineInfo:
    firmware: str | None = None
    settings: Settings | None = None


class Machine:
    """La máquina, vista desde arriba. Envuelve Connection + Streamer."""

    def __init__(self, connection: Connection):
        self.conn = connection
        self.info = MachineInfo()
        self._streamer: Streamer | None = None

    # ------------------------------------------------------------ consultas

    def status(self, timeout: float = 2.0) -> Status:
        """Pide un status report y devuelve el primero que llegue."""
        self.conn.write_realtime(CMD_STATUS)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for line in self.conn.read_lines():
                status = parse_status(line)
                if status is not None:
                    return status
            time.sleep(0.01)
        raise TimeoutError("la máquina no respondió al pedido de status")

    def read_settings(self) -> Settings:
        """Lee todos los `$N=v` con el comando `$$`."""
        lines = send_and_wait(self.conn, "$$", collect=True)
        values: dict[int, float] = {}
        for line in lines:
            parsed = parse_setting(line)
            if parsed:
                values[parsed[0]] = parsed[1]
        settings = Settings(values)
        self.info.settings = settings
        return settings

    def check_settings(
        self, expected: dict[int, float] | None = None
    ) -> dict[int, tuple[float | None, float]]:
        """Devuelve los parámetros que no coinciden con lo esperado."""
        settings = self.info.settings or self.read_settings()
        return settings.diff(expected or REQUIRED_SETTINGS)

    def apply_settings(self, values: dict[int, float]) -> None:
        """Escribe parámetros en la EEPROM. Requiere la máquina en Idle.

        Ojo: la EEPROM tiene un número finito de ciclos de escritura. Esto
        se corre una vez al configurar, no en cada job.
        """
        for number, value in sorted(values.items()):
            text = f"{value:g}"
            send_and_wait(self.conn, f"${number}={text}")

    # -------------------------------------------------------------- acciones

    def unlock(self) -> None:
        """Saca la máquina del estado ALARM (`$X`).

        Después de un `$X` la posición no es confiable: GRBL te deja mover
        pero no sabe dónde está. Salvo que sepas exactamente lo que hacés,
        lo correcto después de una alarma es homing, no unlock.
        """
        send_and_wait(self.conn, "$X")

    def home(self, timeout: float = 60.0) -> None:
        """Ejecuta el ciclo de homing (`$H`) y espera a que termine."""
        try:
            send_and_wait(self.conn, "$H", timeout=timeout)
        except GrblAlarm as alarm:
            raise LaserqError(
                f"falló el homing ({alarm}). Revisá los finales de carrera "
                f"y que nada obstruya el recorrido del cabezal."
            ) from alarm

    def soft_reset(self) -> None:
        self.conn.write_realtime(CMD_SOFT_RESET)
        time.sleep(1.0)
        list(self.conn.read_lines())  # descartar el banner

    def laser_off(self) -> None:
        """Apaga el láser sin mover nada. Es el primer reflejo ante una duda."""
        self.conn.write_line("M5 S0")

    # ------------------------------------------------------------------ job

    def run(
        self,
        lines: Iterable[str],
        *,
        total: int | None = None,
        require_idle: bool = True,
        **streamer_kwargs,
    ) -> Progress:
        """Ejecuta un programa completo, con parada de emergencia por Ctrl-C."""
        if require_idle:
            status = self.status()
            if status.state.is_blocked:
                raise LaserqError(
                    f"la máquina está en {status.state.value} y no puede arrancar. "
                    f"Hacé homing o revisá la causa antes de reintentar."
                )

        self._streamer = Streamer(self.conn, **streamer_kwargs)
        with self._panic_handler():
            return self._streamer.run(lines, total=total)

    @contextmanager
    def _panic_handler(self):
        """Ctrl-C durante un job hace feed hold + reset, no un stack trace.

        Un KeyboardInterrupt sin manejar deja el proceso muerto con el láser
        encendido y la máquina moviéndose hasta vaciar su buffer. Eso no es
        aceptable con 20W a 450nm sobre madera.
        """

        def handler(signum, frame):  # noqa: ARG001
            if self._streamer is not None:
                self._streamer.abort()

        previous = signal.getsignal(signal.SIGINT)
        try:
            signal.signal(signal.SIGINT, handler)
        except ValueError:  # no estamos en el hilo principal
            previous = None
        try:
            yield
        finally:
            if previous is not None:
                signal.signal(signal.SIGINT, previous)

    def emergency_stop(self) -> None:
        """Parada de emergencia por software.

        No reemplaza un corte de alimentación físico. Si vas a dejar la
        máquina corriendo con gente alrededor, poné un interruptor en serie
        con la fuente y ponelo al alcance de la mano.
        """
        if self._streamer is not None:
            self._streamer.abort()
        else:
            self.conn.write_realtime(CMD_SOFT_RESET)


def wait_until_idle(machine: Machine, timeout: float = 600.0) -> Status:
    """Bloquea hasta que la máquina vuelva a Idle.

    Hace falta porque el último `ok` de un job significa "recibí la línea",
    no "terminé de moverme": GRBL todavía tiene el planificador lleno.
    Si apagás el aire o sacás la pieza al recibir el último ok, te comés
    los últimos segundos del grabado.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = machine.status()
        if status.state == MachineState.IDLE:
            return status
        if status.state.is_blocked:
            raise LaserqError(f"la máquina quedó en {status.state.value} esperando Idle")
        time.sleep(0.2)
    raise TimeoutError("la máquina no volvió a Idle")
