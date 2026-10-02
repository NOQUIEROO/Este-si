from datetime import datetime, timezone
from pathlib import Path

import pytest

from odd.app import build_application
from odd.backup import make_backup, prune
from odd.config import Config
from odd.db import Database

FAKE_TOKEN = "123456:AAHfake-token-para-tests-solamente-000"
NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def make_config(tmp_path: Path, **overrides) -> Config:
    data_dir = tmp_path / "data-odd"
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    defaults = dict(
        token=FAKE_TOKEN,
        data_dir=data_dir,
        db_path=data_dir / "oddbar.db",
        backup_dir=backup_dir,
        admin_ids=frozenset({42}),
        scan_radius_m=2500,
        scan_limit=6,
        credito=3.0,
        moneda="USD",
        backup_every_hours=6,
        backup_keep=3,
        backup_chat_id=None,
        secret_salt=b"sal-de-prueba",
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_el_bot_se_arma_entero(tmp_path):
    """Smoke test: registra todos los handlers sin tocar la red."""
    application = build_application(make_config(tmp_path))
    assert len(application.handlers[0]) > 15
    assert application.bot_data["db"].count_bares() == 0


def test_el_credito_se_muestra_como_lo_lee_una_persona(tmp_path):
    cfg = make_config(tmp_path)
    assert cfg.credito_texto() == "USD 3"
    assert cfg.credito_texto(4) == "USD 12"
    assert make_config(tmp_path, credito=2.5).credito_texto() == "USD 2,50"
    assert make_config(tmp_path, moneda="ARS", credito=3000).credito_texto() == "ARS 3000"


def test_respaldo_copia_la_base_entera(tmp_path):
    cfg = make_config(tmp_path)
    db = Database(cfg.db_path)
    bar_id = db.alta_bar(alias="el bar", lat=-34.6, lon=-58.4, placa_lugar="bano", now=NOW)
    db.registrar_paso(
        bar_id=bar_id, foto="f", es_primera=True, contacto="hola@mail.com", credito=3.0, now=NOW
    )
    copia = make_backup(db, cfg)
    db.close()

    restaurada = Database(copia)
    assert restaurada.count_bares() == 1
    assert restaurada.get_paso(1).contacto == "hola@mail.com"
    restaurada.close()


def test_la_poda_solo_toca_copias_sobrantes(tmp_path):
    cfg = make_config(tmp_path, backup_keep=2)
    for nombre in (
        "oddbar-20260101-000000.db",
        "oddbar-20260102-000000.db",
        "oddbar-20260103-000000.db",
        "oddbar-20260104-000000.db",
    ):
        (cfg.backup_dir / nombre).write_bytes(b"x")
    assert prune(cfg) == 2
    quedan = sorted(p.name for p in cfg.backup_dir.glob("*.db"))
    assert quedan == ["oddbar-20260103-000000.db", "oddbar-20260104-000000.db"]


def test_la_poda_no_toca_los_respaldos_del_otro_bot(tmp_path):
    """Las dos bases pueden convivir en un mismo disco sin pisarse."""
    cfg = make_config(tmp_path, backup_keep=1)
    (cfg.backup_dir / "glitchmap-20260101-000000.db").write_bytes(b"x")
    (cfg.backup_dir / "oddbar-20260101-000000.db").write_bytes(b"x")
    (cfg.backup_dir / "oddbar-20260102-000000.db").write_bytes(b"x")
    assert prune(cfg) == 1
    assert (cfg.backup_dir / "glitchmap-20260101-000000.db").is_file()


def test_la_sal_se_genera_sola_y_persiste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data-odd"))
    monkeypatch.delenv("SECRET_SALT", raising=False)

    primera = Config.from_env(dotenv=None)
    segunda = Config.from_env(dotenv=None)
    assert primera.secret_salt == segunda.secret_salt
    assert (tmp_path / "data-odd" / ".salt").is_file()


def test_falta_el_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_TOKEN", "")
    with pytest.raises(SystemExit):
        Config.from_env(dotenv=None)
