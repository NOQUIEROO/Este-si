"""Respaldos en caliente.

La base viva nunca se toca. Lo único que se poda son copias redundantes
viejas, y solo cuando ya hay BACKUP_KEEP copias más nuevas.
"""

from __future__ import annotations

import logging
import sqlite3
from pathlib import Path

from telegram.ext import ContextTypes

from .config import Config
from .db import Database, utcnow

log = logging.getLogger(__name__)


def make_backup(db: Database, cfg: Config) -> Path:
    """Copia consistente de la base, incluso con el bot en funcionamiento."""
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    dest = cfg.backup_dir / f"glitchmap-{stamp}.db"
    with db.lock:
        target = sqlite3.connect(dest)
        try:
            db.raw_connection().backup(target)
        finally:
            target.close()
    prune(cfg)
    return dest


def prune(cfg: Config) -> int:
    copies = sorted(cfg.backup_dir.glob("glitchmap-*.db"), reverse=True)
    removed = 0
    for stale in copies[cfg.backup_keep :]:
        try:
            stale.unlink()
            removed += 1
        except OSError:
            log.warning("no pude podar el respaldo %s", stale)
    return removed


async def backup_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    db: Database = context.application.bot_data["db"]
    cfg: Config = context.application.bot_data["cfg"]

    try:
        path = make_backup(db, cfg)
    except Exception:  # el respaldo nunca puede tumbar al bot
        log.exception("falló el respaldo automático")
        return

    log.info("respaldo escrito en %s", path)

    if cfg.backup_chat_id is None:
        return

    # Mandarlo a un chat es el respaldo fuera del servidor: si el disco muere,
    # la base sigue existiendo en Telegram.
    try:
        with path.open("rb") as handle:
            await context.bot.send_document(
                chat_id=cfg.backup_chat_id,
                document=handle,
                filename=path.name,
                caption=f"🗄 Respaldo de la grilla · {db.count_glitches()} anomalías",
                disable_notification=True,
            )
    except Exception:
        log.exception("no pude enviar el respaldo a BACKUP_CHAT_ID")
