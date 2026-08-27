"""Tests de la matemática del rotativo.

Los errores acá no rompen nada: producen piezas sutilmente mal hechas que
solo se notan cuando las tenés en la mano. Por eso van con números
verificables a mano.
"""

from __future__ import annotations

import math

import pytest

from laserq.gcode.rotary import (
    ConeMapping,
    calibrate_from_wrap,
    cylinder,
    focus_band_width,
    full_turn_mm,
    steps_per_mm_for_roller,
)


def test_vuelta_completa_es_pi_por_diametro():
    assert full_turn_mm(80.0) == pytest.approx(math.pi * 80.0)


def test_el_cilindro_no_deforma_nada():
    """En un cilindro, u del diseño = Y de máquina. Identidad."""
    mapping = cylinder(diameter_mm=80.0, length_mm=100.0)
    for u, v in [(0, 0), (10, 0), (10, 50), (10, 100), (-25, 30)]:
        x, y = mapping.to_machine(u, v)
        assert x == pytest.approx(v)
        assert y == pytest.approx(u)


def test_el_conico_estira_el_extremo_angosto():
    """Misma distancia física necesita más ángulo donde el radio es menor.

    Un mate: 90 mm de diámetro abajo, 70 arriba. Un punto a 20 mm del
    centro del diseño tiene que corresponder a más rotación en el extremo
    angosto que en el ancho, para que la letra mida lo mismo en los dos.
    """
    mapping = ConeMapping(
        diameter_start=90.0, diameter_end=70.0, length=100.0, contact_diameter=80.0
    )
    _, y_ancho = mapping.to_machine(20.0, 0.0)
    _, y_angosto = mapping.to_machine(20.0, 100.0)

    assert y_angosto > y_ancho
    # Y = u * R_contacto / r(v)
    assert y_ancho == pytest.approx(20.0 * 40.0 / 45.0)
    assert y_angosto == pytest.approx(20.0 * 40.0 / 35.0)


def test_magnitud_del_error_sin_corregir():
    """Cuantifica lo que se gana: sobre un mate típico son milímetros."""
    mapping = ConeMapping(diameter_start=90.0, diameter_end=70.0, length=100.0,
                          contact_diameter=80.0)
    _, y_base = mapping.to_machine(20.0, 0.0)
    _, y_tope = mapping.to_machine(20.0, 100.0)

    # Más de 5 mm de corrimiento entre la base y el tope: perfectamente
    # visible a simple vista en la pieza terminada.
    assert abs(y_tope - y_base) > 5.0


def test_el_conico_subdivide_los_segmentos():
    """Una recta del diseño es una curva en el espacio de la máquina."""
    mapping = ConeMapping(diameter_start=90.0, diameter_end=70.0, length=100.0)
    puntos = [(20.0, 0.0), (20.0, 100.0)]  # una "vertical" del diseño

    warped = mapping.warp_polyline(puntos, max_segment_mm=5.0)

    assert len(warped) > 15  # se subdividió
    ys = [y for _, y in warped]
    assert ys == sorted(ys)  # monótono, sin saltos
    # Y el punto del medio NO está en la recta entre extremos: eso es la curvatura.
    medio = warped[len(warped) // 2]
    interpolado = (ys[0] + ys[-1]) / 2
    assert abs(medio[1] - interpolado) > 0.01


def test_el_cilindro_no_subdivide():
    mapping = cylinder(diameter_mm=80.0, length_mm=100.0)
    warped = mapping.warp_polyline([(0.0, 0.0), (0.0, 100.0)])
    assert len(warped) == 2


def test_semiangulo_del_cono():
    mapping = ConeMapping(diameter_start=80.0, diameter_end=100.0, length=100.0)
    # radio crece 10 mm en 100 mm de largo -> atan(0.1)
    assert mapping.taper_angle_deg == pytest.approx(math.degrees(math.atan(0.1)))


def test_franja_de_foco_crece_con_el_diametro():
    """Cuanto más plano el objeto, más ancho podés grabar de una pasada."""
    angosto = focus_band_width(40.0, 0.5)
    ancho = focus_band_width(120.0, 0.5)
    assert ancho > angosto
    # Un termo de 80 mm da alrededor de 12-13 mm de franja útil.
    assert 10.0 < focus_band_width(80.0, 0.5) < 15.0


def test_calibracion_por_vuelta_medida():
    """Si giró de más, hay que bajar los pasos/mm."""
    inicial = 80.0
    # Una vuelta de un objeto de 100 mm debería medir pi*100 = 314.16 mm.
    # Midiendo 2 mm de más, giró de más: el nuevo valor tiene que ser mayor
    # porque hacen falta más pasos por mm comandado para el mismo arco.
    corregido = calibrate_from_wrap(inicial, 100.0, error_mm=2.0)
    assert corregido > inicial
    assert corregido == pytest.approx(inicial * (math.pi * 100 + 2) / (math.pi * 100))


def test_pasos_por_mm_teoricos():
    # NEMA17 de 200 pasos, 16 microsteps, rodillo de 15 mm
    valor = steps_per_mm_for_roller(200, 16, 15.0)
    assert valor == pytest.approx(3200 / (math.pi * 15.0))


def test_diametros_invalidos():
    with pytest.raises(ValueError):
        ConeMapping(diameter_start=0.0, diameter_end=50.0, length=100.0)
    with pytest.raises(ValueError):
        ConeMapping(diameter_start=50.0, diameter_end=50.0, length=0.0)
