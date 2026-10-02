"""Los flujos del bot.

Hay tres personas del otro lado y el bot es distinto para cada una:

    el que camina  -> busca bares cerca y entiende el trato
    el que atiende -> carga la reflexión que le acaba de dejar alguien
    nosotros       -> damos de alta bares, numeramos placas y leemos reflexiones

Nadie tiene que elegir su rol: el bot lo deduce. Un dueño de bar se vuelve
dueño de bar canjeando el código que le dimos, y de ahí en más ve otro menú.
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
    Update,
)
from telegram.constants import ParseMode
from telegram.error import BadRequest, TelegramError
from telegram.ext import (
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

from glitchmap.geo import format_distance, haversine_m, map_url

from . import lexicon as lx
from .backup import make_backup
from .config import Config
from .db import ANFITRION, LUGARES_PLACA, NOMINACION, Database, utcnow
from .estado import (
    ASIGNADA,
    COMUN,
    ENVIADA,
    ESPECIAL,
    INSTALADA,
    PAUSA,
    REACTIVACION,
    RETIRO,
)

log = logging.getLogger(__name__)

# Estados de las tres conversaciones.
PASO_FOTO, PASO_PRIMERA, PASO_CONTACTO = range(3)
ALTA_UBICACION, ALTA_ALIAS, ALTA_DIRECCION, ALTA_PLACA, ALTA_NOTA = range(3, 8)
NOM_UBICACION, NOM_ALIAS, NOM_MOTIVO = range(8, 11)

MAX_ALIAS = 60
MAX_DIRECCION = 120
MAX_NOTA = 200
MAX_CONTACTO = 120
MAX_MOTIVO = 400
MAX_RADIUS_M = 25_000

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sin I/O/0/1
CODE_RE = re.compile(r"\bODD[- ]?([A-Z0-9]{4})[- ]?([A-Z0-9]{4})\b", re.IGNORECASE)
SOLO_NUMERO_RE = re.compile(r"^\s*#?\s*(\d{1,6})\s*$")

# Caracteres que rompen el Markdown de Telegram. Se limpian al guardar, así la
# base queda con texto plano y ningún mensaje puede salir deformado.
UNSAFE_MARKDOWN = str.maketrans({c: None for c in "*_`[]()"})


def generate_code() -> str:
    chunk = lambda: "".join(secrets.choice(CODE_ALPHABET) for _ in range(4))
    return f"ODD-{chunk()}-{chunk()}"


def normalize_code(text: str) -> str | None:
    match = CODE_RE.search(text or "")
    if not match:
        return None
    return f"ODD-{match.group(1).upper()}-{match.group(2).upper()}"


def sanitize(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").translate(UNSAFE_MARKDOWN).split())
    return cleaned[:limit].strip()


class Limiter:
    """Límite de frecuencia en memoria. Se pierde al reiniciar, a propósito."""

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


# Un bar que carga más de 40 reflexiones en una hora está haciendo otra cosa.
PASO_LIMITER = Limiter(limit=40, window_s=3600)


# ------------------------------------------------------------------ contexto


def _db(context: ContextTypes.DEFAULT_TYPE) -> Database:
    return context.application.bot_data["db"]


def _cfg(context: ContextTypes.DEFAULT_TYPE) -> Config:
    return context.application.bot_data["cfg"]


def _es_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    return user is not None and user.id in _cfg(context).admin_ids


def _bar_del_anfitrion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """El bar que administra quien está escribiendo, si administra alguno."""
    user = update.effective_user
    if user is None:
        return None
    db, cfg = _db(context), _cfg(context)
    return db.bar_de_anfitrion(db.host_hash(user.id, cfg.secret_salt))


def admin_only(handler):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not _es_admin(update, context):
            return
        await handler(update, context)

    return wrapper


# ------------------------------------------------------------------ teclados


def menu_visitante() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[lx.BTN_CERCA], [lx.BTN_TRATO, lx.BTN_PLACA]], resize_keyboard=True
    )


def menu_anfitrion() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[lx.BTN_PASO], [lx.BTN_MIBAR, lx.BTN_TRATO]], resize_keyboard=True
    )


def menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> ReplyKeyboardMarkup:
    return menu_anfitrion() if _bar_del_anfitrion(update, context) else menu_visitante()


def teclado_ubicacion() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [[KeyboardButton(lx.BTN_UBICACION, request_location=True)], [lx.BTN_CANCEL]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def teclado_opciones(etiquetas, *, con_skip: bool = False) -> ReplyKeyboardMarkup:
    filas = [[etiqueta] for etiqueta in etiquetas]
    filas.append([lx.BTN_SKIP, lx.BTN_CANCEL] if con_skip else [lx.BTN_CANCEL])
    return ReplyKeyboardMarkup(filas, resize_keyboard=True, one_time_keyboard=True)


# ------------------------------------------------------------------- básicos


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg(context)
    bar_id = _bar_del_anfitrion(update, context)
    if bar_id is not None:
        bar = _db(context).get_bar(bar_id)
        texto = lx.WELCOME_ANFITRION.format(
            alias=bar.alias if bar else "tu bar", credito=cfg.credito_texto()
        )
        await update.effective_message.reply_text(
            texto, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_anfitrion()
        )
        return

    await update.effective_message.reply_text(
        lx.WELCOME.format(credito=cfg.credito_texto()),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_visitante(),
    )


async def cmd_trato(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        lx.TRATO.format(credito=_cfg(context).credito_texto(), btn_placa=lx.BTN_PLACA),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu(update, context),
    )


async def cmd_privacidad(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(lx.PRIVACY, parse_mode=ParseMode.MARKDOWN)


# -------------------------------------------------------------------- buscar


async def pedir_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        lx.ASK_UBICACION, parse_mode=ParseMode.MARKDOWN, reply_markup=teclado_ubicacion()
    )


async def on_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Una ubicación suelta siempre significa: buscá bares acá."""
    location = update.effective_message.location
    context.user_data["pos"] = (location.latitude, location.longitude)
    await buscar(update, context, radio_m=_cfg(context).scan_radius_m)


