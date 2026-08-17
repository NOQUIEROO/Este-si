"""Todo lo que el bot dice, en un solo lugar.

Acá no hay disfraz: el bot habla en criollo, porque del otro lado hay un dueño
de bar atendiendo la barra y alguien parado en la puerta con frío. Cada texto
tiene que poder leerse en diez segundos.
"""

from __future__ import annotations

from glitchmap.geo import format_distance, map_url

from .db import Bar, Paso
from .estado import ETIQUETA_BAR, ETIQUETA_PLACA, ETIQUETA_VEREDICTO, hace

# ---------------------------------------------------------------- vocabulario

LUGAR_PLACA = {
    "frente": "abajo, en el frente",
    "bano": "en el baño",
    "barra": "en la barra",
    "sin_definir": "todavía sin definir",
}

LUGAR_PLACA_BUTTONS = {
    "🚪 Abajo, en el frente": "frente",
    "🚻 En el baño": "bano",
    "🍸 En la barra": "barra",
    "❓ Después vemos": "sin_definir",
}

ORIGEN = {
    "fundacional": "elegido por nosotros",
    "nominado": "elegido por una reflexión especial",
}

# -------------------------------------------------------------------- botones

BTN_CERCA = "📍 Bares con placa cerca"
BTN_TRATO = "🪙 Cómo funciona"
BTN_PLACA = "🔎 Verificar una placa"
BTN_PASO = "✍️ Cargar una reflexión"
BTN_MIBAR = "📊 Mi bar"
BTN_UBICACION = "📍 Usar mi ubicación"
BTN_CANCEL = "✖️ Cancelar"
BTN_SKIP = "Saltear"
BTN_PRIMERA = "🆕 Es la primera vez"
BTN_REPITE = "🔁 Ya había venido"

# --------------------------------------------------------------------- textos

WELCOME = (
    "⬛️ *ODD*\n\n"
    "Hay bares que tienen una placa chiquita de metal: abajo en el frente, en "
    "el baño o en la barra. Esa placa quiere decir que el bar está aprobado "
    "por el criterio ODD.\n\n"
    "Si entrás a uno y decís que sabés de ODD, te invitan hasta {credito} en "
    "consumición. A cambio dejás una reflexión escrita, el dueño le saca una "
    "foto, y listo.\n\n"
    "Buscá el que tengas más cerca 👇"
)

WELCOME_ANFITRION = (
    "⬛️ *ODD · {alias}*\n\n"
    "Este es tu panel. Cuando alguien deje una reflexión, cargala acá: foto de "
    "la reflexión, y si es la primera vez, el contacto.\n\n"
    "Cada reflexión cargada es {credito} de consumición que invitás vos."
)

TRATO = (
    "🪙 *El trato, completo*\n\n"
    "*1.* Entrás a un bar de la lista y decís que sabés de ODD.\n"
    "*2.* Escribís una reflexión. A mano, en el papel que te den. Lo que "
    "tengas ganas de escribir.\n"
    "*3.* El dueño le saca una foto. Si es tu primera vez, le dejás también un "
    "contacto — una sola vez en tu vida, nunca más.\n"
    "*4.* Te invitan hasta {credito} en consumición.\n\n"
    "Si volvés otro día, o vas a otro bar de la red: reflexión nueva, sin "
    "contacto. Ya estás.\n\n"
    "*Cómo reconocer un bar de la red*\n"
    "Por la placa: metálica, del tamaño de una tarjeta de crédito, numerada y "
    "pegada. Está abajo en el frente, en el baño o en la barra. Si no ves "
    "ninguna placa, no es un bar de la red.\n\n"
    "Podés chequear que una placa sea de verdad: {btn_placa}.\n\n"
    "*Y algo más*\n"
    "Las reflexiones las leemos. Cuando una nos parece especial, le "
    "escribimos a esa persona al contacto que dejó y le damos algo que no se "
    "compra: elegir el próximo bar de la red.\n\n"
    "Qué guardamos de vos → /privacidad"
)

