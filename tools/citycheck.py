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


def format_offset(minutes: int) -> str:
    """90 -> "+01:30", -60 -> "-01:00"."""
    sign = "-" if minutes < 0 else "+"
    return f"{sign}{abs(minutes) // 60:02d}:{abs(minutes) % 60:02d}"


# Déduction du décalage de l'heure légale à partir des heures publiées (voir infer_offset).
MIN_CITIES_FOR_OFFSET = 20   # au moins autant de villes aux coordonnées vérifiées
OFFSET_STEP_MIN = 30         # les décalages légaux sont des multiples de 30 minutes
OFFSET_ROUND_TOLERANCE = 10  # écart maximal entre la médiane et le multiple retenu (minutes)
OFFSET_AGREEMENT = 0.9       # part des villes à moins de 15 minutes de la médiane
OFFSET_SPREAD_MIN = 15


def infer_offset(day: date, samples: list[tuple[float, str]]) -> str | None:
    """Décalage de l'heure légale ("+00:00") déduit des Dhuhr publiés ce jour-là, ou None.

    `samples` : (longitude vérifiée, Dhuhr "HH:MM") pour des villes différentes. Pour chacune,
    l'écart entre l'heure publiée et le midi solaire calculé à sa longitude vaut le décalage
    légal, à quelques minutes près. On prend la médiane, arrondie à 30 minutes ; si les villes
    sont trop peu nombreuses ou en désaccord, ou si la médiane n'est pas proche d'un multiple
    de 30 minutes, on renvoie None plutôt que de deviner.
    """
    estimates = []
    for lon, hhmm in samples:
        h, m = map(int, hhmm.split(":"))
        solar_noon = 720 - equation_of_time(day) + DHUHR_OFFSET_MIN - 4 * lon  # minutes UTC
        estimates.append(h * 60 + m - solar_noon)
    if len(estimates) < MIN_CITIES_FOR_OFFSET:
        return None
    estimates.sort()
    median = estimates[len(estimates) // 2]
    close = sum(1 for e in estimates if abs(e - median) <= OFFSET_SPREAD_MIN)
    if close / len(estimates) < OFFSET_AGREEMENT:
        return None
    rounded = round(median / OFFSET_STEP_MIN) * OFFSET_STEP_MIN
    if abs(median - rounded) > OFFSET_ROUND_TOLERANCE:
        return None
    return format_offset(int(rounded))


def city_implied_longitude(
    times: dict, utc_offset: str | None, offsets: dict | None = None
) -> float | None:
    """Médiane sur les jours du fichier (robuste aux arrondis d'une minute).

    `offsets` : décalage par jour (prioritaire sur `utc_offset`) quand le fichier en contient."""
    values = []
    for iso, day_times in sorted(times.items())[:15]:
        lon = implied_longitude(day_times["dhuhr"], date.fromisoformat(iso), (offsets or {}).get(iso) or utc_offset)
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


_ARABIC_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ى": "ي", "ة": "ه", "ؤ": "و", "ئ": "ي"})
_DIACRITICS = re.compile("[\u064b-\u0652\u0640]")


def fold_arabic(text: str) -> str:
    """Graphie simplifiée (أ/إ/آ → ا, ة → ه, ى → ي, sans voyelles) : les noms Habous et OSM
    ne s'écrivent pas toujours pareil."""
    return _DIACRITICS.sub("", text).translate(_ARABIC_FOLD)


def name_variants(name_ar: str | None, name_fr: str | None = None) -> list[str]:
    """Requêtes à essayer, de la plus précise à la plus large (sans doublons)."""
    out: list[str] = []

    def add(q: str) -> None:
        q = " ".join(q.split())
        if q and q not in out:
            out.append(q)

    if name_ar:
        folded = fold_arabic(name_ar)
        for base in (name_ar, folded):
            add(f"{base}, المغرب")
        words = folded.split()
        if len(words) > 1:
            add(f"{' '.join(words[:2])}, المغرب")  # ex. « اكودال املشيل ميدلت » → « اكودال املشيل »
            if len(words[0]) > 3:
                add(f"{words[0]}, المغرب")  # pas un préfixe courant (آيت, بئر…)
            else:
                add(f"{' '.join(words[1:])}, المغرب")
        add(f"دوار {folded}, المغرب")
        add(f"جماعة {folded}, المغرب")
        add(name_ar)
    if name_fr:
        add(f"{name_fr}, Maroc")
    return out