async def buscar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    radio_m: int,
    editar: bool = False,
) -> None:
    posicion = context.user_data.get("pos")
    if posicion is None:
        await pedir_ubicacion(update, context)
        return

    lat, lon = posicion
    db, cfg = _db(context), _cfg(context)
    encontrados = db.cerca(lat, lon, radio_m, cfg.scan_limit)

    botones: list[list[InlineKeyboardButton]] = []
    if encontrados:
        cabeza = (
            f"⬛️ *{len(encontrados)} bar{'es' if len(encontrados) > 1 else ''} de la red* "
            f"a menos de {format_distance(radio_m)}"
        )
        cuerpo = "\n\n".join(
            lx.render_fila(i, bar) for i, bar in enumerate(encontrados, start=1)
        )
        texto = f"{cabeza}\n\n{cuerpo}\n\n_Tocá un número para ver la ficha._"
        botones.append(
            [
                InlineKeyboardButton(str(i), callback_data=f"b:{bar.id}")
                for i, bar in enumerate(encontrados, start=1)
            ]
        )
    else:
        texto = lx.SIN_BARES.format(radio=format_distance(radio_m))

    if radio_m < MAX_RADIUS_M:
        mas = min(MAX_RADIUS_M, radio_m * 2)
        botones.append(
            [
                InlineKeyboardButton(
                    f"🔭 Buscar hasta {format_distance(mas)}", callback_data=f"cerca:{mas}"
                )
            ]
        )

    markup = InlineKeyboardMarkup(botones) if botones else None

    if editar and update.callback_query is not None:
        try:
            await update.callback_query.edit_message_text(
                texto, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
            )
        except BadRequest as exc:  # mismo contenido: no hay nada que editar
            if "not modified" not in str(exc).lower():
                raise
        return

    # Telegram no deja combinar botones inline con el teclado del menú en un
    # mismo mensaje: primero devolvemos el menú, después los resultados.
    await update.effective_message.reply_text(
        "Buscando…", reply_markup=menu(update, context), disable_notification=True
    )
    await update.effective_message.reply_text(
        texto, parse_mode=ParseMode.MARKDOWN, reply_markup=markup
    )


async def on_buscar_mas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await buscar(update, context, radio_m=int(query.data.split(":")[1]), editar=True)


