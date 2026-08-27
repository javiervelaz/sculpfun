"""Tests de la cola de jobs."""

import pytest

from laserq.jobs import Job, JobQueue, JobState


@pytest.fixture
def queue(tmp_path):
    q = JobQueue(tmp_path / "test.db")
    yield q
    q.close()


def test_encolar_y_reclamar(queue):
    queue.add(Job(name="uno", gcode_path="/tmp/a.gcode"))
    queue.add(Job(name="dos", gcode_path="/tmp/b.gcode"))

    primero = queue.claim_next()
    assert primero.name == "uno"
    assert primero.state == JobState.RUNNING


def test_la_prioridad_manda(queue):
    queue.add(Job(name="normal", gcode_path="/a", priority=0))
    queue.add(Job(name="urgente", gcode_path="/b", priority=10))
    assert queue.claim_next().name == "urgente"


def test_no_se_reclama_dos_veces(queue):
    """La atomicidad importa el día que haya dos workers."""
    queue.add(Job(name="unico", gcode_path="/a"))
    assert queue.claim_next() is not None
    assert queue.claim_next() is None


def test_cola_vacia(queue):
    assert queue.claim_next() is None


def test_finish_marca_done(queue):
    job = queue.add(Job(name="x", gcode_path="/a"))
    queue.claim_next()
    queue.finish(job.id, lines_done=100)
    assert queue.get(job.id).state == JobState.DONE


def test_finish_con_error_marca_failed(queue):
    job = queue.add(Job(name="x", gcode_path="/a"))
    queue.claim_next()
    queue.finish(job.id, error="ALARM:1")
    recuperado = queue.get(job.id)
    assert recuperado.state == JobState.FAILED
    assert "ALARM" in recuperado.error


def test_recover_stale_devuelve_los_interrumpidos(queue):
    """Un corte de luz deja jobs en RUNNING para siempre si nadie limpia."""
    queue.add(Job(name="a", gcode_path="/a"))
    queue.add(Job(name="b", gcode_path="/b"))
    queue.claim_next()

    assert queue.recover_stale() == 1
    assert queue.counts()["pending"] == 2


def test_batch_en_una_transaccion(queue):
    jobs = [Job(name=f"pieza-{i}", gcode_path=f"/tmp/{i}.gcode") for i in range(200)]
    queue.add_batch(jobs)
    assert queue.counts()["pending"] == 200
    assert all(j.id is not None for j in jobs)
