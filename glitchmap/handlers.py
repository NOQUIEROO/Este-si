"""Los flujos del bot.

Dos caminos, nada más: escanear la grilla y registrar una anomalía. Todo lo
demás son botones sobre esos dos.
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from dataclasses import replace

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from . import lexicon as lx
from .backup import make_backup
from .config import Config
from .db import Database, utcnow
from .geo import format_distance, haversine_m
from .stability import COLLAPSE, CONFIRM

log = logging.getLogger(__name__)

ASK_LOC, ASK_ALIAS, ASK_COVER, ASK_NOISE, ASK_WINDOW, ASK_NOTE = range(6)

MAX_ALIAS = 40
MAX_NOTE = 200
MAX_RADIUS_M = 50_000

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin I/O/0/1
CODE_RE = re.compile(r"\bGLX[- ]?([A-Z0-9]{4})[- ]?([A-Z0-9]{4})\b", re.IGNORECASE)

# Caracteres que rompen el Markdown de Telegram. Se limpian al guardar, así la
# base queda con texto plano y ningún mensaje puede salir deformado.
UNSAFE_MARKDOWN = str.maketrans({c: None for c in "*_`[]()"})


def generate_code() -> str:
    chunk = lambda: "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    return f"GLX-{chunk()}-{chunk()}"


def normalize_code(text: str) -> str | None:
    match = CODE_RE.search(text or "")
    if not match:
        return None
    return f"GLX-{match.group(1).upper()}-{match.group(2).upper()}"


def sanitize(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").translate(UNSAFE_MARKDOWN).split())
    return cleaned[:limit].strip()


class Limiter:
    """Límite de frecuencia en memoria. Se pierde al reiniciar, a propósito:
    en disco no queda ni un rastro de quién hizo qué."""

    def __init__(self, limit: int, window_s: float) -> None:
        self.limit = limit
        self.window_s = window_s
        self._events: dict[int, list[float]] = {}

    def allow(self, key: int) -> bool:
        now = time.monotonic()
        bucket = [t for t in self._events.get(key, []) if now - t < self.window_s]
        if len(bucket) >= self.limit:
            self._events[key] = bucket
            return False
        bucket.append(now)
        self._events[key] = bucket
        return True


class Dedupe:
    """Evita que la misma persona infle una anomalía a fuerza de confirmarla.
    También en memoria."""

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self._seen: dict[tuple[int, int], float] = {}

    def allow(self, user_id: int, glitch_id: int) -> bool:
        now = time.monotonic()
        key = (user_id, glitch_id)
        last = self._seen.get(key)
        if last is not None and now - last < self.window_s:
            return False
        self._seen[key] = now
        return True


REPORT_LIMITER = Limiter(limit=6, window_s=3600)
SIGNAL_LIMITER = Limiter(limit=30, window_s=3600)
SIGNAL_DEDUPE = Dedupe(window_s=12 * 3600)


# --------------------------------------------------------------- teclados


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[lx.BTN_SCAN], [lx.BTN_REPORT, lx.BTN_MANUAL]],
        resize_keyboard=True,
    )


def location_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(lx.BTN_LOCATION, request_location=True)], [lx.BTN_CANCEL]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def choice_keyboard(labels, *, with_skip: bool = False) -> ReplyKeyboardMarkup:
    rows = [[label] for label in labels]
    rows.append([lx.BTN_SKIP, lx.BTN_CANCEL] if with_skip else [lx.BTN_CANCEL])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True, one_time_keyboard=True)


# ------------------------------------------------------------------ puerta


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["cfg"]


async def gate(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Corre antes que todo. Si la persona no está en la red, no pasa nada más.

    Registrado en el grupo -1: si devuelve normalmente, el update sigue su
    curso; si levanta ApplicationHandlerStop, se corta acá.
    """
    user = update.effective_user
    if user is None:
        raise ApplicationHandlerStop

    db, cfg = _db(context), _cfg(context)
    member_hash = db.member_hash(user.id, cfg.secret_salt)
    if db.is_member(member_hash):
        return

    # Los admins entran solos: si no, nadie podría emitir el primer código.
    if user.id in cfg.admin_ids:
        db.ensure_member(member_hash)
        return

    if update.callback_query is not None:
        await update.callback_query.answer("Acceso restringido a la grilla.", show_alert=True)
        raise ApplicationHandlerStop

    message = update.effective_message
    if message is None:
        raise ApplicationHandlerStop

    code = normalize_code(message.text or "")
    if code and db.redeem_invite(code, member_hash):
        await message.reply_text(lx.GRANTED, parse_mode=ParseMode.MARKDOWN)
        await message.reply_text(
            lx.WELCOME, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard()
        )
        raise ApplicationHandlerStop

    await message.reply_text(
        lx.BAD_CODE if code else lx.LOCKED,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardRemove(),
    )
    raise ApplicationHandlerStop


