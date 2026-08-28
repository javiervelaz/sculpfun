"""Tests del worker: la única capa que maneja la máquina sin nadie mirando.

El homing es lo que más importa acá. Con el rotativo montado, Y deja de ser
la mesa y pasa a ser el rodillo: un `$H` sale a buscar un final de carrera
que en ese eje no existe y la pieza gira hasta que alguien corta. Y en mesa
plana, homear después de `set-origin` manda el cabezal a la esquina absoluta
y deja el offset de G92 calculado para una posición que ya no es la actual.

Por eso "cuántas veces homeó" es una aserción de primera clase y no un
detalle de implementación.
"""

from __future__ import annotations

import pytest

from laserq.driver.connection import FakeConnection
from laserq.driver.machine import Machine
from laserq.jobs import Job, JobQueue, JobState, Worker

#: Programa mínimo pero real. El índice de cada línea importa en el test de
#: fallas, así que no lo cambies sin recontar.
#: 0:"G21" 1:"G90" 2:"M4 S0" 3:"G1X10Y10F3000S500" 4:"M5 S0" 5:"M2"
GCODE = "G21\nG90\nM4 S0\nG1X10Y10F3000S500\nM5 S0\nM2\n"


def _entorno(tmp_path, piezas: int = 2, conn: FakeConnection | None = None, **kwargs):
    conn = conn or FakeConnection()
    conn.open()
    machine = Machine(conn)
    queue = JobQueue(tmp_path / "cola.db")
    for index in range(piezas):
        ruta = tmp_path / f"pieza{index}.gcode"
        ruta.write_text(GCODE, encoding="ascii")
        queue.add(Job(name=f"pieza{index}", gcode_path=str(ruta)))
    worker = Worker(machine, queue, confirm_each=False, **kwargs)
    return conn, queue, worker


def _homings(conn: FakeConnection) -> int:
    return conn.sent.count("$H")


def test_por_defecto_homea_una_sola_vez_por_tirada(tmp_path):
    """50 termos no necesitan 50 ciclos de homing."""
    conn, _, worker = _entorno(tmp_path, piezas=3)

    stats = worker.run_forever(max_jobs=3)

    assert stats.completed == 3
    assert _homings(conn) == 1


def test_home_each_homea_antes_de_cada_job(tmp_path):
    conn, _, worker = _entorno(tmp_path, piezas=3, home_policy="each")

    worker.run_forever(max_jobs=3)

    assert _homings(conn) == 3


def test_no_home_no_homea_nunca(tmp_path):
    """El modo rotativo: `$H` en Y no tiene final de carrera que buscar."""
    conn, _, worker = _entorno(tmp_path, piezas=2, home_policy="never")

    stats = worker.run_forever(max_jobs=2)

    assert stats.completed == 2
    assert _homings(conn) == 0


def test_una_politica_de_homing_invalida_falla_al_construir(tmp_path):
    conn = FakeConnection()
    conn.open()
    queue = JobQueue(tmp_path / "cola.db")

    with pytest.raises(ValueError, match="home_policy"):
        Worker(Machine(conn), queue, home_policy="a_veces")


def test_un_job_fallado_obliga_a_rehomear(tmp_path):
    """emergency_stop() hace soft reset: después de eso la posición no vale."""
    # sent[0] es el "$H"; el programa arranca en sent[1], así que la línea
    # de grabado (índice 3 del archivo) cae en sent[4].
    conn = FakeConnection(error_on={4: 20})
    conn, _, worker = _entorno(tmp_path, piezas=2, conn=conn)

    stats = worker.run_forever(max_jobs=2)

    assert stats.failed == 1
    assert stats.completed == 1
    assert _homings(conn) == 2  # una por job: el fallado invalidó la posición


def test_un_job_que_se_sale_del_area_se_rechaza_sin_encender_el_laser(tmp_path):
    conn = FakeConnection()
    conn.open()
    machine = Machine(conn)
    queue = JobQueue(tmp_path / "cola.db")
    ruta = tmp_path / "gigante.gcode"
    ruta.write_text("G21\nG90\nG1X9000Y10F3000S500\nM2\n", encoding="ascii")
    queue.add(Job(name="gigante", gcode_path=str(ruta)))
    worker = Worker(machine, queue, confirm_each=False, work_area=(410.0, 400.0))

    stats = worker.run_forever(max_jobs=1)

    assert stats.failed == 1
    assert conn.sent == []  # ni siquiera se conectó a homear
    assert queue.list(JobState.FAILED)[0].error.startswith("el job se sale")


def test_un_archivo_que_no_existe_falla_sin_tocar_la_maquina(tmp_path):
    conn = FakeConnection()
    conn.open()
    queue = JobQueue(tmp_path / "cola.db")
    queue.add(Job(name="fantasma", gcode_path=str(tmp_path / "no-esta.gcode")))
    worker = Worker(Machine(conn), queue, confirm_each=False)

    stats = worker.run_forever(max_jobs=1)

    assert stats.failed == 1
    assert conn.sent == []
