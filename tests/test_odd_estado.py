from datetime import datetime, timedelta, timezone

from odd.estado import (
    ACTIVO,
    ALTA,
    ASIGNADA,
    COMUN,
    EMITIDA,
    ESPECIAL,
    INSTALADA,
    PAUSA,
    PAUSADO,
    PENDIENTE,
    REACTIVACION,
    RETIRADO,
    RETIRO,
    estado_bar,
    estado_placa,
    es_visitable,
    hace,
    veredicto,
)

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def dias(cantidad: float) -> datetime:
    return NOW + timedelta(days=cantidad)


def test_un_bar_sin_historia_esta_activo():
    assert estado_bar([]) == ACTIVO


def test_el_estado_es_siempre_el_ultimo_evento():
    historia = [(ALTA, dias(0)), (PAUSA, dias(10)), (REACTIVACION, dias(20))]
    assert estado_bar(historia) == ACTIVO
    assert estado_bar(historia + [(PAUSA, dias(30))]) == PAUSADO
    assert estado_bar(historia + [(RETIRO, dias(30))]) == RETIRADO


def test_el_orden_en_que_llegan_los_eventos_no_importa():
    """Se ordena por fecha, no por posicion en la lista."""
    desordenado = [(PAUSA, dias(10)), (ALTA, dias(0)), (REACTIVACION, dias(20))]
    assert estado_bar(desordenado) == ACTIVO


def test_solo_los_activos_se_muestran():
    assert es_visitable(ACTIVO)
    assert not es_visitable(PAUSADO)
    assert not es_visitable(RETIRADO)


def test_una_placa_arranca_en_stock_y_avanza():
    assert estado_placa([]) == EMITIDA
    historia = [(EMITIDA, dias(0)), (ASIGNADA, dias(1))]
    assert estado_placa(historia) == ASIGNADA
    assert estado_placa(historia + [(INSTALADA, dias(5))]) == INSTALADA


def test_una_reflexion_arranca_sin_leer():
    assert veredicto([]) == PENDIENTE
    assert veredicto([(COMUN, dias(1))]) == COMUN
    # Un admin puede cambiar de opinion: vale el ultimo veredicto.
    assert veredicto([(COMUN, dias(1)), (ESPECIAL, dias(2))]) == ESPECIAL
    assert veredicto([(ESPECIAL, dias(2)), (COMUN, dias(3))]) == COMUN


def test_las_fechas_se_leen_como_las_diria_una_persona():
    assert hace(NOW, NOW) == "recién"
    assert hace(NOW, NOW + timedelta(hours=5)) == "hace 5 h"
    assert hace(NOW, NOW + timedelta(days=1.2)) == "ayer"
    assert hace(NOW, NOW + timedelta(days=10)) == "hace 10 días"
    assert hace(NOW, NOW + timedelta(days=90)) == "hace 3 meses"
    assert hace(NOW, NOW + timedelta(days=800)) == "hace 2 años"