PRIVACY = (
    "🕶 *Qué guardamos*\n\n"
    "*Si solo buscás bares:* nada. Buscar no deja ninguna fila en ningún lado. "
    "Tu ubicación se usa para calcular distancias y se olvida.\n\n"
    "*Si dejás una reflexión:* la foto que saca el dueño (que vive en los "
    "servidores de Telegram, no en los nuestros), en qué bar fue y cuándo. La "
    "reflexión no lleva tu nombre.\n\n"
    "*Si es tu primera vez:* además el contacto que dejaste. Ese es el único "
    "dato personal de todo el sistema, lo dejás sabiendo que lo dejás, y sirve "
    "para una sola cosa: poder escribirte si tu reflexión resulta especial.\n\n"
    "No lo vendemos, no lo cruzamos con nada y no te vamos a mandar "
    "publicidad. Si querés que lo borremos, escribinos y listo.\n\n"
    "*De los dueños de bar* guardamos un HMAC de su id de Telegram con una "
    "sal que vive fuera de la base: alcanza para saber qué bar administran y "
    "no sirve para nada más."
)

LOCKED_ANFITRION = (
    "Este panel es para los bares de la red.\n\n"
    "Si sos dueño de un bar y tenés un código de anfitrión (`ODD-XXXX-XXXX`), "
    "mandámelo y quedás vinculado a tu bar."
)

BAD_CODE = "⛔ Ese código no existe o ya se usó."

ANFITRION_LISTO = (
    "✅ Quedaste como anfitrión de *{alias}*.\n\n"
    "Ya podés cargar reflexiones desde el menú."
)

ASK_UBICACION = (
    "Pasame tu ubicación y te digo qué bares de la red tenés cerca.\n\n"
    "_Tocá el botón, o mandame un pin del mapa si querés mirar otra zona._"
)

SIN_BARES = (
    "No hay ningún bar de la red en {radio}.\n\n"
    "Todavía somos pocos. Podés ampliar la búsqueda acá abajo."
)

ASK_PLACA = "Pasame el número que dice la placa y te digo si es de la red."

PLACA_DESCONOCIDA = (
    "❌ *La placa {numero} no figura.*\n\n"
    "Puede ser un número mal leído, o una placa que no emitimos nosotros. "
    "Si te están cobrando por algo que no es, avisanos."
)

PLACA_SIN_BAR = (
    "🔢 *Placa {numero}* · emitida pero todavía sin bar.\n\n"
    "Si la viste puesta en una pared, avisanos: alguien se adelantó."
)

PLACA_OK = "✅ *Placa {numero}* · {bar}\n{estado}\n\n_Es de la red._"

# --------------------------------------------------------------- cargar paso

ASK_FOTO = (
    "📷 Mandame la foto de la reflexión.\n\n"
    "_Que se lea. No hace falta que salga linda._"
)

ASK_PRIMERA = "¿Es la primera vez de esta persona en la red?"

ASK_CONTACTO = (
    "Pedile un contacto y escribilo acá: un mail, un teléfono, un usuario de "
    "Instagram. Lo que prefiera.\n\n"
    "Se lo pedimos una sola vez en la vida, y es para avisarle si su reflexión "
    "resulta especial."
)

PASO_GUARDADO = (
    "✅ *Reflexión #{id} cargada.*\n\n"
    "Invitale hasta {credito} en consumición.\n\n"
    "_Van {total} en tu bar._"
)

PASO_SIN_FOTO = "Necesito la foto de la reflexión. Mandámela como foto, no como archivo."
PASO_CANCELADO = "Listo, no cargué nada."

RATE_LIMITED = "⏳ Muchas cargas seguidas. Esperá un rato."

# ---------------------------------------------------------------- nominación

NOMINAR_BIENVENIDA = (
    "✨ *Tu reflexión nos pareció especial.*\n\n"
    "Por eso te toca lo que no se compra: elegir un bar nuevo para la red.\n\n"
    "Pensalo bien: si lo aprobamos, le mandamos una placa numerada y queda "
    "adentro. Vas a poder decir que ese lugar está por vos."
)

