"""Indice de estabilidad de un glitch.

Toda la salud de un lugar sale de dos cosas: las senales que dejo la gente y
cuanto hace que nadie lo toca. Nada se borra ni se edita: un lugar que dejo de
servir simplemente pierde estabilidad hasta desvanecerse de los escaneos.
"""

from __future__ import annotations

from datetime import datetime, timedelta

BASE_SCORE = 55.0
CONFIRM_WEIGHT = 9.0
COLLAPSE_WEIGHT = -22.0
HALF_LIFE_DAYS = 30.0  # una senal pesa la mitad cada 30 dias
SILENCE_GRACE_DAYS = 45.0  # a partir de aca, el silencio erosiona
SILENCE_PENALTY_PER_DAY = 0.5
SILENCE_PENALTY_MAX = 30.0

CONFIRM = "confirm"
COLLAPSE = "collapse"

FADED_BELOW = 25  # por debajo de esto no aparece en un escaneo normal


def _decay(age_days: float) -> float:
    return 0.5 ** (max(0.0, age_days) / HALF_LIFE_DAYS)


def stability(
    created_at: datetime,
    signals: list[tuple[str, datetime]],
    now: datetime,
) -> int:
    """Devuelve un entero 0-100. Funcion pura: mismo input, mismo output."""
    score = BASE_SCORE
    for kind, when in signals:
        age_days = (now - when).total_seconds() / 86400.0
        weight = CONFIRM_WEIGHT if kind == CONFIRM else COLLAPSE_WEIGHT
        score += weight * _decay(age_days)

    last_touch = max((when for _, when in signals), default=created_at)
    silence_days = (now - last_touch).total_seconds() / 86400.0
    if silence_days > SILENCE_GRACE_DAYS:
        penalty = (silence_days - SILENCE_GRACE_DAYS) * SILENCE_PENALTY_PER_DAY
        score -= min(SILENCE_PENALTY_MAX, penalty)

    return int(max(0, min(100, round(score))))


def label(score: int) -> str:
    if score >= 75:
        return "ESTABLE"
    if score >= 50:
        return "FLUCTUANTE"
    if score >= FADED_BELOW:
        return "INESTABLE"
    return "DESVANECIDO"


def bar(score: int, width: int = 10) -> str:
    filled = round(score / 100 * width)
    return "▰" * filled + "▱" * (width - filled)


def is_faded(score: int) -> bool:
    return score < FADED_BELOW


def humanize_age(when: datetime, now: datetime) -> str:
    delta: timedelta = now - when
    minutes = delta.total_seconds() / 60
    if minutes < 60:
        return "hace minutos"
    hours = minutes / 60
    if hours < 24:
        return f"hace {int(hours)} h"
    days = hours / 24
    if days < 2:
        return "ayer"
    if days < 45:
        return f"hace {int(days)} dias"
    months = days / 30
    if months < 24:
        return f"hace {int(months)} meses"
    return f"hace {int(months / 12)} anios"
