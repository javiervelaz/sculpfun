"""Tests de corte: kerf, orden y multipasada.

Los tres se ven recién en la pieza terminada, y los tres se ven tarde: un
kerf con el signo cambiado no falla, encastra flojo. Por eso el signo tiene
test propio.
"""

from __future__ import annotations

import pytest

from laserq.gcode.builder import GcodeOptions, GcodeProgram
from laserq.gcode.cut import (
    HOLE,
    PART,
    Contour,
    CutOptions,
    compensate,
    compensated_rect,
    cut_contours,
    offset_polygon,
    order_contours,
    outline,
    signed_area,
    slot,
)
from laserq.profiles import MaterialProfile


def _ancho(points):
    xs = [x for x, _ in points]
    return max(xs) - min(xs)


# ------------------------------------------------------------------ kerf


def test_una_ranura_se_dibuja_mas_angosta_que_su_medida_final():
    """El láser se come kerf/2 de cada lado: si dibujás 6.0 te queda 6.2."""
    puntos = compensated_rect(0, 0, 6.0, 30.0, kerf=0.2, role=HOLE)

    assert _ancho(puntos) == pytest.approx(5.8)


def test_una_pieza_se_dibuja_mas_ancha_que_su_medida_final():
    puntos = compensated_rect(0, 0, 6.0, 30.0, kerf=0.2, role=PART)

    assert _ancho(puntos) == pytest.approx(6.2)


def test_la_compensacion_no_mueve_el_centro():
    ranura = compensated_rect(10, 0, 6.0, 30.0, kerf=0.2, role=HOLE)
    pieza = compensated_rect(10, 0, 6.0, 30.0, kerf=0.2, role=PART)

    centro = lambda p: (min(x for x, _ in p) + max(x for x, _ in p)) / 2  # noqa: E731
    assert centro(ranura) == pytest.approx(13.0)
    assert centro(pieza) == pytest.approx(13.0)


def test_sin_kerf_el_camino_es_la_medida():
    assert _ancho(slot(0, 0, 6.0, 30.0).points) == pytest.approx(6.0)
    assert _ancho(outline(0, 0, 6.0, 30.0).points) == pytest.approx(6.0)


def test_un_kerf_que_se_come_la_ranura_falla_claro():
    with pytest.raises(ValueError, match="se come la ranura"):
        compensated_rect(0, 0, 0.3, 30.0, kerf=0.4, role=HOLE)


def test_un_rol_invalido_falla_al_construir():
    with pytest.raises(ValueError, match="rol invalido"):
        Contour([(0, 0), (1, 1)], role="agujerito")


# ----------------------------------------------------------------- orden


def test_los_interiores_se_cortan_antes_que_el_contorno():
    """Al revés, la pieza se suelta y las ranuras que faltan salen corridas."""
    perimetro = outline(0, 0, 100, 50)
    ranura_a = slot(10, 10, 6, 20)
    ranura_b = slot(30, 10, 6, 20)

    ordenados = order_contours([perimetro, ranura_a, ranura_b])

    assert [c.role for c in ordenados] == [HOLE, HOLE, PART]
    assert ordenados[-1] is perimetro


def test_el_orden_dentro_de_cada_grupo_se_respeta():
    a, b = slot(0, 0, 6, 20), slot(20, 0, 6, 20)

    assert order_contours([a, b]) == [a, b]


# ------------------------------------------------------------ multipasada


def _g1(program) -> int:
    return sum(1 for line in program if line.startswith("G1"))


def test_cada_contorno_se_repite_las_pasadas_pedidas():
    program = GcodeProgram(GcodeOptions())
    linea = Contour([(0, 0), (0, 12)], role=PART, closed=False)

    cut_contours(program, [linea], CutOptions(speed=250, power=1000, passes=4))

    assert _g1(program) == 4  # una línea abierta = un G1 por pasada


def test_una_pasada_es_el_default():
    program = GcodeProgram(GcodeOptions())
    linea = Contour([(0, 0), (0, 12)], role=PART, closed=False)

    cut_contours(program, [linea], CutOptions())

    assert _g1(program) == 1


def test_un_contorno_puede_pedir_sus_propias_pasadas():
    """Lo necesita la placa de test: cada fila lleva una cantidad distinta."""
    program = GcodeProgram(GcodeOptions())
    contornos = [
        Contour([(0, 0), (0, 12)], role=PART, closed=False, passes=2),
        Contour([(5, 0), (5, 12)], role=PART, closed=False, passes=5),
    ]

    cut_contours(program, contornos, CutOptions(passes=1))

    assert _g1(program) == 7


def test_el_perfil_del_material_trae_pasadas_y_kerf():
    """`passes` estaba en el YAML y no llegaba al G-code. Acá llega."""
    perfil = MaterialProfile(
        name="multilaminado_6mm_corte", operation="cut",
        speed=250, power=1000, passes=4, kerf_mm=0.18,
    )

    options = CutOptions.from_profile(perfil)

    assert (options.speed, options.power, options.passes) == (250, 1000, 4)
    assert options.kerf_mm == pytest.approx(0.18)


# --------------------------------------------------- offset de polígonos


def test_el_offset_general_coincide_con_el_de_rectangulos():
    """Dos caminos al mismo número: si divergen, uno de los dos miente."""
    rect = [(0, 0), (6, 0), (6, 30), (0, 30)]

    for role in (HOLE, PART):
        general = compensate(rect, kerf=0.25, role=role)
        especifico = compensated_rect(0, 0, 6, 30, kerf=0.25, role=role)
        for (ax, ay), (bx, by) in zip(general, especifico):
            assert ax == pytest.approx(bx)
            assert ay == pytest.approx(by)


def test_el_offset_no_depende_del_sentido_de_giro():
    """Un contorno dibujado al revés tiene que compensar para el mismo lado."""
    horario = [(0, 30), (6, 30), (6, 0), (0, 0)]
    antihorario = [(0, 0), (6, 0), (6, 30), (0, 30)]
    assert signed_area(horario) < 0 < signed_area(antihorario)

    def ancho(points):
        xs = [x for x, _ in points]
        return max(xs) - min(xs)

    assert ancho(offset_polygon(horario, 0.125)) == pytest.approx(6.25)
    assert ancho(offset_polygon(antihorario, 0.125)) == pytest.approx(6.25)


def test_con_kerf_cero_el_contorno_no_se_toca():
    rect = [(0, 0), (6, 0), (6, 30), (0, 30)]
    assert compensate(rect, kerf=0.0, role=PART) == rect


def test_un_contorno_de_dos_puntos_no_se_puede_desplazar():
    with pytest.raises(ValueError, match="al menos 3 puntos"):
        offset_polygon([(0, 0), (1, 1)], 0.1)
