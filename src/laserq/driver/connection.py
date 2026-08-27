"""Transporte serie hacia GRBL.

Responsabilidad única: bytes para adentro, bytes para afuera. No sabe nada
de G-code ni de jobs. Todo lo que sube es texto por líneas.

Detalle importante: los comandos realtime (`?`, `!`, `~`, 0x18) se escriben
como un solo byte crudo y **no llevan salto de línea**. GRBL los intercepta
en la interrupción de recepción, no pasan por el buffer de líneas, y por
eso no cuentan para el control de flujo por conteo de caracteres.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterator

from .errors import ConnectionError_

# Comandos realtime (byte único, sin newline)
CMD_STATUS = b"?"
CMD_FEED_HOLD = b"!"
CMD_RESUME = b"~"
CMD_SOFT_RESET = b"\x18"
CMD_JOG_CANCEL = b"\x85"
CMD_SAFETY_DOOR = b"\x84"

# Overrides de potencia del láser (útiles para ajustar en caliente sin recortar el job)
CMD_SPINDLE_OVR_RESET = b"\x99"
CMD_SPINDLE_OVR_PLUS_10 = b"\x9a"
CMD_SPINDLE_OVR_MINUS_10 = b"\x9b"


@dataclass
class ConnectionConfig:
    port: str
    baudrate: int = 115200
    #: Segundos de espera tras abrir el puerto. El reset por DTR reinicia el
    #: micro y GRBL tarda en mandar su banner; si escribís antes, se pierde.
    wake_delay: float = 2.0
    read_timeout: float = 0.0  # 0 = no bloqueante


class Connection:
    """Envoltura fina sobre pyserial con lectura por líneas no bloqueante."""

    def __init__(self, config: ConnectionConfig):
        self.config = config
        self._serial = None
        self._buffer = bytearray()
        self.banner: str | None = None

    # ---------------------------------------------------------------- ciclo

    def open(self) -> None:
        try:
            import serial  # import diferido: la librería se puede usar sin hardware
        except ImportError as exc:  # pragma: no cover
            raise ConnectionError_(
                "pyserial no está instalado. Instalalo con: pip install pyserial"
            ) from exc

        try:
            self._serial = serial.Serial(
                self.config.port,
                self.config.baudrate,
                timeout=self.config.read_timeout,
                write_timeout=2.0,
            )
        except Exception as exc:
            raise ConnectionError_(f"no se pudo abrir {self.config.port}: {exc}") from exc

        # Esperar el reinicio del microcontrolador y descartar el banner.
        time.sleep(self.config.wake_delay)
        self._serial.reset_input_buffer()
        self._serial.reset_output_buffer()

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            finally:
                self._serial = None

    def __enter__(self) -> "Connection":
        self.open()
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    @property
    def is_open(self) -> bool:
        return self._serial is not None and self._serial.is_open

    # ------------------------------------------------------------ escritura

    def write_line(self, line: str) -> int:
        """Envía una línea de G-code. Devuelve los bytes escritos (con el \\n)."""
        payload = (line.strip() + "\n").encode("ascii", errors="replace")
        self._require_open().write(payload)
        return len(payload)

    def write_realtime(self, command: bytes) -> None:
        """Envía un comando realtime de un byte, sin newline."""
        self._require_open().write(command)

    # -------------------------------------------------------------- lectura

    def read_lines(self) -> Iterator[str]:
        """Devuelve todas las líneas completas que haya en el buffer de entrada.

        No bloquea: si no hay nada, no devuelve nada. Los bytes de una línea
        parcial quedan guardados para la próxima llamada.
        """
        serial_port = self._require_open()
        waiting = serial_port.in_waiting
        if waiting:
            self._buffer.extend(serial_port.read(waiting))

        while b"\n" in self._buffer:
            raw, _, rest = self._buffer.partition(b"\n")
            self._buffer = bytearray(rest)
            line = raw.decode("ascii", errors="replace").strip()
            if line:
                yield line

    def _require_open(self):
        if self._serial is None or not self._serial.is_open:
            raise ConnectionError_("el puerto no está abierto")
        return self._serial


class FakeConnection(Connection):
    """Conexión simulada: responde `ok` a cada línea y `<Idle|...>` a `?`.

    Sirve para correr los tests y para hacer dry-run del generador de G-code
    sin encender el láser. Registra todo lo enviado en `sent`.
    """

    def __init__(self, error_on: dict[int, int] | None = None):
        super().__init__(ConnectionConfig(port="fake"))
        self.sent: list[str] = []
        self.realtime: list[bytes] = []
        self._pending: list[str] = []
        self._error_on = error_on or {}
        self._open = False

    def open(self) -> None:
        self._open = True
        self.banner = "Grbl 1.1f ['$' for help]"

    def close(self) -> None:
        self._open = False

    @property
    def is_open(self) -> bool:
        return self._open

    def write_line(self, line: str) -> int:
        index = len(self.sent)
        self.sent.append(line.strip())
        code = self._error_on.get(index)
        self._pending.append(f"error:{code}" if code else "ok")
        return len(line.strip()) + 1

    def write_realtime(self, command: bytes) -> None:
        self.realtime.append(command)
        if command == CMD_STATUS:
            self._pending.append("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")

    def read_lines(self) -> Iterator[str]:
        while self._pending:
            yield self._pending.pop(0)
