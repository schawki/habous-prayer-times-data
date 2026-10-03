"""Contrôle des coordonnées des villes avec les horaires Habous eux-mêmes.

L'heure du Dhuhr d'une ville dépend presque uniquement de sa longitude (4 minutes par
degré). On peut donc retrouver la longitude « implicite » de chaque ville à partir de
son fichier d'horaires et la comparer à celle de l'adresse trouvée sur OpenStreetMap :
un écart de plus de TOLERANCE_DEG signale une mauvaise ville (ex. Marrakech trouvée près
de Tiznit). Aucune dépendance : testable seul.

Calibrage : sur 13 villes sûres et 17 jours (26/09-12/10/2026), le Dhuhr Habous est en
moyenne de 5,85 min (écart ±0,2) après le midi solaire local.
"""

from __future__ import annotations

import math
import re
from datetime import date

DHUHR_OFFSET_MIN = 5.85
TOLERANCE_DEG = 0.8  # ~3 minutes
MIN_PLACE_RANK = 16  # 16 = ville/commune ; en dessous : région, province, pays
PLACE_CLASSES = {"place", "boundary"}
# Maroc, Sahara, Sebta, Melilla
LAT_RANGE = (20.0, 37.5)
LON_RANGE = (-18.0, 0.0)
_OFFSET_RE = re.compile(r"^([+-])(\d{2}):(\d{2})$")


def offset_minutes(utc_offset: str | None) -> int | None:
    if not utc_offset or not (m := _OFFSET_RE.match(utc_offset)):
        return None
    total = int(m.group(2)) * 60 + int(m.group(3))
    return -total if m.group(1) == "-" else total


def equation_of_time(day: date) -> float:
    """Équation du temps en minutes (précision ~0,5 min)."""
    b = 2 * math.pi * (day.timetuple().tm_yday - 81) / 365
    return 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)


def implied_longitude(dhuhr_hhmm: str, day: date, utc_offset: str | None) -> float | None:
    """Longitude (degrés, négative à l'ouest) impliquée par l'heure du Dhuhr, ou None."""
    off = offset_minutes(utc_offset)
    if off is None:
        return None
    h, m = map(int, dhuhr_hhmm.split(":"))
    utc_min = h * 60 + m - off
    return (720 - equation_of_time(day) + DHUHR_OFFSET_MIN - utc_min) / 4


def city_implied_longitude(times: dict, utc_offset: str | None) -> float | None:
    """Médiane sur les jours du fichier (robuste aux arrondis d'une minute)."""
    values = []
    for iso, day_times in sorted(times.items())[:15]:
        lon = implied_longitude(day_times["dhuhr"], date.fromisoformat(iso), utc_offset)
        if lon is not None:
            values.append(lon)
    if not values:
        return None
    values.sort()
    return values[len(values) // 2]


def is_place(candidate: dict) -> bool:
    """Résultat OpenStreetMap = lieu habité (pas une rue, un pays ni une région)."""
    try:
        lat, lon = float(candidate["lat"]), float(candidate["lon"])
        rank = int(candidate.get("place_rank", 0))
    except (KeyError, TypeError, ValueError):
        return False
    return (
        candidate.get("class") in PLACE_CLASSES
        and rank >= MIN_PLACE_RANK
        and LAT_RANGE[0] <= lat <= LAT_RANGE[1]
        and LON_RANGE[0] <= lon <= LON_RANGE[1]
    )


def pick_candidate(candidates: list[dict], implied: float | None, tolerance: float = TOLERANCE_DEG):
    """(candidat, vérifié) ; vérifié = cohérent avec le Dhuhr. None si rien d'acceptable."""
    places = [c for c in candidates if is_place(c)]
    if not places:
        return None
    if implied is None:
        return places[0], False  # pas d'horaires pour contrôler : on garde le meilleur résultat
    best = min(places, key=lambda c: abs(float(c["lon"]) - implied))
    if abs(float(best["lon"]) - implied) <= tolerance:
        return best, True
    return None
