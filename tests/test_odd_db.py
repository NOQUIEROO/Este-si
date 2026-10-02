from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from odd.db import ANFITRION, NOMINACION, Database
from odd.estado import ACTIVO, BAJA, COMUN, ENVIADA, ESPECIAL, INSTALADA, PAUSA, PAUSADO

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
OBELISCO = (-34.603722, -58.381592)


@pytest.fixture()
def db(tmp_path):
    base = Database(tmp_path / "odd.db")
    yield base
    base.close()


def alta(db, lat=OBELISCO[0], lon=OBELISCO[1], alias="el bar", **kwargs):
    return db.alta_bar(
        alias=alias,
        lat=lat,
        lon=lon,
        direccion=kwargs.get("direccion"),
        placa_lugar=kwargs.get("placa_lugar", "frente"),
        nota=kwargs.get("nota"),
        origen=kwargs.get("origen", "fundacional"),
        now=kwargs.get("now", NOW),
    )


# ------------------------------------------------------------------- bares


def test_un_bar_nuevo_nace_activo(db):
    bar_id = alta(db, alias="Bar Trece", direccion="Sarmiento 1234")
    bar = db.get_bar(bar_id)
    assert bar.alias == "Bar Trece"
    assert bar.direccion == "Sarmiento 1234"
    assert bar.estado == ACTIVO
    assert bar.placa is None
    assert bar.pasos == 0


def test_un_lugar_de_placa_inventado_no_entra(db):
    with pytest.raises(ValueError):
        alta(db, placa_lugar="en la vereda")


def test_pausar_un_bar_lo_saca_de_la_busqueda(db):
    bar_id = alta(db)
    assert len(db.cerca(*OBELISCO, radius_m=1000, limit=10)) == 1

    db.evento_bar(bar_id, PAUSA, now=NOW + timedelta(days=1))
    assert db.get_bar(bar_id).estado == PAUSADO
    assert db.cerca(*OBELISCO, radius_m=1000, limit=10) == []
    # Pero sigue existiendo: no se borró nada.
    assert len(db.cerca(*OBELISCO, radius_m=1000, limit=10, incluir_cerrados=True)) == 1


def test_la_busqueda_ordena_por_distancia_y_respeta_el_radio(db):
    cerca = alta(db, -34.603722, -58.381592, alias="cerca")
    medio = alta(db, -34.609722, -58.392500, alias="medio")  # ~1,2 km
    alta(db, -34.700000, -58.500000, alias="lejos")  # ~15 km

    encontrados = db.cerca(*OBELISCO, radius_m=3000, limit=10)
    assert [bar.id for bar in encontrados] == [cerca, medio]
    assert encontrados[0].distance_m < encontrados[1].distance_m


def test_la_busqueda_respeta_el_limite(db):
    for i in range(8):
        alta(db, OBELISCO[0] + i * 0.001, OBELISCO[1], alias=f"bar {i}")
    assert len(db.cerca(*OBELISCO, radius_m=5000, limit=3)) == 3


# ------------------------------------------------------------------ placas


def test_las_placas_se_numeran_correlativas(db):
    assert db.emitir_placas(3) == [1, 2, 3]
    assert db.emitir_placas(2) == [4, 5]
    assert db.emitir_placas(0) == []
    assert db.placas_en_stock() == [1, 2, 3, 4, 5]


def test_asignar_una_placa_la_pega_al_bar(db):
    bar_id = alta(db, alias="Bar Trece")
    db.emitir_placas(2, now=NOW)
    db.asignar_placa(2, bar_id, now=NOW)

    assert db.get_bar(bar_id).placa == 2
    assert db.placas_en_stock() == [1]

    placa = db.get_placa(2)
    assert placa.bar_alias == "Bar Trece"
    assert placa.estado == "asignada"

    db.evento_placa(2, ENVIADA, bar_id, now=NOW + timedelta(days=1))
    db.evento_placa(2, INSTALADA, bar_id, now=NOW + timedelta(days=5))
    assert db.get_placa(2).estado == INSTALADA