async def on_ficha(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    bar = _db(context).get_bar(int(query.data.split(":")[1]))
    if bar is None:
        await query.message.reply_text("Ese bar ya no está en la red.")
        return

    posicion = context.user_data.get("pos")
    if posicion is not None:
        bar = replace(bar, distance_m=haversine_m(posicion[0], posicion[1], bar.lat, bar.lon))

    await query.message.reply_text(
        lx.render_bar(bar, utcnow()),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------ verificar placa


async def pedir_placa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(lx.ASK_PLACA, reply_markup=menu(update, context))


async def on_numero_suelto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Un mensaje que es solo un número siempre significa: chequeá esta placa."""
    match = SOLO_NUMERO_RE.match(update.effective_message.text or "")
    if match is None:
        return
    await responder_placa(update, context, int(match.group(1)))


async def cmd_placa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args or not context.args[0].lstrip("#").isdigit():
        await pedir_placa(update, context)
        return
    await responder_placa(update, context, int(context.args[0].lstrip("#")))


async def responder_placa(
    update: Update, context: ContextTypes.DEFAULT_TYPE, numero: int
) -> None:
    placa = _db(context).get_placa(numero)
    if placa is None:
        texto = lx.PLACA_DESCONOCIDA.format(numero=numero)
    else:
        texto = lx.render_placa(placa.numero, placa.estado, placa.bar_alias)
    await update.effective_message.reply_text(
        texto, parse_mode=ParseMode.MARKDOWN, reply_markup=menu(update, context)
    )


# --------------------------------------------------------------- códigos


async def on_codigo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Puerta de entrada de los dos códigos que existen.

    Es el punto de entrada de la conversación de nominación porque un código
    especial *arranca* esa charla; un código de anfitrión se resuelve acá
    mismo y la conversación termina antes de empezar.
    """
    code = normalize_code(update.effective_message.text or "")
    db = _db(context)
    codigo = db.validar_codigo(code) if code else None

    if codigo is None:
        await update.effective_message.reply_text(
            lx.BAD_CODE, reply_markup=menu(update, context)
        )
        return ConversationHandler.END

    if codigo.rol == ANFITRION:
        if codigo.bar_id is None or not db.consumir_codigo(codigo.id):
            await update.effective_message.reply_text(lx.BAD_CODE)
            return ConversationHandler.END
        cfg = _cfg(context)
        db.vincular_anfitrion(db.host_hash(update.effective_user.id, cfg.secret_salt), codigo.bar_id)
        bar = db.get_bar(codigo.bar_id)
        await update.effective_message.reply_text(
            lx.ANFITRION_LISTO.format(alias=bar.alias if bar else "tu bar"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=menu_anfitrion(),
        )
        return ConversationHandler.END

    # Código de nominación: empieza la charla para elegir un bar nuevo.
    context.user_data["nominacion"] = {"codigo_id": codigo.id, "paso_id": codigo.paso_id}
    await update.effective_message.reply_text(
        lx.NOMINAR_BIENVENIDA, parse_mode=ParseMode.MARKDOWN
    )
    await update.effective_message.reply_text(
        lx.ASK_NOMINACION_UBICACION, reply_markup=teclado_ubicacion()
    )
    return NOM_UBICACION


async def nominar_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location = update.effective_message.location
    context.user_data["nominacion"]["lat"] = location.latitude
    context.user_data["nominacion"]["lon"] = location.longitude
    await update.effective_message.reply_text(
        lx.ASK_NOMINACION_ALIAS,
        reply_markup=ReplyKeyboardMarkup([[lx.BTN_CANCEL]], resize_keyboard=True),
    )
    return NOM_ALIAS


async def nominar_alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    alias = sanitize(update.effective_message.text, MAX_ALIAS)
    if not alias:
        await update.effective_message.reply_text("Necesito el nombre del lugar.")
        return NOM_ALIAS
    context.user_data["nominacion"]["alias"] = alias
    await update.effective_message.reply_text(
        lx.ASK_NOMINACION_MOTIVO,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup([[lx.BTN_CANCEL]], resize_keyboard=True),
    )
    return NOM_MOTIVO


async def nominar_motivo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    borrador = context.user_data.get("nominacion", {})
    motivo = sanitize(update.effective_message.text, MAX_MOTIVO) or None
    db = _db(context)

    # El código se gasta recién ahora: si abandonaron a la mitad, sigue sirviendo.
    if not db.consumir_codigo(borrador["codigo_id"]):
        await update.effective_message.reply_text(lx.BAD_CODE, reply_markup=menu_visitante())
        context.user_data.pop("nominacion", None)
        return ConversationHandler.END

    nominacion_id = db.crear_nominacion(
        alias=borrador["alias"],
        lat=borrador["lat"],
        lon=borrador["lon"],
        motivo=motivo,
        paso_id=borrador.get("paso_id"),
    )
    context.user_data.pop("nominacion", None)

    await update.effective_message.reply_text(
        lx.NOMINACION_GUARDADA.format(alias=borrador["alias"]),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_visitante(),
    )
    await avisar_admins(
        context,
        f"✨ Propuesta nueva #{nominacion_id}: *{borrador['alias']}*\n"
        f"_{motivo or 'sin motivo'}_\n\nMirala con /propuestas",
    )
    return ConversationHandler.END


async def nominar_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("nominacion", None)
    await update.effective_message.reply_text(
        "Listo. El código te sigue sirviendo cuando quieras usarlo.",
        reply_markup=menu_visitante(),
    )
    return ConversationHandler.END


# ------------------------------------------------------- cargar una reflexión


async def paso_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    bar_id = _bar_del_anfitrion(update, context)
    if bar_id is None:
        await update.effective_message.reply_text(
            lx.LOCKED_ANFITRION, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_visitante()
        )
        return ConversationHandler.END

    if not PASO_LIMITER.allow(bar_id):
        await update.effective_message.reply_text(lx.RATE_LIMITED, reply_markup=menu_anfitrion())
        return ConversationHandler.END

    context.user_data["paso"] = {"bar_id": bar_id}
    await update.effective_message.reply_text(
        lx.ASK_FOTO,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=ReplyKeyboardMarkup([[lx.BTN_CANCEL]], resize_keyboard=True),
    )
    return PASO_FOTO


async def paso_foto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    fotos = update.effective_message.photo
    if not fotos:
        await update.effective_message.reply_text(lx.PASO_SIN_FOTO)
        return PASO_FOTO

    # La foto más grande que mandó Telegram. Guardamos el id, no los bytes.
    context.user_data["paso"]["foto"] = fotos[-1].file_id
    await update.effective_message.reply_text(
        lx.ASK_PRIMERA, reply_markup=teclado_opciones([lx.BTN_PRIMERA, lx.BTN_REPITE])
    )
    return PASO_PRIMERA


async def paso_primera(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.effective_message.text or ""
    if texto == lx.BTN_REPITE:
        return await paso_guardar(update, context, es_primera=False, contacto=None)
    if texto != lx.BTN_PRIMERA:
        await update.effective_message.reply_text(
            "Elegí una de las dos.",
            reply_markup=teclado_opciones([lx.BTN_PRIMERA, lx.BTN_REPITE]),
        )
        return PASO_PRIMERA

    await update.effective_message.reply_text(
        lx.ASK_CONTACTO,
        reply_markup=ReplyKeyboardMarkup([[lx.BTN_SKIP], [lx.BTN_CANCEL]], resize_keyboard=True),
    )
    return PASO_CONTACTO


async def paso_contacto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.effective_message.text or ""
    contacto = None if texto == lx.BTN_SKIP else (sanitize(texto, MAX_CONTACTO) or None)
    return await paso_guardar(update, context, es_primera=True, contacto=contacto)


async def paso_guardar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    *,
    es_primera: bool,
    contacto: str | None,
) -> int:
    borrador = context.user_data.pop("paso", {})
    if "foto" not in borrador:
        await update.effective_message.reply_text(lx.PASO_SIN_FOTO)
        return ConversationHandler.END

    db, cfg = _db(context), _cfg(context)
    paso_id = db.registrar_paso(
        bar_id=borrador["bar_id"],
        foto=borrador["foto"],
        es_primera=es_primera,
        contacto=contacto,
        credito=cfg.credito,
    )
    resumen = db.resumen_bar(borrador["bar_id"])

    await update.effective_message.reply_text(
        lx.PASO_GUARDADO.format(
            id=paso_id, credito=cfg.credito_texto(), total=resumen["pasos"]
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_anfitrion(),
    )

    paso = db.get_paso(paso_id)
    if paso is not None:
        await mandar_a_admins(context, paso)
    return ConversationHandler.END


async def paso_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("paso", None)
    await update.effective_message.reply_text(lx.PASO_CANCELADO, reply_markup=menu(update, context))
    return ConversationHandler.END


# ------------------------------------------------------------------- avisos


def teclado_veredicto(paso_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✨ Especial", callback_data=f"v:{paso_id}:{ESPECIAL}"),
                InlineKeyboardButton("✓ Leída", callback_data=f"v:{paso_id}:{COMUN}"),
            ]
        ]
    )


async def avisar_admins(context: ContextTypes.DEFAULT_TYPE, texto: str) -> None:
    for admin_id in _cfg(context).admin_ids:
        try:
            await context.bot.send_message(
                admin_id, texto, parse_mode=ParseMode.MARKDOWN, disable_notification=True
            )
        except TelegramError:
            log.warning("no pude avisarle al admin %s", admin_id)


async def mandar_a_admins(context: ContextTypes.DEFAULT_TYPE, paso) -> None:
    """Cada reflexión llega a los admins apenas se carga, con los dos botones.

    Leerlas es el trabajo de verdad de esta red: cuanto menos fricción tenga,
    más chance hay de que se haga."""
    for admin_id in _cfg(context).admin_ids:
        try:
            await context.bot.send_photo(
                admin_id,
                photo=paso.foto,
                caption=lx.render_paso(paso, utcnow()),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=teclado_veredicto(paso.id),
                disable_notification=True,
            )
        except TelegramError:
            log.warning("no pude mandarle la reflexión %s al admin %s", paso.id, admin_id)


async def on_veredicto(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _es_admin(update, context):
        await query.answer("Solo los admins leen reflexiones.", show_alert=True)
        return

    _, raw_id, kind = query.data.split(":")
    paso_id = int(raw_id)
    db = _db(context)
    db.juzgar(paso_id, kind)

    if kind != ESPECIAL:
        await query.answer("Anotada como leída.")
        await _refrescar_veredicto(query, db, paso_id)
        return

    # Una reflexión especial se paga con lo único que no se compra: elegir el
    # próximo bar. El código se lo mandamos nosotros al contacto que dejó.
    code = generate_code()
    db.crear_codigo(code, NOMINACION, paso_id=paso_id, max_usos=1)
    paso = db.get_paso(paso_id)
    await query.answer("✨ Especial. Te paso el código.")
    await _refrescar_veredicto(query, db, paso_id)
    await query.message.reply_text(
        f"✨ *Reflexión #{paso_id}* marcada como especial.\n\n"
        f"Escribile a `{paso.contacto if paso and paso.contacto else 'no dejó contacto'}` "
        f"y pasale este código:\n\n`{code}`\n\n"
        "_Con ese código elige un bar nuevo para la red._",
        parse_mode=ParseMode.MARKDOWN,
    )


async def _refrescar_veredicto(query, db: Database, paso_id: int) -> None:
    paso = db.get_paso(paso_id)
    if paso is None:
        return
    try:
        await query.edit_message_caption(
            caption=lx.render_paso(paso, utcnow()), parse_mode=ParseMode.MARKDOWN
        )
    except BadRequest as exc:
        if "not modified" not in str(exc).lower():
            raise


# --------------------------------------------------------------------- panel


async def cmd_mibar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bar_id = _bar_del_anfitrion(update, context)
    if bar_id is None:
        await update.effective_message.reply_text(
            lx.LOCKED_ANFITRION, parse_mode=ParseMode.MARKDOWN, reply_markup=menu_visitante()
        )
        return

    db, cfg = _db(context), _cfg(context)
    bar = db.get_bar(bar_id)
    resumen = db.resumen_bar(bar_id)
    placa = f"#{bar.placa}" if bar and bar.placa is not None else "en camino"
    await update.effective_message.reply_text(
        f"📊 *{bar.alias if bar else 'tu bar'}*\n"
        f"Placa {placa} · {lx.LUGAR_PLACA.get(bar.placa_lugar if bar else '', '')}\n\n"
        f"✍️ {resumen['pasos']} reflexiones\n"
        f"🆕 {resumen['primeras']} primeras veces\n"
        f"✨ {resumen['especiales']} marcadas como especiales\n"
        f"🪙 {cfg.credito_texto(resumen['pasos'])} invitados en total",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu_anfitrion(),
    )


# --------------------------------------------------------------------- admin


@admin_only
async def cmd_censo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    cfg = _cfg(context)
    s = _db(context).stats()
    await update.effective_message.reply_text(
        "📊 *Estado de la red*\n\n"
        f"Bares: {s['bares']} ({s['activos']} activos)\n"
        f"Anfitriones vinculados: {s['anfitriones']}\n\n"
        f"Reflexiones: {s['pasos']} · sin leer: {s['sin_leer']}\n"
        f"Especiales: {s['especiales']}\n"
        f"Contactos nuevos: {s['contactos']}\n"
        f"Invitado en total: {cfg.moneda} {s['credito']:.0f}\n\n"
        f"Placas: {s['placas']} · en stock {s['placas_stock']} · "
        f"en camino {s['placas_en_camino']} · puestas {s['placas_puestas']}",
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cmd_bares(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bares = _db(context).listar_bares()
    if not bares:
        await update.effective_message.reply_text(
            "Todavía no hay ningún bar. Empezá con /altabar."
        )
        return
    ahora = utcnow()
    await update.effective_message.reply_text(
        "\n\n".join(lx.render_admin_bar(bar, ahora) for bar in bares),
        parse_mode=ParseMode.MARKDOWN,
    )


def _argumentos_enteros(context: ContextTypes.DEFAULT_TYPE, cuantos: int) -> list[int] | None:
    if len(context.args) < cuantos:
        return None
    try:
        return [int(arg.lstrip("#")) for arg in context.args[:cuantos]]
    except ValueError:
        return None


@admin_only
async def cmd_estado_bar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/pausar, /reactivar y /retirar comparten toda la lógica menos el verbo."""
    verbo = (update.effective_message.text or "").split()[0].lstrip("/").split("@")[0]
    kind = {"pausar": PAUSA, "reactivar": REACTIVACION, "retirar": RETIRO}[verbo]

    argumentos = _argumentos_enteros(context, 1)
    if argumentos is None:
        await update.effective_message.reply_text(f"Uso: /{verbo} <id del bar>")
        return

    db = _db(context)
    bar = db.get_bar(argumentos[0])
    if bar is None:
        await update.effective_message.reply_text("No existe ese bar.")
        return
    db.evento_bar(bar.id, kind)
    await update.effective_message.reply_text(
        f"Listo: *{bar.alias}* quedó como {kind}.", parse_mode=ParseMode.MARKDOWN
    )


@admin_only
async def cmd_placas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    db = _db(context)
    if context.args:
        argumentos = _argumentos_enteros(context, 1)
        if argumentos is None or not 1 <= argumentos[0] <= 500:
            await update.effective_message.reply_text("Uso: /placas <cuántas emitir, 1 a 500>")
            return
        numeros = db.emitir_placas(argumentos[0])
        await update.effective_message.reply_text(
            f"🔢 Emitidas {len(numeros)} placas: *{numeros[0]}* a *{numeros[-1]}*.\n\n"
            "Mandá a grabar esos números. Asignalas con /asignar <número> <id del bar>.",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    stock = db.placas_en_stock()
    resumen = db.resumen_placas()
    detalle = " · ".join(f"{clave}: {valor}" for clave, valor in resumen.items() if valor)
    await update.effective_message.reply_text(
        f"🔢 *Placas*\n{detalle or 'todavía ninguna'}\n\n"
        f"Libres: {', '.join(str(n) for n in stock[:30]) or '—'}",
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cmd_asignar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    argumentos = _argumentos_enteros(context, 2)
    if argumentos is None:
        await update.effective_message.reply_text("Uso: /asignar <número de placa> <id del bar>")
        return
    numero, bar_id = argumentos

    db = _db(context)
    bar = db.get_bar(bar_id)
    if bar is None:
        await update.effective_message.reply_text("No existe ese bar.")
        return
    try:
        db.asignar_placa(numero, bar_id)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(
        f"🔢 Placa *{numero}* → *{bar.alias}*.\n\n"
        f"Cuando la despaches: /enviada {numero}. Cuando esté pegada: /instalada {numero}.",
        parse_mode=ParseMode.MARKDOWN,
    )


@admin_only
async def cmd_movimiento_placa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/enviada e /instalada: el mismo movimiento con distinto nombre."""
    verbo = (update.effective_message.text or "").split()[0].lstrip("/").split("@")[0]
    kind = {"enviada": ENVIADA, "instalada": INSTALADA}[verbo]

    argumentos = _argumentos_enteros(context, 1)
    if argumentos is None:
        await update.effective_message.reply_text(f"Uso: /{verbo} <número de placa>")
        return

    db = _db(context)
    placa = db.get_placa(argumentos[0])
    if placa is None:
        await update.effective_message.reply_text("Esa placa no fue emitida.")
        return
    if placa.bar_id is None:
        await update.effective_message.reply_text(
            f"La placa {placa.numero} todavía no tiene bar. Asignala primero."
        )
        return
    db.evento_placa(placa.numero, kind, placa.bar_id)
    await update.effective_message.reply_text(
        f"🔢 Placa *{placa.numero}* ({placa.bar_alias}): {kind}.", parse_mode=ParseMode.MARKDOWN
    )


@admin_only
async def cmd_anfitrion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    argumentos = _argumentos_enteros(context, 1)
    if argumentos is None:
        await update.effective_message.reply_text("Uso: /anfitrion <id del bar>")
        return

    db = _db(context)
    bar = db.get_bar(argumentos[0])
    if bar is None:
        await update.effective_message.reply_text("No existe ese bar.")
        return
    await update.effective_message.reply_text(
        _texto_codigo_anfitrion(db, bar.id, bar.alias, context.bot.username),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


def _texto_codigo_anfitrion(db: Database, bar_id: int, alias: str, username: str | None) -> str:
    """Emite un código y arma el mensaje que se le reenvía al dueño del bar."""
    code = generate_code()
    db.crear_codigo(code, ANFITRION, bar_id=bar_id, max_usos=3)
    link = f"https://t.me/{username}?start=hola" if username else "(link no disponible)"
    return (
        f"🔑 Código de anfitrión para *{alias}* (id {bar_id}):\n\n`{code}`\n\n"
        f"Que el dueño abra {link}, mande ese código y queda vinculado.\n"
        "_Sirve para 3 personas del bar._"
    )


@admin_only
async def cmd_pendientes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    pasos = _db(context).pasos_sin_leer()
    if not pasos:
        await update.effective_message.reply_text("No quedan reflexiones sin leer. 🎉")
        return
    ahora = utcnow()
    for paso in pasos:
        await update.effective_message.reply_photo(
            photo=paso.foto,
            caption=lx.render_paso(paso, ahora),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=teclado_veredicto(paso.id),
        )


@admin_only
async def cmd_propuestas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    nominaciones = _db(context).nominaciones_abiertas()
    if not nominaciones:
        await update.effective_message.reply_text("No hay propuestas abiertas.")
        return

    for nominacion in nominaciones:
        await update.effective_message.reply_text(
            f"✨ *Propuesta #{nominacion.id}* · {nominacion.alias}\n"
            f"_{nominacion.motivo or 'sin motivo'}_\n"
            f"🗺 [Dónde queda]({map_url(nominacion.lat, nominacion.lon)})",
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=True,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("✅ Entra", callback_data=f"n:{nominacion.id}:si"),
                        InlineKeyboardButton("✖️ No", callback_data=f"n:{nominacion.id}:no"),
                    ]
                ]
            ),
        )


async def on_propuesta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not _es_admin(update, context):
        await query.answer("Solo los admins.", show_alert=True)
        return

    _, raw_id, decision = query.data.split(":")
    db = _db(context)
    nominacion_id = int(raw_id)

    if decision == "no":
        db.evento_nominacion(nominacion_id, "rechazada")
        await query.answer("Rechazada.")
        await query.edit_message_reply_markup(reply_markup=None)
        return

    bar_id = db.aprobar_nominacion(nominacion_id)
    if bar_id is None:
        await query.answer("Esa propuesta ya estaba resuelta.", show_alert=True)
        return

    nominacion = db.get_nominacion(nominacion_id)
    await query.answer("Entró a la red.")
    await query.edit_message_reply_markup(reply_markup=None)
    await query.message.reply_text(
        f"✅ *{nominacion.alias}* es el bar {bar_id} de la red.\n\n"
        "Ahora: asignale una placa con /asignar y pasale el código de anfitrión al dueño.\n\n"
        + _texto_codigo_anfitrion(db, bar_id, nominacion.alias, context.bot.username),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )


@admin_only
async def cmd_respaldo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    path = make_backup(_db(context), _cfg(context))
    with path.open("rb") as handle:
        await update.effective_message.reply_document(
            document=handle, filename=path.name, caption="🗄 Respaldo manual"
        )


# ------------------------------------------------------------- alta de un bar


async def alta_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not _es_admin(update, context):
        return ConversationHandler.END
    context.user_data["alta"] = {}
    await update.effective_message.reply_text(
        "📍 Mandame el pin del bar.", reply_markup=teclado_ubicacion()
    )
    return ALTA_UBICACION


async def alta_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    location = update.effective_message.location
    context.user_data["alta"]["lat"] = location.latitude
    context.user_data["alta"]["lon"] = location.longitude
    await update.effective_message.reply_text(
        "¿Cómo se llama?", reply_markup=ReplyKeyboardMarkup([[lx.BTN_CANCEL]], resize_keyboard=True)
    )
    return ALTA_ALIAS


async def alta_alias(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    alias = sanitize(update.effective_message.text, MAX_ALIAS)
    if not alias:
        await update.effective_message.reply_text("Necesito un nombre.")
        return ALTA_ALIAS
    context.user_data["alta"]["alias"] = alias
    await update.effective_message.reply_text(
        "Dirección, para que la gente la lea antes de salir.",
        reply_markup=ReplyKeyboardMarkup(
            [[lx.BTN_SKIP], [lx.BTN_CANCEL]], resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return ALTA_DIRECCION


async def alta_direccion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.effective_message.text or ""
    direccion = None if texto == lx.BTN_SKIP else (sanitize(texto, MAX_DIRECCION) or None)
    context.user_data["alta"]["direccion"] = direccion
    await update.effective_message.reply_text(
        "¿Dónde va a ir la placa?", reply_markup=teclado_opciones(lx.LUGAR_PLACA_BUTTONS)
    )
    return ALTA_PLACA


async def alta_placa(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    lugar = lx.LUGAR_PLACA_BUTTONS.get(update.effective_message.text or "")
    if lugar is None:
        await update.effective_message.reply_text(
            "Elegí una de las opciones.", reply_markup=teclado_opciones(lx.LUGAR_PLACA_BUTTONS)
        )
        return ALTA_PLACA
    context.user_data["alta"]["placa_lugar"] = lugar
    await update.effective_message.reply_text(
        "Última: una nota para quien llegue (o salteá).",
        reply_markup=ReplyKeyboardMarkup(
            [[lx.BTN_SKIP], [lx.BTN_CANCEL]], resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return ALTA_NOTA


async def alta_nota(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    texto = update.effective_message.text or ""
    nota = None if texto == lx.BTN_SKIP else (sanitize(texto, MAX_NOTA) or None)
    borrador = context.user_data.pop("alta", {})

    db = _db(context)
    bar_id = db.alta_bar(
        alias=borrador["alias"],
        lat=borrador["lat"],
        lon=borrador["lon"],
        direccion=borrador.get("direccion"),
        placa_lugar=borrador.get("placa_lugar", "sin_definir"),
        nota=nota,
        origen="fundacional",
    )

    libres = db.placas_en_stock()
    sugerencia = (
        f"Placa libre más baja: *{libres[0]}* → `/asignar {libres[0]} {bar_id}`"
        if libres
        else "No hay placas en stock: emití con /placas <cuántas>."
    )
    await update.effective_message.reply_text(
        f"✅ *{borrador['alias']}* entró como bar {bar_id}.\n\n{sugerencia}",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=menu(update, context),
    )
    await update.effective_message.reply_text(
        _texto_codigo_anfitrion(db, bar_id, borrador["alias"], context.bot.username),
        parse_mode=ParseMode.MARKDOWN,
        disable_web_page_preview=True,
    )
    return ConversationHandler.END


async def alta_cancelar(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.pop("alta", None)
    await update.effective_message.reply_text("Cancelado.", reply_markup=menu(update, context))
    return ConversationHandler.END


async def esperaba_ubicacion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(
        "Necesito el pin. Tocá el botón, o mandame una ubicación (📎 → Ubicación).",
        reply_markup=teclado_ubicacion(),
    )


# ------------------------------------------------------------------ errores


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    log.exception("error procesando un update", exc_info=context.error)


# ------------------------------------------------------------------- armado


def _cancel_filter():
    return filters.Regex(f"^{re.escape(lx.BTN_CANCEL)}$")


def conversacion_paso() -> ConversationHandler:
    cancelar = _cancel_filter()
    return ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_PASO)}$"), paso_start),
            CommandHandler("cargar", paso_start),
        ],
        states={
            PASO_FOTO: [
                MessageHandler(filters.PHOTO, paso_foto),
                MessageHandler(~cancelar & ~filters.COMMAND, paso_foto),
            ],
            PASO_PRIMERA: [
                MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, paso_primera)
            ],
            PASO_CONTACTO: [
                MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, paso_contacto)
            ],
        },
        fallbacks=[
            MessageHandler(cancelar, paso_cancelar),
            CommandHandler("cancelar", paso_cancelar),
        ],
        allow_reentry=True,
    )


def conversacion_alta() -> ConversationHandler:
    cancelar = _cancel_filter()
    return ConversationHandler(
        entry_points=[CommandHandler("altabar", alta_start)],
        states={
            ALTA_UBICACION: [
                MessageHandler(filters.LOCATION, alta_ubicacion),
                MessageHandler(~cancelar & ~filters.COMMAND, esperaba_ubicacion),
            ],
            ALTA_ALIAS: [MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, alta_alias)],
            ALTA_DIRECCION: [
                MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, alta_direccion)
            ],
            ALTA_PLACA: [MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, alta_placa)],
            ALTA_NOTA: [MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, alta_nota)],
        },
        fallbacks=[
            MessageHandler(cancelar, alta_cancelar),
            CommandHandler("cancelar", alta_cancelar),
        ],
        allow_reentry=True,
    )


def conversacion_nominacion() -> ConversationHandler:
    cancelar = _cancel_filter()
    return ConversationHandler(
        entry_points=[MessageHandler(filters.Regex(CODE_RE), on_codigo)],
        states={
            NOM_UBICACION: [
                MessageHandler(filters.LOCATION, nominar_ubicacion),
                MessageHandler(~cancelar & ~filters.COMMAND, esperaba_ubicacion),
            ],
            NOM_ALIAS: [MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, nominar_alias)],
            NOM_MOTIVO: [
                MessageHandler(filters.TEXT & ~cancelar & ~filters.COMMAND, nominar_motivo)
            ],
        },
        fallbacks=[
            MessageHandler(cancelar, nominar_cancelar),
            CommandHandler("cancelar", nominar_cancelar),
        ],
        allow_reentry=True,
    )


