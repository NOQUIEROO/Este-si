from datetime import datetime, timedelta, timezone

import pytest

from glitchmap.db import Database
from glitchmap.stability import COLLAPSE, CONFIRM

NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)
OBELISCO = (-34.603722, -58.381592)


@pytest.fixture()
def db(tmp_path):
    base = Database(tmp_path / "test.db")
    yield base
    base.close()


def add(db, lat, lon, alias="punto", **kwargs):
    return db.add_glitch(
        alias=alias,
        lat=lat,
        lon=lon,
        cobertura=kwargs.get("cobertura", "techo"),
        interferencia=kwargs.get("interferencia", "baja"),
        ventana=kwargs.get("ventana", "noche"),
        nota=kwargs.get("nota"),
        now=kwargs.get("now", NOW),
    )


def test_guarda_y_recupera(db):
    gid = add(db, *OBELISCO, alias="el banco del fondo", nota="entras por atras")
    glitch = db.get_glitch(gid, now=NOW)
    assert glitch is not None
    assert glitch.alias == "el banco del fondo"
    assert glitch.nota == "entras por atras"
    assert glitch.confirms == 0


def test_nadie_puede_saber_quien_cargo_que(db):
    """La garantia central: no hay columna de usuario en el contenido."""
    add(db, *OBELISCO)
    columnas = {
        row[1]
        for table in ("glitches", "signals")
        for row in db.raw_connection().execute(f"PRAGMA table_info({table})")
    }
    assert not any("user" in c or "member" in c or "hash" in c for c in columnas)


def test_escaneo_ordena_por_distancia_y_respeta_el_radio(db):
    cerca = add(db, -34.603722, -58.381592, alias="cerca")
    medio = add(db, -34.609722, -58.392500, alias="medio")  # ~1,2 km
    add(db, -34.700000, -58.500000, alias="lejos")  # ~15 km

    encontrados = db.nearby(*OBELISCO, radius_m=3000, limit=10, now=NOW)
    assert [g.id for g in encontrados] == [cerca, medio]
    assert encontrados[0].distance_m < encontrados[1].distance_m


def test_el_limite_recorta(db):
    for i in range(5):
        add(db, -34.603722 + i * 0.001, -58.381592, alias=f"p{i}")
    assert len(db.nearby(*OBELISCO, radius_m=3000, limit=2, now=NOW)) == 2


def test_un_glitch_colapsado_desaparece_del_escaneo_pero_no_de_la_base(db):
    gid = add(db, *OBELISCO)
    for i in range(3):
        db.add_signal(gid, COLLAPSE, now=NOW + timedelta(hours=i))

    later = NOW + timedelta(days=1)
    assert db.nearby(*OBELISCO, radius_m=3000, limit=10, now=later) == []
    # Sigue existiendo, y aparece si lo pedis explicitamente.
    con_desvanecidas = db.nearby(
        *OBELISCO, radius_m=3000, limit=10, include_faded=True, now=later
    )
    assert [g.id for g in con_desvanecidas] == [gid]
    assert db.get_glitch(gid, now=later) is not None
    assert db.count_glitches() == 1


def test_confirmar_sube_el_puntaje(db):
    gid = add(db, *OBELISCO)
    antes = db.get_glitch(gid, now=NOW).score
    db.add_signal(gid, CONFIRM, now=NOW)
    assert db.get_glitch(gid, now=NOW).score > antes


def test_senal_desconocida_es_error(db):
    gid = add(db, *OBELISCO)
    with pytest.raises(ValueError):
        db.add_signal(gid, "sabotaje")


def test_codigo_de_invitacion_se_agota(db):
    db.create_invite("GLX-AAAA-BBBB", max_uses=2, now=NOW)
    assert db.redeem_invite("GLX-AAAA-BBBB", "hash-1") is True
    assert db.redeem_invite("GLX-AAAA-BBBB", "hash-2") is True
    assert db.redeem_invite("GLX-AAAA-BBBB", "hash-3") is False
    assert db.is_member("hash-1") and not db.is_member("hash-3")


def test_codigo_no_distingue_mayusculas(db):
    db.create_invite("GLX-AAAA-BBBB", max_uses=1, now=NOW)
    assert db.redeem_invite("glx-aaaa-bbbb", "hash-1") is True


def test_reingresar_no_consume_otro_uso(db):
    db.create_invite("GLX-AAAA-BBBB", max_uses=1, now=NOW)
    assert db.redeem_invite("GLX-AAAA-BBBB", "hash-1") is True
    assert db.redeem_invite("GLX-AAAA-BBBB", "hash-1") is True
    assert db.redeem_invite("GLX-AAAA-BBBB", "hash-2") is False


def test_codigo_invalido(db):
    assert db.redeem_invite("GLX-ZZZZ-ZZZZ", "hash-1") is False


def test_el_hash_de_miembro_depende_de_la_sal(db):
    uno = db.member_hash(123456, b"sal-a")
    otro = db.member_hash(123456, b"sal-b")
    assert uno != otro
    assert uno == db.member_hash(123456, b"sal-a")
    assert "123456" not in uno


def test_la_base_no_expone_ninguna_forma_de_borrar(db):
    borradores = [
        name
        for name in dir(db)
        if not name.startswith("_") and any(w in name for w in ("delete", "remove", "drop", "purge"))
    ]
    assert borradores == []


def test_migracion_es_idempotente(tmp_path):
    path = tmp_path / "twice.db"
    first = Database(path)
    add(first, *OBELISCO)
    first.close()
    second = Database(path)
    assert second.count_glitches() == 1
    second.close()
