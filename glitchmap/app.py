"""Armado y arranque del bot."""

from __future__ import annotations

import logging

from telegram import Update
from telegram.ext import Application

from .backup import backup_job, make_backup
from .config import Config
from .db import Database
from .handlers import generate_code, register

log = logging.getLogger(__name__)


def bootstrap_invite(db: Database) -> str | None:
    """Primer arranque: si la red está vacía, emite un código y lo deja en el log.

    Sin esto habría que tocar la base a mano para poder entrar la primera vez.
    """
    if db.count_members() or db.count_invites():
        return None
    code = generate_code()
    db.create_invite(code, max_uses=5)
    return code


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

    code = bootstrap_invite(db)
    if code:
        log.warning("PRIMER CÓDIGO DE ACCESO (usalo vos): %s", code)
    if not cfg.admin_ids:
        log.warning("ADMIN_IDS está vacío: nadie va a poder emitir códigos nuevos con /invitar")

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
    log.info("la grilla está en línea")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
