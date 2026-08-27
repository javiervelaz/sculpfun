"""Tests del protocolo de streaming.

Esta es la parte del sistema donde un error no se ve: el job sale igual,
solo que peor. Por eso conviene tenerla cubierta antes de confiar en ella.
"""

from __future__ import annotations

import pytest

from laserq.driver.connection import CMD_FEED_HOLD, CMD_SOFT_RESET, FakeConnection
from laserq.driver.errors import GrblError
from laserq.driver.streamer import RX_USABLE, Streamer, strip_comments


def test_strip_comments():
    assert strip_comments("G1 X10 ; mover") == "G1 X10"
    assert strip_comments("G1 (comentario) X10") == "G1 X10"
    # colapsa espacios: son bytes del buffer de 128 que no rinden nada
    assert strip_comments("G1   X10    Y20") == "G1 X10 Y20"
    assert strip_comments("  ; solo comentario") == ""
    assert strip_comments("G0X0Y0") == "G0X0Y0"


def test_envia_todas_las_lineas_y_espera_los_acks():
    conn = FakeConnection()
    conn.open()
    program = [f"G1X{i}" for i in range(50)]

    progress = Streamer(conn).run(program)

    assert conn.sent == program
    assert progress.sent == 50
    assert progress.acked == 50
    assert progress.fraction == 1.0


def test_saltea_lineas_vacias_y_comentarios():
    conn = FakeConnection()
    conn.open()

    Streamer(conn).run(["G21", "", "; nada", "   ", "G90"])

    assert conn.sent == ["G21", "G90"]


class BufferTrackingConnection(FakeConnection):
    """Conexión que registra cuántos bytes había en vuelo en cada escritura.

    Sirve para verificar la invariante central del protocolo: nunca superar
    el buffer de recepción de GRBL, pero tampoco dejarlo vacío al pedo.
    """

    def __init__(self, hold_acks: int = 0):
        super().__init__()
        self.hold_acks = hold_acks
        self.in_flight = 0
        self.peak_in_flight = 0
        self.held: list[str] = []

    def write_line(self, line: str) -> int:
        size = len(line.strip()) + 1
        self.in_flight += size
        self.peak_in_flight = max(self.peak_in_flight, self.in_flight)
        self.sent.append(line.strip())
        self.held.append("ok")
        # Simula la latencia: GRBL no responde de inmediato, así que
        # retenemos los primeros acks para que el buffer se llene de verdad.
        if len(self.held) > self.hold_acks:
            self._pending.append(self.held.pop(0))
            self.in_flight -= size
        return size

    def read_lines(self):
        while self._pending:
            yield self._pending.pop(0)
        # Al final, liberar lo retenido para que el job pueda terminar.
        if not self._pending and self.held:
            self._pending.extend(self.held)
            self.held.clear()
            self.in_flight = 0


def test_nunca_supera_el_buffer_de_grbl():
    conn = BufferTrackingConnection(hold_acks=1000)
    conn.open()
    program = [f"G1X{i}.123Y{i}.456F3000S800" for i in range(300)]

    Streamer(conn).run(program)

    assert conn.peak_in_flight <= RX_USABLE
    assert conn.sent == program


def test_mantiene_el_buffer_bien_lleno():
    """Si el pico de ocupación fuera bajo, estaríamos matando el lookahead."""
    conn = BufferTrackingConnection(hold_acks=1000)
    conn.open()
    program = [f"G1X{i}" for i in range(300)]  # líneas cortas: entran muchas

    Streamer(conn).run(program)

    # Con líneas de ~7 bytes tienen que entrar más de 10 a la vez.
    assert conn.peak_in_flight > RX_USABLE * 0.8


def test_un_error_de_grbl_identifica_la_linea_culpable():
    conn = FakeConnection(error_on={3: 20})  # la cuarta línea da error:20
    conn.open()
    program = ["G21", "G90", "M4S0", "G1X10", "G1X20"]

    with pytest.raises(GrblError) as info:
        Streamer(conn).run(program)

    assert info.value.code == 20
    assert "G1X10" in str(info.value)
    assert info.value.line_no == 4


def test_abort_hace_feed_hold_antes_del_reset():
    """El orden importa: un soft reset en movimiento pierde la posición."""
    conn = FakeConnection()
    conn.open()
    streamer = Streamer(conn)

    streamer.abort()

    assert conn.realtime[0] == CMD_FEED_HOLD
    assert CMD_SOFT_RESET in conn.realtime
    assert conn.realtime.index(CMD_FEED_HOLD) < conn.realtime.index(CMD_SOFT_RESET)