ASK_NOMINACION_UBICACION = "📍 ¿Dónde queda? Mandame el pin del bar."
ASK_NOMINACION_ALIAS = "¿Cómo se llama?"
ASK_NOMINACION_MOTIVO = (
    "Última: ¿por qué ese y no otro?\n\n"
    "_Dos renglones alcanzan. Es lo que vamos a leer cuando decidamos._"
)

NOMINACION_GUARDADA = (
    "✅ *Anotado: {alias}.*\n\n"
    "Lo vamos a ir a ver. Si entra en la red, te avisamos al contacto que "
    "dejaste."
)

# ------------------------------------------------------------------ render


def render_bar(bar: Bar, ahora, *, con_link: bool = True) -> str:
    """La ficha que ve alguien parado en la calle."""
    lineas = [f"⬛️ *{bar.alias}*"]
    if bar.distance_m is not None:
        lineas.append(f"📍 A {format_distance(bar.distance_m)} tuyo")
    if bar.direccion:
        lineas.append(f"🏠 {bar.direccion}")
    if bar.placa is not None:
        lineas.append(f"🔢 Placa #{bar.placa} · {LUGAR_PLACA.get(bar.placa_lugar, '')}")
    else:
        lineas.append("🔢 Placa en camino")
    if bar.nota:
        lineas.append(f"🗒 _{bar.nota}_")
    if bar.estado != "activo":
        lineas.append(f"⚠️ {ETIQUETA_BAR.get(bar.estado, bar.estado)}")
    if bar.pasos == 1:
        lineas.append("✍️ Una reflexión dejada acá")
    elif bar.pasos:
        lineas.append(f"✍️ {bar.pasos} reflexiones dejadas acá")
    else:
        lineas.append("✍️ Todavía nadie dejó una reflexión acá. Podés ser la primera persona.")
    if con_link:
        lineas.append(f"🗺 [Cómo llegar]({map_url(bar.lat, bar.lon)})")
    return "\n".join(lineas)


def render_fila(indice: int, bar: Bar) -> str:
    distancia = format_distance(bar.distance_m) if bar.distance_m is not None else "—"
    placa = f"placa #{bar.placa}" if bar.placa is not None else "placa en camino"
    return f"*{indice}.* {bar.alias} · {distancia}\n    _{placa}_"


def render_paso(paso: Paso, ahora) -> str:
    """Lo que ve un admin cuando lee una reflexión."""
    lineas = [
        f"✍️ *Reflexión #{paso.id}* · {paso.bar_alias}",
        f"🕓 {hace(paso.created_at, ahora)} · {ETIQUETA_VEREDICTO.get(paso.veredicto, paso.veredicto)}",
    ]
    if paso.es_primera:
        lineas.append(f"🆕 Primera vez · contacto: `{paso.contacto or 'no dejó'}`")
    else:
        lineas.append("🔁 Ya había venido")
    return "\n".join(lineas)


def render_admin_bar(bar: Bar, ahora) -> str:
    """La misma ficha, pero con lo que solo nos importa a nosotros."""
    placa = f"#{bar.placa}" if bar.placa is not None else "—"
    lineas = [
        f"*[{bar.id}] {bar.alias}* · {ETIQUETA_BAR.get(bar.estado, bar.estado)}",
        f"placa {placa} ({LUGAR_PLACA.get(bar.placa_lugar, '')}) · {ORIGEN.get(bar.origen, bar.origen)}",
        f"{bar.pasos} {'reflexión' if bar.pasos == 1 else 'reflexiones'}"
        + (f" · última {hace(bar.ultimo_paso, ahora)}" if bar.ultimo_paso else ""),
    ]
    return "\n".join(lineas)


def render_placa(numero: int, estado: str, bar_alias: str | None) -> str:
    if bar_alias is None:
        return PLACA_SIN_BAR.format(numero=numero)
    return PLACA_OK.format(
        numero=numero,
        bar=bar_alias,
        estado=f"_{ETIQUETA_PLACA.get(estado, estado)}_",
    )
