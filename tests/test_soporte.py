"""Tests del soporte de notebook.

Casi todo lo que puede salir mal acá sale mal en silencio: una ranura con el
kerf al revés encastra floja, un tope un milímetro alto hamaca, y el grabado
después del corte funciona hasta el día que una pieza se mueve. Ninguna de
esas cosas tira una excepción, así que cada una tiene su test.
"""

from __future__ import annotations

import pytest

from laserq.gcode.cut import HOLE, PART, CutOptions
from laserq.gcode.font import text_width
from laserq.products.soporte import (
    PRESETS,
    SoporteSpec,
    _contornos,
    build_soporte,
    medidas,
    perfil_longitudinal,
    perfil_transversal,
)

CORTE = CutOptions(speed=300, power=1000, passes=3, kerf_mm=0.25)


def _spec(**kwargs) -> SoporteSpec:
    base = dict(espesor=2.9, kerf=0.25, nombre="Javi", marca="CounterLabs")
    base.update(kwargs)
    return SoporteSpec(**base)


def _rango(points, eje: int):
    valores = [p[eje] for p in points]
    return min(valores), max(valores)


# ------------------------------------------------------------------- kerf


def test_la_ranura_sale_del_espesor_menos_el_kerf():
    """2.90 de plancha y 0.25 de kerf tienen que dar un camino de 2.65."""
    spec = _spec()
    contornos = _contornos(spec)
    perimetro_t = next(c for c in contornos if c.role == PART)

    # Se mide en la boca de la muesca, sobre el canto: ahí están las dos
    # mejillas y nada más. Adentro está el alivio, que es más ancho a propósito.
    centro = spec.margen + spec.ancho / 2
    canto = max(p[1] for p in perimetro_t.points)
    mejillas = sorted(p[0] for p in perimetro_t.points
                      if abs(p[1] - canto) < 1e-6 and abs(p[0] - centro) < 5.0)

    assert len(mejillas) == 2
    assert mejillas[1] - mejillas[0] == pytest.approx(2.65, abs=1e-6)
    assert spec.ranura_dibujada == 2.65


def test_sin_kerf_la_ranura_es_el_espesor():
    spec = _spec(kerf=0.0)
    assert spec.ranura_dibujada == 2.9


def test_el_perimetro_crece_lo_que_la_ranura_se_achica():
    """Un solo desplazamiento resuelve las dos cosas, con signos opuestos."""
    con = _spec()
    sin = _spec(kerf=0.0)
    ancho_con = _rango(_contornos(con)[-1].points, 0)
    ancho_sin = _rango(_contornos(sin)[-1].points, 0)

    crecio = (ancho_con[1] - ancho_con[0]) - (ancho_sin[1] - ancho_sin[0])
    assert crecio == pytest.approx(0.25, abs=1e-6)


# -------------------------------------------------------------- geometría


def test_las_dos_muescas_van_en_sentidos_opuestos():
    """Si las dos abrieran para el mismo lado, las piezas no encastran."""
    spec = _spec()
    t = perfil_transversal(spec, 0.0, 0.0)
    ele = perfil_longitudinal(spec, 0.0, 0.0)
    centro_t, centro_l = spec.ancho / 2, spec.fondo / 2

    # en la T la muesca baja desde el canto de arriba
    raiz_t = min(p[1] for p in t if abs(p[0] - centro_t) < 2.0)
    assert raiz_t == pytest.approx(spec.altura - spec.profundidad_muesca, abs=spec.alivio)

    # en la L sube desde la base
    raiz_l = max(p[1] for p in ele if abs(p[0] - centro_l) < 2.0)
    assert raiz_l == pytest.approx(spec.profundidad_muesca, abs=spec.alivio)


