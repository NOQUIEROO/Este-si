from pathlib import Path

import pytest

from glitchmap.app import bootstrap_invite, build_application
from glitchmap.backup import make_backup, prune
from glitchmap.config import Config
from glitchmap.db import Database
from glitchmap.handlers import normalize_code

FAKE_TOKEN = "123456:AAHfake-token-para-tests-solamente-000"


def make_config(tmp_path: Path, **overrides) -> Config:
    data_dir = tmp_path / "data"
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    defaults = dict(
        token=FAKE_TOKEN,
        data_dir=data_dir,
        db_path=data_dir / "glitchmap.db",
        backup_dir=backup_dir,
        admin_ids=frozenset({42}),
        scan_radius_m=3000,
        scan_limit=5,
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
    grupos = application.handlers
    assert grupos[-1], "la puerta tiene que estar en el grupo -1"
    assert len(grupos[0]) > 10
    assert application.bot_data["db"].count_glitches() == 0


def test_el_primer_arranque_emite_un_codigo(tmp_path):
    db = Database(tmp_path / "a.db")
    code = bootstrap_invite(db)
    assert code and normalize_code(code) == code
    assert db.redeem_invite(code, "hash-1") is True
    # Con la red ya poblada no vuelve a emitir nada.
    assert bootstrap_invite(db) is None
    db.close()


def test_respaldo_copia_la_base_entera(tmp_path):
    cfg = make_config(tmp_path)
    db = Database(cfg.db_path)
    db.add_glitch(
        alias="punto",
        lat=-34.6,
        lon=-58.4,
        cobertura="techo",
        interferencia="baja",
        ventana="noche",
        nota=None,
    )
    copia = make_backup(db, cfg)
    db.close()

    restaurada = Database(copia)
    assert restaurada.count_glitches() == 1
    restaurada.close()


def test_la_poda_solo_toca_copias_sobrantes(tmp_path):
    cfg = make_config(tmp_path, backup_keep=2)
    for name in ("glitchmap-20260101-000000.db", "glitchmap-20260102-000000.db",
                 "glitchmap-20260103-000000.db", "glitchmap-20260104-000000.db"):
        (cfg.backup_dir / name).write_bytes(b"x")
    assert prune(cfg) == 2
    quedan = sorted(p.name for p in cfg.backup_dir.glob("*.db"))
    assert quedan == ["glitchmap-20260103-000000.db", "glitchmap-20260104-000000.db"]


def test_la_sal_se_genera_sola_y_persiste(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_TOKEN", FAKE_TOKEN)
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.delenv("SECRET_SALT", raising=False)

    primera = Config.from_env(dotenv=None)
    segunda = Config.from_env(dotenv=None)
    assert primera.secret_salt == segunda.secret_salt
    assert (tmp_path / "data" / ".salt").is_file()


def test_falta_el_token(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_TOKEN", "")
    with pytest.raises(SystemExit):
        Config.from_env(dotenv=None)
