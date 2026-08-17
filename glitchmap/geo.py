"""Geometria minima: distancias y cajas de busqueda. Sin dependencias."""

from __future__ import annotations

import math

EARTH_RADIUS_M = 6_371_008.8


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos puntos sobre la esfera."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def bounding_box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """Caja (min_lat, max_lat, min_lon, max_lon) que contiene al circulo.

    Sirve para que SQL descarte el 99% de las filas antes de calcular haversine.
    """
    d_lat = math.degrees(radius_m / EARTH_RADIUS_M)
    cos_lat = math.cos(math.radians(lat))
    # Cerca de los polos la correccion por longitud explota; ahi abrimos a todo.
    if abs(cos_lat) < 1e-6:
        return (max(-90.0, lat - d_lat), min(90.0, lat + d_lat), -180.0, 180.0)
    d_lon = math.degrees(radius_m / (EARTH_RADIUS_M * cos_lat))
    return (
        max(-90.0, lat - d_lat),
        min(90.0, lat + d_lat),
        max(-180.0, lon - d_lon),
        min(180.0, lon + d_lon),
    )


def map_url(lat: float, lon: float) -> str:
    return f"https://maps.google.com/?q={lat:.6f},{lon:.6f}"


def format_distance(meters: float) -> str:
    if meters < 950:
        return f"{round(meters / 10) * 10} m"
    return f"{meters / 1000:.1f} km".replace(".", ",")