# ------------------------------------------------------------------ básicos


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        lx.WELCOME, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard()
    )


async def cmd_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        lx.MANUAL, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard()
    )


async def cmd_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(lx.PRIVACY, parse_mode=ParseMode.MARKDOWN)


# ------------------------------------------------------------------ escaneo


async def ask_scan_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        lx.ASK_LOCATION_SCAN, reply_markup=location_keyboard()
    )


async def on_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Una ubicación fuera del registro siempre significa: escaneá acá."""
    location = update.effective_message.location
    context.user_data["pos"] = (location.latitude, location.longitude)
    await run_scan(update, context, radius_m=_cfg(context).scan_radius_m)


async def run_scan(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    radius_m: int,
    include_faded: bool = False,
    edit: bool = False,
) -> None:
    position = context.user_data.get("pos")
    if position is None:
        await ask_scan_location(update, context)
        return

    lat, lon = position
    db, cfg = _db(context), _cfg(context)
    now = utcnow()
    results = db.nearby(lat, lon, radius_m, cfg.scan_limit, include_faded, now)

    buttons: list[list[InlineKeyboardButton]] = []
    if results:
        header = (
            f"📡 *{len(results)} anomalía{'s' if len(results) > 1 else ''}* "
            f"en un radio de {format_distance(radius_m)}"
        )
        body = "\n\n".join(lx.render_row(i, g) for i, g in enumerate(results, start=1))
        text = f"{header}\n\n{body}\n\n_Tocá un número para ver la ficha._"
        buttons.append(
            [
                InlineKeyboardButton(str(i), callback_data=f"g:{g.id}")
                for i, g in enumerate(results, start=1)
            ]
        )
    else:
        text = lx.NOTHING_NEARBY.format(radius=format_distance(radius_m))

    extra: list[InlineKeyboardButton] = []
    if radius_m < MAX_RADIUS_M:
        wider = min(MAX_RADIUS_M, radius_m * 2)
        extra.append(
            InlineKeyboardButton(
                f"🔭 Ampliar a {format_distance(wider)}",
                callback_data=f"scan:{wider}:{int(include_faded)}",
            )
        )
    if not include_faded:
        extra.append(
            InlineKeyboardButton("👻 Incluir desvanecidas", callback_data=f"scan:{radius_m}:1")
        )
    if extra:
        buttons.append(extra)

    markup = InlineKeyboardMarkup(buttons) if buttons else None

    if edit and update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(
                text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
            )
            return
        except BadRequest as exc:  # mismo contenido: no hay nada que editar
            if "not modified" not in str(exc).lower():
                raise
            return

    # Telegram no deja combinar botones inline con el teclado del menú en un
    # mismo mensaje: primero devolvemos el menú, después los resultados.
    await update.effective_message.reply_text(
        "▚ Barrido completo.", reply_markup=main_keyboard(), disable_notification=True
    )
    await update.effective_message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
    )


async def on_scan_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, radius_raw, faded_raw = query.data.split(":")
    await run_scan(
        update,
        context,
        radius_m=int(radius_raw),
        include_faded=bool(int(faded_raw)),
        edit=True,
    )


def _with_distance(glitch, context: ContextTypes.DEFAULT_TYPE):
    """Agrega la distancia si sabemos dónde está parada la persona."""
    position = context.user_data.get("pos")
    if position is None:
        return glitch
    return replace(
        glitch, distance_m=haversine_m(position[0], position[1], glitch.lat, glitch.lon)
    )


def detail_keyboard(glitch_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Sigue activa", callback_data=f"s:{glitch_id}:{CONFIRM}"),
                InlineKeyboardButton("⚠️ Colapsó", callback_data=f"s:{glitch_id}:{COLLAPSE}"),
            ]
        ]
    )


async def on_detail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    glitch_id = int(query.data.split(":")[1])
    glitch = _db(context).get_glitch(glitch_id)
    if glitch is None:
        await query.message.reply_text("Esa anomalía ya no está en la grilla.")
        return

    glitch = _with_distance(glitch, context)

    await query.message.reply_text(
        lx.render_card(glitch, utcnow()),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=detail_keyboard(glitch_id),
        disable_web_page_preview=True,
    )


async def on_signal(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    _, raw_id, kind = query.data.split(":")
    glitch_id = int(raw_id)
    user_id = update.effective_user.id

    if not SIGNAL_LIMITER.allow(user_id):
        await query.answer(lx.RATE_LIMITED, show_alert=True)
        return
    if not SIGNAL_DEDUPE.allow(user_id, glitch_id):
        await query.answer(lx.ALREADY_SIGNALED, show_alert=True)
        return

    db = _db(context)
    db.add_signal(glitch_id, kind)
    await query.answer(lx.CONFIRMED if kind == CONFIRM else lx.COLLAPSED)

    glitch = db.get_glitch(glitch_id)
    if glitch is None:
        return
    glitch = _with_distance(glitch, context)
    try:
        await query.edit_message_text(
            lx.render_card(glitch, utcnow()),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=detail_keyboard(glitch_id),
            disable_web_page_preview=True,
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


# ---------------------------------------------------------------- registro


async def report_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not REPORT_LIMITER.allow(update.effective_user.id):
        await update.effective_message.reply_text(
            lx.RATE_LIMITED, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard()
        )
        return ConversationHandler.END

    context.user_data["draft"] = {}
    await update.effective_message.reply_text(
        lx.ASK_LOCATION_REPORT, parse_mode=ParseMode.MARKDOWN, reply_markup=location_keyboard()
    )
    return ASK_LOC


async def report_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location = update.effective_message.location
    context.user_data["draft"]["lat"] = location.latitude
    context.user_data["draft"]["lon"] = location.longitude
    await update.effective_message.reply_text(
        lx.ASK_ALIAS,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup([[lx.BTN_CANCEL]], resize_keyboard=True),
    )
    return ASK_ALIAS


async def report_alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    alias = sanitize(update.effective_message.text, MAX_ALIAS)
    if not alias:
        await update.effective_message.reply_text("Necesito un nombre, aunque sea corto.")
        return ASK_ALIAS
    context.user_data["draft"]["alias"] = alias
    await update.effective_message.reply_text(
        lx.ASK_COVER, reply_markup=choice_keyboard(lx.COBERTURA_BUTTONS)
    )
    return ASK_COVER


async def report_cover(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    key = lx.COBERTURA_BUTTONS.get(update.effective_message.text)
    if key is None:
        await update.effective_message.reply_text(
            "Elegí una de las opciones.", reply_markup=choice_keyboard(lx.COBERTURA_BUTTONS)
        )
        return ASK_COVER
    context.user_data["draft"]["cobertura"] = key
    await update.effective_message.reply_text(
        lx.ASK_NOISE, reply_markup=choice_keyboard(lx.INTERFERENCIA_BUTTONS)
    )
    return ASK_NOISE


async def report_noise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    key = lx.INTERFERENCIA_BUTTONS.get(update.effective_message.text)
    if key is None:
        await update.effective_message.reply_text(
            "Elegí una de las opciones.", reply_markup=choice_keyboard(lx.INTERFERENCIA_BUTTONS)
        )
        return ASK_NOISE
    context.user_data["draft"]["interferencia"] = key
    await update.effective_message.reply_text(
        lx.ASK_WINDOW, reply_markup=choice_keyboard(lx.VENTANA_BUTTONS)
    )
    return ASK_WINDOW


async def report_window(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    key = lx.VENTANA_BUTTONS.get(update.effective_message.text)
    if key is None:
        await update.effective_message.reply_text(
            "Elegí una de las opciones.", reply_markup=choice_keyboard(lx.VENTANA_BUTTONS)
        )
        return ASK_WINDOW
    context.user_data["draft"]["ventana"] = key
    await update.effective_message.reply_text(
        lx.ASK_NOTE,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup(
            [[lx.BTN_SKIP], [lx.BTN_CANCEL]], resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return ASK_NOTE


async def report_note(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.effective_message.text or ""
    note = None if text == lx.BTN_SKIP else (sanitize(text, MAX_NOTE) or None)
    draft = context.user_data.get("draft", {})
    draft["nota"] = note
    return await report_save(update, context, draft)


async def report_save(update: Update, context: ContextTypes.DEFAULT_TYPE, draft: dict) -> int:
    db = _db(context)
    glitch_id = db.add_glitch(
        alias=draft["alias"],
        lat=draft["lat"],
        lon=draft["lon"],
        cobertura=draft["cobertura"],
        interferencia=draft["interferencia"],
        ventana=draft["ventana"],
        nota=draft.get("nota"),
    )
    context.user_data.pop("draft", None)

    await update.effective_message.reply_text(
        lx.SAVED, parse_mode=ParseMode.MARKDOWN, reply_markup=main_keyboard()
    )
    glitch = db.get_glitch(glitch_id)
    if glitch is not None:
        await update.effective_message.reply_text(
            lx.render_card(glitch, utcnow()),
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
        )
    return ConversationHandler.END


async def report_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("draft", None)
    await update.effective_message.reply_text(lx.CANCELLED, reply_markup=main_keyboard())
    return ConversationHandler.END


async def report_expected_location(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.effective_message.reply_text(
        "Para anclar la anomalía necesito el punto. Tocá el botón, o mandame un "
        "pin del mapa (📎 → Ubicación).",
        reply_markup=location_keyboard(),
    )
    return ASK_LOC


# --------------------------------------------------------------------- admin


def admin_only(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.effective_user.id not in _cfg(context).admin_ids:
            return
        await handler(update, context)

    return wrapper


@admin_only
async def cmd_invite(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    uses = 1
    if context.args:
        try:
            uses = max(1, min(500, int(context.args[0])))
        except ValueError:
            uses = 1

    code = generate_code()
    _db(context).create_invite(code, uses)
    username = context.bot.username
    link = f"https://t.me/{username}?start={code}" if username else "(link no disponible)"
    await update.effective_message.reply_text(
        f"🎟 Código nuevo: `{code}`\nUsos: {uses}\n\n{link}",
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


@admin_only
async def cmd_census(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    stats = _db(context).stats()
    await update.effective_message.reply_text(
        "📊 *Estado de la grilla*\n"
        f"Anomalías: {stats['glitches']}\n"
        f"Visibles: {stats['visibles']}\n"
        f"Desvanecidas: {stats['desvanecidos']}\n"
        f"Señales: {stats['senales']}\n"
        f"Miembros: {stats['miembros']}",
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cmd_backup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    path = make_backup(_db(context), _cfg(context))
    with path.open("rb") as handle:
        await update.effective_message.reply_document(
            document=handle, filename=path.name, caption="🗄 Respaldo manual"
        )


# ------------------------------------------------------------------ errores


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("error procesando un update", exc_info=context.error)


def build_conversation() -> ConversationHandler:
    cancel_filter = filters.Regex(f"^{re.escape(lx.BTN_CANCEL)}$")
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_REPORT)}$"), report_start),
            CommandHandler("registrar", report_start),
        ],
        states={
            ASK_LOC: [
                MessageHandler(filters.LOCATION, report_location),
                MessageHandler(~cancel_filter & ~filters.COMMAND, report_expected_location),
            ],
            ASK_ALIAS: [MessageHandler(filters.TEXT & ~cancel_filter & ~filters.COMMAND, report_alias)],
            ASK_COVER: [MessageHandler(filters.TEXT & ~cancel_filter & ~filters.COMMAND, report_cover)],
            ASK_NOISE: [MessageHandler(filters.TEXT & ~cancel_filter & ~filters.COMMAND, report_noise)],
            ASK_WINDOW: [MessageHandler(filters.TEXT & ~cancel_filter & ~filters.COMMAND, report_window)],
            ASK_NOTE: [MessageHandler(filters.TEXT & ~cancel_filter & ~filters.COMMAND, report_note)],
        },
        fallbacks=[
            MessageHandler(cancel_filter, report_cancel),
            CommandHandler("cancelar", report_cancel),
        ],
        allow_reentry=True,
    )


def register(application) -> None:
    application.add_handler(MessageHandler(filters.ALL, gate), group=-1)
    application.add_handler(CallbackQueryHandler(gate), group=-1)

    application.add_handler(build_conversation())

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("manual", cmd_manual))
    application.add_handler(CommandHandler("ayuda", cmd_manual))
    application.add_handler(CommandHandler("privacidad", cmd_privacy))
    application.add_handler(CommandHandler("escanear", ask_scan_location))
    application.add_handler(CommandHandler("invitar", cmd_invite))
    application.add_handler(CommandHandler("censo", cmd_census))
    application.add_handler(CommandHandler("respaldo", cmd_backup))

    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_SCAN)}$"), ask_scan_location))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_MANUAL)}$"), cmd_manual))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_CANCEL)}$"), cmd_start))
    application.add_handler(MessageHandler(filters.LOCATION, on_location))

    application.add_handler(CallbackQueryHandler(on_scan_callback, pattern=r"^scan:"))
    application.add_handler(CallbackQueryHandler(on_detail, pattern=r"^g:"))
    application.add_handler(CallbackQueryHandler(on_signal, pattern=r"^s:"))

    application.add_error_handler(on_error)
