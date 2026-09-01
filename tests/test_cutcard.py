"""Tests de las dos placas de calibración de corte."""

from __future__ import annotations

from laserq.calibration.cutcard import (
    CutTestSpec,
    KerfCombSpec,
    build_cut_test,
    build_kerf_comb,
)
from laserq.gcode.cut import CutOptions


def test_el_peine_barre_alrededor_del_espesor_medido():
    """Un multilaminado de "6mm" mide 5.8: el barrido se centra en lo medido."""
    spec = KerfCombSpec(thickness_mm=5.8, span_mm=0.2, step_mm=0.05)

    assert spec.widths == [5.6, 5.65, 5.7, 5.75, 5.8, 5.85, 5.9, 5.95, 6.0]
    assert 5.8 in spec.widths


def test_el_peine_no_compensa_el_kerf():
    """Es la única pieza donde eso es correcto: es lo que se está midiendo.

    La primera ranura arranca en origin_x y mide exactamente su nominal, así
    que su borde derecho cae en un número redondo y verificable.
    """
    spec = KerfCombSpec(thickness_mm=5.8, span_mm=0.1, step_mm=0.05, origin=(12.0, 16.0))
    program = build_kerf_comb(spec, CutOptions(speed=250, power=1000, passes=1))

    texto = program.as_text()
    assert spec.widths[0] == 5.7
    assert "X17.7" in texto  # 12.0 + 5.7, sin compensar


def test_el_peine_corta_una_galga_de_la_misma_plancha():
    """Sin galga hay que buscar un recorte, y el recorte nunca es de esta plancha."""
    spec = KerfCombSpec(thickness_mm=6.0, span_mm=0.1, step_mm=0.05,
                        origin=(12.0, 16.0), pitch_mm=16.0, gauge_size_mm=(30.0, 18.0))
    texto = build_kerf_comb(spec, CutOptions()).as_text()

    # 5 ranuras -> la galga arranca en 12 + 5*16 + 16 = 108 y termina en 138.
    assert "X108Y16" in texto
    assert "X138" in texto

    sin_galga = KerfCombSpec(thickness_mm=6.0, span_mm=0.1, step_mm=0.05, gauge=False)
    assert spec.total_size[0] > sin_galga.total_size[0]


def test_una_galga_mas_larga_que_la_ranura_avisa():
    spec = KerfCombSpec(thickness_mm=6.0, slot_length_mm=20.0, gauge_size_mm=(30.0, 18.0))

    program = build_kerf_comb(spec, CutOptions())

    assert "no va a entrar de plano" in program.as_text()


def test_la_placa_de_corte_usa_una_velocidad_por_columna():
    spec = CutTestSpec(passes=[2, 4], speeds=[100, 300], power=1000)

    texto = build_cut_test(spec).as_text()

    assert "F100" in texto
    assert "F300" in texto


def test_cada_fila_de_la_placa_lleva_sus_pasadas():
    """Es el eje entero de la placa: si no se repite, no mide nada."""
    spec = CutTestSpec(passes=[2, 4], speeds=[100, 300], power=1000,
                       origin=(18.0, 16.0), pitch_x=14.0, pitch_y=16.0, line_mm=12.0)
    lineas = list(build_cut_test(spec))

    def cortes_hasta(x, y):
        prefijo = f"G1X{x:g}Y{y:g}"
        return sum(1 for line in lineas if line.startswith(prefijo))

    # fila 0 (y 16..28) son 2 pasadas; fila 1 (y 32..44) son 4.
    assert cortes_hasta(18, 28) == 2
    assert cortes_hasta(32, 28) == 2
    assert cortes_hasta(18, 44) == 4
    assert cortes_hasta(32, 44) == 4


def test_la_placa_declara_como_se_lee():
    """El G-code se abre dentro de un mes sin acordarse de nada."""
    texto = build_cut_test(CutTestSpec(), material="multilaminado 6mm").as_text()

    assert "dar vuelta la plancha" in texto
    assert "multilaminado 6mm" in texto
