"""Todo lo que el bot dice, en un solo lugar.

El vocabulario no es decoración: cada campo "de ciencia ficción" carga un dato
que de verdad sirve cuando estás parado en la calle buscando un lugar.

    cobertura     -> ¿hay techo? ¿corre viento? ¿te tapa la lluvia?
    interferencia -> ¿cuánta gente pasa por ahí?
    ventana       -> ¿a qué hora conviene?
    estabilidad   -> ¿sigue sirviendo, según quienes volvieron?
"""

from __future__ import annotations

from .db import Glitch
from .geo import format_distance, map_url
from .stability import bar, humanize_age, label

# --------------------------------------------------------------------- campos

COBERTURA = {
    "techo": "techo sólido",
    "semi": "semicubierto",
    "abierto": "cielo abierto",
}

INTERFERENCIA = {
    "nula": "nula · no pasa nadie",
    "baja": "baja · algún transeúnte",
    "media": "media · hay movimiento",
    "alta": "alta · zona observada",
}

VENTANA = {
    "madrugada": "madrugada · 00–06",
    "mañana": "mañana · 06–12",
    "tarde": "tarde · 12–19",
    "noche": "noche · 19–00",
    "cualquiera": "cualquier hora",
}

# ------------------------------------------------------------------- botonera

# Cada paso del registro se contesta con un botón del teclado, así nadie tiene
# que escribir nada que después haya que interpretar.
COBERTURA_BUTTONS = {
    "🏠 Techo sólido": "techo",
    "🌤 Semicubierto": "semi",
    "🌌 Cielo abierto": "abierto",
}

INTERFERENCIA_BUTTONS = {
    "🔇 Nula": "nula",
    "🔈 Baja": "baja",
    "🔉 Media": "media",
    "🔊 Alta": "alta",
}

VENTANA_BUTTONS = {
    "🌑 Madrugada": "madrugada",
    "🌅 Mañana": "mañana",
    "🌇 Tarde": "tarde",
    "🌃 Noche": "noche",
    "♾ Cualquiera": "cualquiera",
}

BTN_SCAN = "📡 Escanear la grilla"
BTN_REPORT = "🛰 Registrar anomalía"
BTN_MANUAL = "📖 Manual de campo"
BTN_CANCEL = "✖️ Abortar"
BTN_LOCATION = "📍 Fijar mi posición"
BTN_SKIP = "Saltear"

# --------------------------------------------------------------------- textos

WELCOME = (
    "▞▚ *RED DE ANOMALÍAS* ▚▞\n\n"
    "Acá se registran los puntos donde la realidad afloja un poco: rincones "
    "donde el tiempo pasa distinto y nadie te mira.\n\n"
    "Escaneá la grilla para ver qué hay cerca tuyo, o registrá una anomalía "
    "nueva si encontraste una que no figura.\n\n"
    "_La grilla la sostiene la gente que vuelve a confirmar los puntos. "
    "Si algo dejó de funcionar, marcalo._"
)

LOCKED = (
    "🔒 *Acceso restringido a la grilla*\n\n"
    "Esta red no es pública. Necesitás un código de acceso de alguien que ya "
    "esté adentro.\n\n"
    "Si tenés uno, mandámelo ahora (formato `GLX-XXXX-XXXX`)."
)

BAD_CODE = (
    "⛔ Código inválido o agotado.\n\n"
    "Puede que ya lo haya usado todo el mundo. Pedí uno nuevo a quien te invitó."
)

GRANTED = (
    "✅ *Acceso concedido.*\n\n"
    "Estás dentro de la red. Bienvenido a la grilla."
)

MANUAL = (
    "📖 *MANUAL DE CAMPO*\n\n"
    "*Escanear la grilla*\n"
    "Compartís tu posición y te devuelvo las anomalías más cercanas, ordenadas "
    "por distancia. Si no aparece nada, ampliá el radio.\n\n"
    "*Registrar una anomalía*\n"
    "Marcás el punto exacto y respondés cuatro cosas: si hay techo, cuánta "
    "gente pasa, a qué hora conviene y cualquier detalle útil.\n\n"
    "*Índice de estabilidad*\n"
    "Arranca en 55. Sube cuando alguien confirma que el punto sigue sirviendo, "
    "baja cuando alguien avisa que colapsó, y se erosiona solo si nadie lo "
    "toca durante mucho tiempo. Por debajo de 25 deja de aparecer en los "
    "escaneos normales.\n\n"
    "Por eso importa tocar los botones cuando volvés de un lugar: es lo único "
    "que mantiene la grilla viva.\n\n"
    "*Privacidad* → /privacidad"
)

