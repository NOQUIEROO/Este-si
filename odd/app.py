"""Armado y arranque del bot de ODD."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application

from .backup import backup_job, make_backup
from .config import Config
from .db import Database
from .handlers import register

log = logging.getLogger(__name__)


def build_application(cfg: Config | None = None) -> Application:
    cfg = cfg or Config.from_env()
    db = Database(cfg.db_path)

    application = Application.builder().token(cfg.token).build()
    application.bot_data["db"] = db
    application.bot_data["cfg"] = cfg
    register(application)

    if application.job_queue is not None:
        application.job_queue.run_repeating(
            backup_job,
            interval=cfg.backup_every_hours * 3600,
            first=60,
            name="respaldo",
        )
    else:  # sin el extra [job-queue] instalado
        log.warning("job queue no disponible: no va a haber respaldos automáticos")

    if not cfg.admin_ids:
        log.warning(
            "ADMIN_IDS está vacío: nadie va a poder dar de alta bares ni leer reflexiones"
        )
    elif not db.count_bares():
        log.warning("todavía no hay ningún bar: empezá mandándole /altabar al bot")

    # Un respaldo apenas arranca, antes de aceptar cualquier escritura nueva.
    try:
        make_backup(db, cfg)
    except Exception:
        log.exception("no pude hacer el respaldo de arranque")

    return application


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s | %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    application = build_application()
    log.info("ODD en línea")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