def test_el_tope_de_la_t_queda_al_ras_del_canto_de_la_l():
    """La invariante del diseño: si no, la notebook se hamaca sobre la T."""
    spec = _spec()
    altura_l_en_el_cruce = (spec.altura_frente + spec.altura_fondo) / 2

    assert altura_l_en_el_cruce == pytest.approx(spec.altura)
    assert _rango(perfil_transversal(spec, 0.0, 0.0), 1)[1] == pytest.approx(spec.altura)


def test_el_alivio_asoma_de_la_ranura():
    """Si no asoma no alivia nada: el esquinero vivo sigue ahí."""
    spec = _spec()
    t = perfil_transversal(spec, 0.0, 0.0)
    centro = spec.ancho / 2
    cerca = [p[0] for p in t if abs(p[0] - centro) < 5.0]

    # El arco se emite como polilínea inscrita, así que el ancho medido queda
    # unas centésimas por debajo del nominal. Es la aproximación, no un error.
    assert max(cerca) - min(cerca) == pytest.approx(spec.alivio, abs=0.02)
    assert max(cerca) - min(cerca) > spec.espesor


def test_el_angulo_reparte_el_desnivel_a_los_dos_lados_del_cruce():
    spec = _spec(altura=100.0, fondo=220.0, angulo=15.0)

    assert spec.altura_frente == pytest.approx(70.5, abs=0.1)
    assert spec.altura_fondo == pytest.approx(129.5, abs=0.1)
    assert (spec.altura_frente + spec.altura_fondo) / 2 == pytest.approx(100.0)


# ----------------------------------------------------------------- orden


def _potencias(program) -> list[float]:
    salida = []
    for line in program:
        if line.startswith(("G1", "G0")) and "S" in line:
            valor = line.split("S", 1)[1]
            numero = ""
            for char in valor:
                if char.isdigit() or char == ".":
                    numero += char
                else:
                    break
            if numero:
                salida.append(float(numero))
    return salida


def test_primero_graba_y_despues_corta():
    """Grabar sobre una pieza ya suelta es cómo se arruina la última unidad."""
    program = build_soporte(_spec(), CORTE, grabado_feed=2500, grabado_power=300)
    potencias = [p for p in _potencias(program) if p > 0]

    assert potencias, "el programa no encendió el láser nunca"
    assert potencias[0] == 300           # arranca grabando
    assert potencias[-1] == 1000         # termina cortando
    assert potencias.index(1000) > max(i for i, p in enumerate(potencias) if p == 300)


def test_el_pasa_cables_se_corta_antes_que_el_perimetro():
    contornos = _contornos(_spec(pasa_cables=True))

    assert contornos[0].role == HOLE
    assert all(c.role == PART for c in contornos[1:])


def test_sin_pasa_cables_no_queda_ningun_agujero():
    assert all(c.role == PART for c in _contornos(_spec(pasa_cables=False)))


# --------------------------------------------------------------- grabado


def test_un_nombre_largo_se_achica_hasta_entrar():
    corto = medidas(_spec(nombre="Ana"), CORTE).grabado_alto
    largo = medidas(_spec(nombre="Guadalupe"), CORTE).grabado_alto

    assert corto == 20.0
    assert 8.0 < largo < 20.0


def test_un_nombre_imposible_avisa_en_vez_de_salirse():
    spec = _spec(nombre="Guadalupe Fernandez Etchegaray")

    assert medidas(spec, CORTE).grabado_alto == 8.0     # tocó el piso
    assert any("no entra" in aviso for aviso in spec.advertencias())


def test_un_nombre_con_ene_no_es_un_problema():
    """El motivo de haber agregado los glifos acentuados."""
    program = build_soporte(_spec(nombre="Peña"), CORTE)

    assert len(program) > 0
    assert "Peña" in program.as_text()


def test_un_caracter_sin_glifo_falla_antes_de_encender_el_laser():
    with pytest.raises(ValueError, match="no tiene"):
        build_soporte(_spec(nombre="Javi@casa"), CORTE)


# ---------------------------------------------------------------- límites