PRIVACY = (
    "🕶 *Qué guarda esta red*\n\n"
    "*De los lugares:* coordenadas, alias, los tres atributos y tu nota. "
    "Nada más.\n\n"
    "*De vos:* nada. Literalmente nada.\n\n"
    "Las tablas de lugares y de confirmaciones no tienen ninguna columna de "
    "usuario. Ni tu id, ni tu nombre, ni un hash. No existe forma de saber "
    "quién cargó qué punto, ni quién lo confirmó — ni para mí, ni para nadie "
    "con acceso total a la base.\n\n"
    "Lo único que se recuerda de las personas es un HMAC de tu id de Telegram "
    "en la lista de la puerta, para no pedirte el código cada vez. Esa lista "
    "no se cruza con nada, y sin la sal secreta (que vive fuera de la base) "
    "ese dato no sirve para nada.\n\n"
    "*Consecuencia:* no puedo mostrarte \"tus\" reportes ni dejarte borrarlos, "
    "porque no sé cuáles son. Es el precio del anonimato, y es a propósito.\n\n"
    "Tampoco se borra nada: un lugar que dejó de servir pierde estabilidad "
    "hasta desvanecerse, pero su historia queda."
)

ASK_LOCATION_SCAN = (
    "📡 Necesito tu posición para barrer la zona.\n\n"
    "Tocá el botón, o mandame un pin del mapa si querés escanear otro lugar."
)

ASK_LOCATION_REPORT = (
    "🛰 *Anclaje de coordenadas*\n\n"
    "Marcá el punto exacto de la anomalía. Si no estás ahí, mandame un pin del "
    "mapa (📎 → Ubicación) en vez de usar el botón."
)

ASK_ALIAS = (
    "Ponele un nombre corto para reconocerlo en la lista.\n\n"
    "_Ej: «el banco del fondo», «la escalera del club»._"
)

ASK_COVER = "¿Cómo está de cobertura? Esto define si te sirve con viento o lluvia."
ASK_NOISE = "¿Cuánta interferencia hay? O sea: cuánta gente pasa."
ASK_WINDOW = "¿Cuál es la ventana temporal óptima?"
ASK_NOTE = (
    "Último paso: alguna nota para quien llegue.\n\n"
    "_Cómo entrar, dónde sentarse, qué evitar._ Tocá «Saltear» si no hace falta."
)

SAVED = (
    "✅ *Anomalía registrada en la grilla.*\n\n"
    "Ya aparece para todo el que escanee la zona. Cuando alguien vuelva y "
    "confirme que sigue activa, su estabilidad va a subir."
)

CANCELLED = "Registro abortado. No quedó nada anotado."
NOTHING_NEARBY = (
    "📡 *Sin anomalías en {radius}.*\n\n"
    "La zona parece estable. Podés ampliar el barrido, o registrar vos la "
    "primera de la zona."
)

RATE_LIMITED = (
    "⏳ Demasiadas señales seguidas desde este terminal. Esperá un rato.\n\n"
    "_(El límite vive en memoria y no queda registrado en ningún lado.)_"
)

CONFIRMED = "📈 Señal recibida. La anomalía sube en estabilidad."
COLLAPSED = "📉 Colapso reportado. La anomalía pierde estabilidad."
ALREADY_SIGNALED = "Ya mandaste una señal para esta anomalía hace poco."


def render_card(glitch: Glitch, now, *, with_link: bool = True) -> str:
    """Ficha completa de una anomalía."""
    score = glitch.score
    lines = [
        f"▞▚ *GLITCH #{glitch.id}* · «{glitch.alias}»",
        f"`{bar(score)}` *{score}* · {label(score)}",
    ]
    if glitch.distance_m is not None:
        lines.append(f"📍 A {format_distance(glitch.distance_m)} tuyo")
    lines += [
        f"🛰 Cobertura: {COBERTURA.get(glitch.cobertura, glitch.cobertura)}",
        f"📶 Interferencia: {INTERFERENCIA.get(glitch.interferencia, glitch.interferencia)}",
        f"🕓 Ventana: {VENTANA.get(glitch.ventana, glitch.ventana)}",
    ]
    if glitch.nota:
        lines.append(f"🗒 _{glitch.nota}_")

    if glitch.last_signal is not None:
        lines.append(
            f"⏱ Última señal {humanize_age(glitch.last_signal, now)}"
            f" · {glitch.confirms} ✅ / {glitch.collapses} ⚠️"
        )
    else:
        lines.append(f"⏱ Registrada {humanize_age(glitch.created_at, now)} · sin confirmar todavía")

    if with_link:
        lines.append(f"🗺 [Abrir en el mapa]({map_url(glitch.lat, glitch.lon)})")
    return "\n".join(lines)


def render_row(index: int, glitch: Glitch) -> str:
    """Una línea del listado de resultados."""
    distance = format_distance(glitch.distance_m) if glitch.distance_m is not None else "—"
    return (
        f"*{index}.* «{glitch.alias}» · {distance}\n"
        f"    `{bar(glitch.score, 8)}` {glitch.score} · {label(glitch.score)}"
    )