def test_una_placa_de_baja_deja_al_bar_sin_placa(db):
    bar_id = alta(db)
    db.emitir_placas(1, now=NOW)
    db.asignar_placa(1, bar_id, now=NOW)
    db.evento_placa(1, BAJA, bar_id, now=NOW + timedelta(days=30))
    assert db.get_bar(bar_id).placa is None


def test_no_se_puede_mover_una_placa_que_no_existe(db):
    with pytest.raises(ValueError):
        db.evento_placa(99, ENVIADA)


def test_verificar_una_placa_que_no_emitimos(db):
    assert db.get_placa(1) is None


# ------------------------------------------------------------------- pasos


def paso(db, bar_id, *, primera=True, contacto="hola@mail.com", now=NOW):
    return db.registrar_paso(
        bar_id=bar_id,
        foto="file-id-de-telegram",
        es_primera=primera,
        contacto=contacto,
        credito=3.0,
        now=now,
    )


def test_una_reflexion_arranca_sin_leer_y_suma_al_bar(db):
    bar_id = alta(db)
    paso_id = paso(db, bar_id)

    guardado = db.get_paso(paso_id)
    assert guardado.veredicto == "pendiente"
    assert guardado.es_primera is True
    assert guardado.contacto == "hola@mail.com"
    assert db.get_bar(bar_id).pasos == 1
    assert [p.id for p in db.pasos_sin_leer()] == [paso_id]


def test_juzgarla_la_saca_de_la_pila(db):
    bar_id = alta(db)
    paso_id = paso(db, bar_id)
    db.juzgar(paso_id, ESPECIAL, now=NOW + timedelta(hours=2))

    assert db.get_paso(paso_id).veredicto == ESPECIAL
    assert db.pasos_sin_leer() == []


def test_el_resumen_del_bar_cuenta_lo_que_le_importa_al_dueño(db):
    bar_id = alta(db)
    primero = paso(db, bar_id, primera=True)
    paso(db, bar_id, primera=False, contacto=None, now=NOW + timedelta(days=1))
    paso(db, bar_id, primera=True, now=NOW + timedelta(days=2))
    db.juzgar(primero, ESPECIAL)

    resumen = db.resumen_bar(bar_id)
    assert resumen["pasos"] == 3
    assert resumen["primeras"] == 2
    assert resumen["contactos"] == 2  # el que no dejó contacto no cuenta
    assert resumen["credito"] == 9.0
    assert resumen["especiales"] == 1


def test_un_veredicto_no_se_cuenta_dos_veces(db):
    bar_id = alta(db)
    paso_id = paso(db, bar_id)
    db.juzgar(paso_id, ESPECIAL, now=NOW)
    db.juzgar(paso_id, COMUN, now=NOW + timedelta(days=1))
    db.juzgar(paso_id, ESPECIAL, now=NOW + timedelta(days=2))
    assert db.resumen_bar(bar_id)["especiales"] == 1


# ----------------------------------------------------------------- códigos


def test_un_codigo_de_anfitrion_vincula_el_bar(db):
    bar_id = alta(db)
    db.crear_codigo("ODD-AAAA-BBBB", ANFITRION, bar_id=bar_id, max_usos=1)

    codigo = db.validar_codigo("odd-aaaa-bbbb")  # el caso no importa
    assert codigo is not None and codigo.bar_id == bar_id
    assert db.consumir_codigo(codigo.id) is True

    db.vincular_anfitrion("hash-del-dueño", bar_id)
    assert db.bar_de_anfitrion("hash-del-dueño") == bar_id
    assert db.bar_de_anfitrion("cualquier-otro") is None


def test_un_codigo_gastado_no_sirve_mas(db):
    bar_id = alta(db)
    db.crear_codigo("ODD-AAAA-BBBB", ANFITRION, bar_id=bar_id, max_usos=2)
    codigo = db.validar_codigo("ODD-AAAA-BBBB")

    assert db.consumir_codigo(codigo.id) is True
    assert db.consumir_codigo(codigo.id) is True
    assert db.consumir_codigo(codigo.id) is False  # el tercero ya no entra
    assert db.validar_codigo("ODD-AAAA-BBBB") is None