def test_un_kerf_mayor_al_espesor_falla_claro():
    with pytest.raises(ValueError, match="se come el espesor"):
        build_soporte(_spec(espesor=0.2, kerf=0.25), CORTE)


def test_un_angulo_que_se_come_el_frente_falla_claro():
    with pytest.raises(ValueError, match="apoya sobre un filo"):
        build_soporte(_spec(angulo=40.0), CORTE)


def test_un_alivio_mas_chico_que_el_espesor_falla_claro():
    with pytest.raises(ValueError, match="mayor que el espesor"):
        build_soporte(_spec(alivio=2.0), CORTE)


def test_las_dos_piezas_entran_en_la_plancha_de_la_maquina():
    ancho, alto = _spec().plancha

    assert ancho <= 410 and alto <= 400


# ------------------------------------------------- dónde va el nombre


def test_el_nombre_no_va_en_el_medio_de_la_pieza():
    """El error de la v1: el centro de la T es donde se para la otra pieza.

    Grabado ahí, el nombre queda partido al medio y tapado. Se ve en la
    primera unidad física y no se ve en ningún test que mire solo números,
    así que va este.
    """
    spec = _spec(nombre="Javi")
    alto = medidas(spec, CORTE).grabado_alto
    mitad_texto = text_width(spec.nombre, alto) / 2
    derecha = spec.grabado_centro_x + mitad_texto

    assert derecha < spec.ancho / 2 - spec.espesor


def test_el_ala_del_nombre_se_elige():
    izq = _spec(nombre="Javi", nombre_lado="izq").grabado_centro_x
    der = _spec(nombre="Javi", nombre_lado="der").grabado_centro_x

    assert izq < 300 / 2 < der
    assert izq + der == pytest.approx(300.0)


def test_un_ala_inexistente_falla_claro():
    with pytest.raises(ValueError, match="nombre_lado"):
        build_soporte(_spec(nombre="Javi", nombre_lado="arriba"), CORTE)


def test_el_grosor_multiplica_los_trazos_del_grabado():
    fino = build_soporte(_spec(nombre="Javi", grosor=0.0), CORTE)
    grueso = build_soporte(_spec(nombre="Javi", grosor=0.3), CORTE)

    assert len(grueso) > len(fino)


# --------------------------------------------------------------- presets


def test_los_dos_presets_generan_piezas_validas():
    for nombre, valores in PRESETS.items():
        spec = SoporteSpec(espesor=2.9, kerf=0.25, **valores)
        assert spec.problemas() == [], f"el preset {nombre} no valida"


def test_el_preset_bajo_es_realmente_mas_bajo():
    alto = SoporteSpec(espesor=2.9, kerf=0.25, **PRESETS["alto"])
    bajo = SoporteSpec(espesor=2.9, kerf=0.25, **PRESETS["bajo"])

    assert bajo.altura_frente < alto.altura_frente
    assert bajo.altura_fondo < alto.altura_fondo
    assert bajo.altura_frente > 12       # no apoya sobre un filo
    assert bajo.profundidad_muesca > 12  # la unión sigue agarrando


# ------------------------------------------- dónde viven los valores


def test_el_grosor_vive_en_el_perfil_junto_a_la_velocidad(tmp_path):
    """Se miden juntos en la misma placa: separarlos invita a mezclarlos."""
    from laserq.profiles import MaterialProfile, load_material, save_material

    save_material(
        MaterialProfile(name="mdf_texto", operation="engrave",
                        speed=1000, power=600, grosor_mm=0.4),
        tmp_path,
    )
    vuelto = load_material("mdf_texto", tmp_path)

    assert (vuelto.speed, vuelto.power) == (1000, 600)
    assert vuelto.grosor_mm == 0.4


def test_un_perfil_sin_grosor_no_engrosa_nada(tmp_path):
    from laserq.profiles import MaterialProfile, load_material, save_material

    save_material(MaterialProfile(name="pelado", speed=1000, power=600), tmp_path)

    assert load_material("pelado", tmp_path).grosor_mm == 0.0
