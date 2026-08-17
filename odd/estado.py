"""El estado de las cosas, como funciones puras.

En esta base nada se edita y nada se borra: un bar no cambia de estado, se le
agrega un evento. El estado actual es siempre *el ultimo evento*, y calcularlo
es una funcion pura — mismo input, mismo resultado, testeable sin base.

Vale para las tres cosas que tienen vida propia:

    un bar     -> alta / pausa / reactivacion / retiro
    una placa  -> emitida / asignada / enviada / instalada / baja
    un paso    -> pendiente hasta que un admin lo juzga comun o especial
"""

from __future__ import annotations

from datetime import datetime


def _ultimo(eventos: list[tuple[str, datetime]]) -> str | None:
    """El evento mas nuevo. Ante dos con la misma hora, gana el ultimo cargado.

    El desempate importa de verdad: dos eventos pueden caer en el mismo
    segundo (o traer la misma fecha si alguien la escribio a mano), y sin una
    regla clara el estado quedaria a merced del orden en que SQLite devuelva
    las filas. Por eso todas las consultas los traen en orden de insercion y
    aca nos quedamos con el ultimo de esa lista.
    """
    if not eventos:
        return None
    return max(enumerate(eventos), key=lambda par: (par[1][1], par[0]))[1][0]


# ------------------------------------------------------------------- un bar

ALTA = "alta"
PAUSA = "pausa"
REACTIVACION = "reactivacion"
RETIRO = "retiro"

ACTIVO = "activo"
PAUSADO = "pausado"
RETIRADO = "retirado"

_ESTADO_POR_EVENTO = {
    ALTA: ACTIVO,
    REACTIVACION: ACTIVO,
    PAUSA: PAUSADO,
    RETIRO: RETIRADO,
}

EVENTOS_BAR = tuple(_ESTADO_POR_EVENTO)

ETIQUETA_BAR = {
    ACTIVO: "🟢 activo",
    PAUSADO: "🟡 en pausa",
    RETIRADO: "⚫️ retirado",
}


def estado_bar(eventos: list[tuple[str, datetime]]) -> str:
    """Estado de un bar a partir de su historia. Sin eventos: activo."""
    return _ESTADO_POR_EVENTO.get(_ultimo(eventos), ACTIVO)


def es_visitable(estado: str) -> bool:
    """Solo los activos se muestran en una busqueda normal."""
    return estado == ACTIVO


# ----------------------------------------------------------------- una placa

EMITIDA = "emitida"
ASIGNADA = "asignada"
ENVIADA = "enviada"
INSTALADA = "instalada"
BAJA = "baja"

EVENTOS_PLACA = (EMITIDA, ASIGNADA, ENVIADA, INSTALADA, BAJA)

ETIQUETA_PLACA = {
    EMITIDA: "en stock",
    ASIGNADA: "asignada, sin enviar",
    ENVIADA: "en camino",
    INSTALADA: "puesta en la pared",
    BAJA: "dada de baja",
}


def estado_placa(eventos: list[tuple[str, datetime]]) -> str:
    return _ultimo(eventos) or EMITIDA


def placa_en_pared(estado: str) -> bool:
    return estado == INSTALADA


# ------------------------------------------------------------------ un paso

PENDIENTE = "pendiente"
COMUN = "comun"
ESPECIAL = "especial"

VEREDICTOS = (COMUN, ESPECIAL)

ETIQUETA_VEREDICTO = {
    PENDIENTE: "sin leer",
    COMUN: "leída",
    ESPECIAL: "✨ especial",
}


def veredicto(veredictos: list[tuple[str, datetime]]) -> str:
    """Una reflexion arranca pendiente y queda con lo ultimo que dijo un admin."""
    return _ultimo(veredictos) or PENDIENTE


# ------------------------------------------------------------------- nominar

PROPUESTA = "propuesta"
APROBADA = "aprobada"
RECHAZADA = "rechazada"

EVENTOS_NOMINACION = (PROPUESTA, APROBADA, RECHAZADA)


def estado_nominacion(eventos: list[tuple[str, datetime]]) -> str:
    return _ultimo(eventos) or PROPUESTA


# ------------------------------------------------------------------- formato


def hace(cuando: datetime, ahora: datetime) -> str:
    minutos = (ahora - cuando).total_seconds() / 60
    if minutos < 60:
        return "recién"
    horas = minutos / 60
    if horas < 24:
        return f"hace {int(horas)} h"
    dias = horas / 24
    if dias < 2:
        return "ayer"
    if dias < 45:
        return f"hace {int(dias)} días"
    meses = dias / 30
    if meses < 24:
        return f"hace {int(meses)} meses"
    return f"hace {int(meses / 12)} años"