def test_un_codigo_que_no_existe(db):
    assert db.validar_codigo("ODD-ZZZZ-ZZZZ") is None


def test_el_codigo_no_se_guarda_en_claro(db):
    bar_id = alta(db)
    db.crear_codigo("ODD-AAAA-BBBB", ANFITRION, bar_id=bar_id)
    guardados = [
        fila["code_hash"] for fila in db.raw_connection().execute("SELECT code_hash FROM codigos")
    ]
    assert "ODD-AAAA-BBBB" not in guardados


# ------------------------------------------------------------- nominaciones


def test_una_propuesta_aprobada_se_vuelve_un_bar(db):
    bar_id = alta(db)
    paso_id = paso(db, bar_id)
    db.juzgar(paso_id, ESPECIAL)
    db.crear_codigo("ODD-CCCC-DDDD", NOMINACION, paso_id=paso_id)

    nominacion_id = db.crear_nominacion(
        alias="El Progreso",
        lat=-34.60,
        lon=-58.38,
        motivo="porque ahí escribí la reflexión",
        paso_id=paso_id,
        now=NOW,
    )
    assert [n.id for n in db.nominaciones_abiertas()] == [nominacion_id]

    nuevo_bar = db.aprobar_nominacion(nominacion_id, now=NOW + timedelta(days=1))
    bar = db.get_bar(nuevo_bar)
    assert bar.alias == "El Progreso"
    assert bar.origen == "nominado"
    assert bar.estado == ACTIVO
    assert db.nominaciones_abiertas() == []
    # Aprobar dos veces no crea dos bares.
    assert db.aprobar_nominacion(nominacion_id) is None


def test_una_propuesta_rechazada_no_crea_nada(db):
    nominacion_id = db.crear_nominacion(
        alias="El Otro", lat=-34.6, lon=-58.4, motivo=None, paso_id=None, now=NOW
    )
    db.evento_nominacion(nominacion_id, "rechazada", now=NOW + timedelta(days=1))
    assert db.nominaciones_abiertas() == []
    assert db.count_bares() == 0
    assert db.aprobar_nominacion(nominacion_id) is None


# --------------------------------------------------------------- la casa


def test_no_hay_un_solo_delete_en_la_capa_de_datos():
    """Si alguien agrega un metodo que borre, este test falla."""
    fuente = (Path(__file__).parent.parent / "odd" / "db.py").read_text(encoding="utf-8")
    assert "DELETE FROM" not in fuente.upper()
    assert "DROP TABLE" not in fuente.upper()


def test_la_foto_de_la_reflexion_no_vive_en_la_base(db):
    """Guardamos el puntero de Telegram, nunca los bytes."""
    bar_id = alta(db)
    paso(db, bar_id)
    columnas = {
        fila[1]: fila[2]
        for fila in db.raw_connection().execute("PRAGMA table_info(pasos)")
    }
    assert columnas["foto"] == "TEXT"
    assert "BLOB" not in set(columnas.values())


def test_el_censo_cuenta_todo(db):
    bar_id = alta(db)
    otro = alta(db, alias="el otro")
    db.evento_bar(otro, PAUSA, now=NOW + timedelta(days=1))
    db.emitir_placas(3, now=NOW)
    db.asignar_placa(1, bar_id, now=NOW)
    db.evento_placa(1, INSTALADA, bar_id, now=NOW + timedelta(days=2))
    primero = paso(db, bar_id)
    paso(db, bar_id, primera=False, contacto=None)
    db.juzgar(primero, ESPECIAL)
    db.vincular_anfitrion("hash", bar_id)

    s = db.stats()
    assert s["bares"] == 2
    assert s["activos"] == 1
    assert s["pasos"] == 2
    assert s["contactos"] == 1
    assert s["credito"] == 6.0
    assert s["especiales"] == 1
    assert s["sin_leer"] == 1
    assert s["anfitriones"] == 1
    assert s["placas"] == 3
    assert s["placas_stock"] == 2
    assert s["placas_puestas"] == 1
