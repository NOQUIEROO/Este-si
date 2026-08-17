"""Configuracion por variables de entorno.

Deliberadamente no comparte codigo con `glitchmap.config`: son dos bots que se
despliegan por separado, con su token, su base y su .env. Compartimos logica
(la geometria), no el pegamento.
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} tiene que ser un numero entero, no {raw!r}") from exc


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip().replace(",", ".")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} tiene que ser un numero, no {raw!r}") from exc


def _load_dotenv(path: Path) -> None:
    """Carga un .env sin dependencias extra. No pisa variables ya definidas."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _resolve_salt(data_dir: Path) -> bytes:
    """Sal del HMAC de anfitriones. Vive fuera de la base, a proposito."""
    from_env = os.environ.get("SECRET_SALT", "").strip()
    if from_env:
        return from_env.encode("utf-8")

    salt_file = data_dir / ".salt"
    if salt_file.is_file():
        return salt_file.read_bytes().strip()

    salt = secrets.token_hex(32).encode("ascii")
    salt_file.write_bytes(salt)
    try:
        salt_file.chmod(0o600)
    except OSError:  # sistemas de archivos sin permisos POSIX
        pass
    return salt


@dataclass(frozen=True)
class Config:
    token: str
    data_dir: Path
    db_path: Path
    backup_dir: Path
    admin_ids: frozenset[int]
    scan_radius_m: int
    scan_limit: int
    credito: float
    moneda: str
    backup_every_hours: int
    backup_keep: int
    backup_chat_id: int | None
    secret_salt: bytes

    def credito_texto(self, veces: int = 1) -> str:
        monto = self.credito * veces
        entero = int(monto)
        cuerpo = str(entero) if monto == entero else f"{monto:.2f}".replace(".", ",")
        return f"{self.moneda} {cuerpo}"

    @classmethod
    def from_env(cls, dotenv: Path | None = Path(".env.odd")) -> "Config":
        if dotenv is not None:
            _load_dotenv(dotenv)

        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            raise SystemExit(
                "Falta BOT_TOKEN. Copia .env.odd.example a .env.odd y pone el token de @BotFather."
            )

        data_dir = Path(os.environ.get("DATA_DIR", "./data-odd").strip() or "./data-odd")
        data_dir.mkdir(parents=True, exist_ok=True)
        backup_dir = data_dir / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        admin_ids = frozenset(
            int(part) for part in os.environ.get("ADMIN_IDS", "").replace(" ", "").split(",") if part
        )

        backup_chat_raw = os.environ.get("BACKUP_CHAT_ID", "").strip()

        return cls(
            token=token,
            data_dir=data_dir,
            db_path=data_dir / "oddbar.db",
            backup_dir=backup_dir,
            admin_ids=admin_ids,
            scan_radius_m=_int_env("SCAN_RADIUS_M", 2500),
            scan_limit=_int_env("SCAN_LIMIT", 6),
            credito=_float_env("CREDITO", 3),
            moneda=os.environ.get("MONEDA", "USD").strip() or "USD",
            backup_every_hours=_int_env("BACKUP_EVERY_HOURS", 6),
            backup_keep=_int_env("BACKUP_KEEP", 48),
            backup_chat_id=int(backup_chat_raw) if backup_chat_raw else None,
            secret_salt=_resolve_salt(data_dir),
        )
