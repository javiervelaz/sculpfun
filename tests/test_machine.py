"""Tests de Machine: jog y origen de trabajo.

`set_origin` es la pieza que le faltaba al flujo real: el material no
siempre está apoyado contra el (0,0) absoluto que deja el homing (esa
esquina puede tener un final de carrera en el medio). Sin esto, todo
G-code generado por el proyecto asume que sí lo está, y graba donde no
corresponde si no lo está.
"""

from __future__ import annotations

from laserq.driver.connection import FakeConnection
from laserq.driver.machine import Machine


def test_jog_absoluto_manda_g90():
    conn = FakeConnection()
    conn.open()
    machine = Machine(conn)

    machine.jog(50, 30, feed=1200)

    assert conn.sent == ["G90 G0 X50 Y30 F1200"]


def test_jog_relativo_manda_g91_y_restaura_g90():
    conn = FakeConnection()
    conn.open()
    machine = Machine(conn)

    machine.jog(10, -5, relative=True)

    assert conn.sent == ["G91 G0 X10 Y-5 F1500", "G90"]


def test_jog_sin_ejes_no_manda_nada():
    conn = FakeConnection()
    conn.open()
    machine = Machine(conn)

    machine.jog()

    assert conn.sent == []


def test_jog_un_solo_eje():
    conn = FakeConnection()
    conn.open()
    machine = Machine(conn)

    machine.jog(x=25)

    assert conn.sent == ["G90 G0 X25 F1500"]


def test_set_origin_manda_g92_en_cero():
    conn = FakeConnection()
    conn.open()
    machine = Machine(conn)

    machine.set_origin()

    assert conn.sent == ["G92 X0 Y0"]


def test_clear_origin_manda_g92_1():
    conn = FakeConnection()
    conn.open()
    machine = Machine(conn)

    machine.clear_origin()

    assert conn.sent == ["G92.1"]