def register(application) -> None:
    # Las conversaciones van primero: mientras alguien está en el medio de una,
    # sus mensajes son de ella y no del menú.
    application.add_handler(conversacion_paso())
    application.add_handler(conversacion_alta())
    application.add_handler(conversacion_nominacion())

    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("ayuda", cmd_trato))
    application.add_handler(CommandHandler("trato", cmd_trato))
    application.add_handler(CommandHandler("privacidad", cmd_privacidad))
    application.add_handler(CommandHandler("cerca", pedir_ubicacion))
    application.add_handler(CommandHandler("placa", cmd_placa))
    application.add_handler(CommandHandler("mibar", cmd_mibar))

    for comando in ("pausar", "reactivar", "retirar"):
        application.add_handler(CommandHandler(comando, cmd_estado_bar))
    for comando in ("enviada", "instalada"):
        application.add_handler(CommandHandler(comando, cmd_movimiento_placa))
    application.add_handler(CommandHandler("bares", cmd_bares))
    application.add_handler(CommandHandler("placas", cmd_placas))
    application.add_handler(CommandHandler("asignar", cmd_asignar))
    application.add_handler(CommandHandler("anfitrion", cmd_anfitrion))
    application.add_handler(CommandHandler("pendientes", cmd_pendientes))
    application.add_handler(CommandHandler("propuestas", cmd_propuestas))
    application.add_handler(CommandHandler("censo", cmd_censo))
    application.add_handler(CommandHandler("respaldo", cmd_respaldo))

    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_CERCA)}$"), pedir_ubicacion))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_TRATO)}$"), cmd_trato))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_PLACA)}$"), pedir_placa))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_MIBAR)}$"), cmd_mibar))
    application.add_handler(MessageHandler(filters.Regex(f"^{re.escape(lx.BTN_CANCEL)}$"), cmd_start))
    application.add_handler(MessageHandler(filters.LOCATION, on_ubicacion))
    application.add_handler(MessageHandler(filters.Regex(SOLO_NUMERO_RE), on_numero_suelto))

    application.add_handler(CallbackQueryHandler(on_buscar_mas, pattern=r"^cerca:"))
    application.add_handler(CallbackQueryHandler(on_ficha, pattern=r"^b:"))
    application.add_handler(CallbackQueryHandler(on_veredicto, pattern=r"^v:"))
    application.add_handler(CallbackQueryHandler(on_propuesta, pattern=r"^n:"))

    application.add_error_handler(on_error)
