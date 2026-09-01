"""Tests del generador de G-code y del raster."""

from __future__ import annotations

import pytest

from laserq.gcode.builder import GcodeOptions, GcodeProgram, measure
from laserq.gcode.raster import RasterOptions, _runs, dither, raster_to_gcode


def test_preamble_arranca_con_el_laser_apagado():
    program = GcodeProgram()
    program.preamble()
    lines = [l for l in program if not l.startswith(";")]
    assert lines[0] == "G21"
    assert "M5 S0" in lines[:5]
    # M4 y no M3: potencia dinámica.
    assert any(l.startswith("M4") for l in lines)
    assert not any(l.startswith("M3") for l in lines)


def test_modo_constante_usa_m3():
    program = GcodeProgram(GcodeOptions(dynamic_power=False))
    program.preamble()
    assert any(l.startswith("M3") for l in program)


def test_no_repite_feed_ni_power():
    """Cada byte repetido es lookahead que le sacás al planificador."""
    program = GcodeProgram()
    program.cut(10, 0, feed=3000, power=500)
    program.cut(20, 0, feed=3000, power=500)
    program.cut(30, 0, feed=3000, power=500)
    lines = list(program)
    assert "F3000" in lines[0] and "S500" in lines[0]
    assert "F" not in lines[1] and "S" not in lines[1]
    assert "F" not in lines[2]


def test_rapid_apaga_el_laser():
    program = GcodeProgram()
    program.cut(10, 0, feed=3000, power=800)
    program.rapid(0, 0)
    assert "S0" in list(program)[-1]


def test_measure_calcula_el_bounding_box():
    program = GcodeProgram()
    program.rapid(10, 20)
    program.cut(50, 20, feed=1000, power=100)
    program.cut(50, 70, feed=1000, power=100)
    box = measure(list(program))
    assert box.min_x == 10 and box.max_x == 50
    assert box.min_y == 20 and box.max_y == 70
    assert box.width == 40 and box.height == 50


def test_agrupa_pixeles_iguales_en_un_solo_movimiento():
    values = [1.0, 1.0, 1.0, 0.0, 0.0, 1.0]
    runs = _runs(values, lambda v: int(v * 1000))
    assert runs == [(0, 3, 1000), (3, 5, 0), (5, 6, 1000)]


def test_el_raster_no_graba_filas_vacias():
    rows = [[0.0] * 10, [1.0] * 10, [0.0] * 10]
    options = RasterOptions(mode="grayscale", skip_blank=True, dpi=254)
    program = raster_to_gcode(rows, options)
    # ojo: "G17" (plano XY) también empieza con "G1". Filtrar bien.
    cortes = [l for l in program if l.startswith("G1") and "X" in l]
    # Una sola fila con contenido -> un solo tramo de grabado.
    assert len(cortes) == 1


def test_el_raster_alterna_direccion():
    rows = [[1.0] * 10 for _ in range(4)]
    options = RasterOptions(mode="grayscale", bidirectional=True, overscan_mm=2.0)
    program = raster_to_gcode(rows, options)
    rapidos = [l for l in program if l.startswith("G0") and "X" in l]
    # Los arranques de fila alternan entre el borde izquierdo y el derecho.
    assert len(rapidos) >= 4


def test_dithering_binario():
    rows = [[0.2, 0.8, 0.5, 0.9] for _ in range(4)]
    salida = dither(rows, RasterOptions(mode="floyd-steinberg"))
    for fila in salida:
        for valor in fila:
            assert valor in (0.0, 1.0)


def test_dithering_conserva_la_densidad_media():
    """Un gris uniforme al 50% tiene que dar ~50% de puntos encendidos."""
    rows = [[0.5] * 40 for _ in range(40)]
    salida = dither(rows, RasterOptions(mode="floyd-steinberg"))
    encendidos = sum(sum(f) for f in salida)
    assert 0.4 < encendidos / 1600 < 0.6


def test_grayscale_no_binariza():
    rows = [[0.33, 0.66]]
    salida = dither(rows, RasterOptions(mode="grayscale"))
    assert salida == rows


def test_modo_desconocido_falla_claro():
    with pytest.raises(ValueError, match="desconocido"):
        dither([[0.5]], RasterOptions(mode="inventado"))


# ------------------------------------------------------------------- fuente

def test_la_fuente_cubre_el_abecedario():
    from laserq.gcode.font import unsupported
    assert unsupported("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") == []


def test_la_fuente_graba_enes_y_acentos():
    """Un soporte personalizado que dice "PENA" en vez de "PEÑA" es basura."""
    from laserq.gcode.font import glyph, normalize, unsupported
    assert normalize("Martín") == "MARTÍN"
    assert normalize("Muñoz") == "MUÑOZ"
    assert unsupported("José Ñandú Güemes") == []
    # la Ñ es la N más el trazo de la tilde, no un glifo suelto
    assert len(glyph("Ñ")) == len(glyph("N")) + 1


def test_un_diacritico_sin_glifo_se_descarta_en_vez_de_fallar():
    """No tenemos cedilla. Mejor grabar FRANCAIS que dejar un hueco."""
    from laserq.gcode.font import normalize, unsupported
    assert normalize("Français") == "FRANCAIS"
    assert unsupported("Français") == []


def test_avisa_de_caracteres_no_soportados():
    from laserq.gcode.font import unsupported
    assert unsupported("HOLA@CASA") == ["@"]


def test_centrado_de_texto():
    from laserq.gcode.font import text_polylines, text_width
    ancho = text_width("ABC", 10.0)
    centrado = text_polylines("ABC", 0.0, 0.0, 10.0, center=True)
    xs = [x for poli in centrado for x, _ in poli]
    assert min(xs) == pytest.approx(-ancho / 2, abs=0.01)


def test_engrosar_repite_el_trazo_en_cruz():
    """Una tipografía de trazo único deja un pelo del ancho del kerf."""
    from laserq.gcode.font import thicken
    trazo = [[(0.0, 0.0), (10.0, 0.0)]]

    assert len(thicken(trazo, 0.0)) == 1

    grueso = thicken(trazo, 0.3)
    assert len(grueso) == 5          # el original más cuatro en cruz
    ys = [y for polyline in grueso for _, y in polyline]
    assert max(ys) - min(ys) == pytest.approx(0.3)


def test_engrosar_saca_las_copias_de_un_trazo_juntas():
    """Intercalarlas sería pagar un traslado por cada desplazamiento."""
    from laserq.gcode.font import thicken
    a, b = [(0.0, 0.0), (1.0, 0.0)], [(5.0, 5.0), (6.0, 5.0)]

    grueso = thicken([a, b], 0.3)

    assert all(p[0][0] < 2 for p in grueso[:5])
    assert all(p[0][0] > 4 for p in grueso[5:])
