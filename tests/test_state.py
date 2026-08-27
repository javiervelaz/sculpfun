"""Tests del parseo de status reports de GRBL."""

from laserq.driver.state import MachineState, Settings, parse_setting, parse_status


def test_status_minimo():
    s = parse_status("<Idle|MPos:0.000,0.000,0.000|FS:0,0>")
    assert s.state == MachineState.IDLE
    assert s.mpos == (0.0, 0.0, 0.0)
    assert s.feed == 0


def test_status_en_movimiento():
    s = parse_status("<Run|MPos:10.500,3.200,0.000|FS:6000,850|Ov:100,100,100>")
    assert s.state == MachineState.RUN
    assert s.spindle == 850
    assert s.overrides == (100, 100, 100)
    assert s.state.is_movable


def test_subestado_de_hold():
    s = parse_status("<Hold:0|MPos:1.000,2.000,3.000|FS:0,0>")
    assert s.state == MachineState.HOLD
    assert s.substate == 0


def test_alarma_esta_bloqueada():
    s = parse_status("<Alarm|MPos:0.000,0.000,0.000|FS:0,0>")
    assert s.state.is_blocked
    assert not s.state.is_movable


def test_posicion_de_trabajo_desde_wco():
    s = parse_status("<Idle|MPos:100.000,50.000,0.000|WCO:10.000,5.000,0.000>")
    assert s.position == (90.0, 45.0, 0.0)


def test_estado_desconocido_no_explota():
    s = parse_status("<Marciano|MPos:0.000,0.000,0.000>")
    assert s.state == MachineState.UNKNOWN


def test_linea_que_no_es_status():
    assert parse_status("ok") is None
    assert parse_status("error:20") is None


def test_parseo_de_parametros():
    assert parse_setting("$32=1.000") == (32, 1.0)
    assert parse_setting("$101=80.000") == (101, 80.0)
    assert parse_setting("ok") is None


def test_diff_de_parametros():
    settings = Settings({32: 0.0, 30: 1000.0})
    diff = settings.diff({32: 1.0, 30: 1000.0, 22: 1.0})
    assert diff[32] == (0.0, 1.0)      # está mal
    assert diff[22] == (None, 1.0)     # no está definido
    assert 30 not in diff              # está bien
