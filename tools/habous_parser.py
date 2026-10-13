"""Analyse de la page HTML des Habous (horaire_hijri_2.php).

Ce module n'a aucune dépendance à Home Assistant afin d'être testable seul
et réutilisable par tools/build_data.py.

Vérifié le 2026-10-03 sur une vraie page (tests/fixtures/habous_58_2026-10-03.html) :
191 villes, 30 jours par page. Le parseur reste *strict sur le résultat* : si les
dates reconstituées ne sont pas cohérentes, il lève ParseError au lieu de produire
des horaires faux.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from html.parser import HTMLParser

PRAYERS = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
# Hijri months as written in the page header (e.g. "ربيع الآخر 1448"), normalised by _norm_ar.
_HIJRI_MONTHS = {
    "محرم": 1, "صفر": 2, "ربيع الاول": 3, "ربيع الاخر": 4, "ربيع الثاني": 4,
    "جمادى الاولى": 5, "جمادى الاول": 5, "جمادى الاخرة": 6, "جمادى الثانية": 6,
    "رجب": 7, "شعبان": 8, "رمضان": 9, "شوال": 10,
    "ذو القعدة": 11, "ذي القعدة": 11, "ذو الحجة": 12, "ذي الحجة": 12,
}
_TIME_RE = re.compile(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{2})\s*$")
_INT_RE = re.compile(r"^\s*(\d{1,2})\s*$")
# Les options du sélecteur valent « index.php?ville=58 » sur la vraie page.
_CITY_ID_RE = re.compile(r"(?:ville=)?(\d+)\s*$")


class ParseError(Exception):
    """La page n'a pas la structure attendue."""


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.selects: list[list[tuple[str, str]]] = []
        self._cell: list[str] | None = None
        self._row: list[str] | None = None
        self._option_value: str | None = None
        self._option_text: list[str] = []
        self._in_select = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []
        elif tag == "select":
            self._in_select = True
            self.selects.append([])
        elif tag == "option" and self._in_select:
            self._option_value = a.get("value", "")
            self._option_text = []

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        if self._option_value is not None:
            self._option_text.append(data)

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "option" and self._option_value is not None:
            text = " ".join("".join(self._option_text).split())
            self.selects[-1].append((self._option_value, text))
            self._option_value = None
        elif tag == "select":
            self._in_select = False


def _norm_time(cell: str) -> str | None:
    m = _TIME_RE.match(cell)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def parse_cities(html: str) -> list[dict[str, str]]:
    """Extrait la liste (id, nom) du sélecteur de villes."""
    p = _PageParser()
    p.feed(html)
    best: list[tuple[str, str]] = []
    for options in p.selects:
        valid = [(v, t) for v, t in options if _CITY_ID_RE.search(v.strip()) and t]
        if len(valid) > len(best):
            best = valid
    if len(best) < 10:
        raise ParseError("Sélecteur de villes introuvable")
    return [{"id": int(_CITY_ID_RE.search(v.strip()).group(1)), "name": t} for v, t in best]


def parse_month(html: str, today: date) -> dict[str, dict[str, str]]:
    """Retourne {YYYY-MM-DD: {fajr, sunrise, dhuhr, asr, maghrib, isha}}.

    La page couvre le mois hijri en cours : on ancre les lignes sur `today`
    grâce à la colonne du jour grégorien, puis on vérifie la cohérence de
    toutes les lignes.
    """
    p = _PageParser()
    p.feed(html)

    parsed: list[tuple[list[str], list[str]]] = []  # (heures, cellules)
    for cells in p.rows:
        times = [t for t in (_norm_time(c) for c in cells) if t]
        if len(times) >= 6:
            parsed.append((times[:6], cells))
    if len(parsed) < 20:
        raise ParseError(f"Seulement {len(parsed)} lignes d'horaires trouvées")

    n = len(parsed)
    # Colonnes entières (jour hijri séquentiel, jour grégorien avec rupture).
    width = min(len(cells) for _, cells in parsed)
    candidates: list[list[int]] = []
    for col in range(width):
        values = []
        for _, cells in parsed:
            m = _INT_RE.match(cells[col])
            if not m:
                break
            values.append(int(m.group(1)))
        else:
            if all(1 <= v <= 31 for v in values):
                candidates.append(values)
    sequential = list(range(1, n + 1))
    gregorian = [c for c in candidates if c != sequential]
    if len(gregorian) != 1:
        raise ParseError("Colonne du jour grégorien non identifiable")
    days = gregorian[0]

    try:
        anchor = days.index(today.day)
    except ValueError as err:
        raise ParseError("Le jour courant est absent du tableau") from err

    result: dict[str, dict[str, str]] = {}
    for i, (times, _) in enumerate(parsed):
        d = today + timedelta(days=i - anchor)
        if d.day != days[i]:
            raise ParseError(f"Dates incohérentes à la ligne {i + 1}")
        result[d.isoformat()] = dict(zip(PRAYERS, times))
    return result


def _norm_ar(text: str) -> str:
    """Arabic text without diacritics, with hamza/alef, ya and ta marbuta variants merged."""
    text = re.sub(r"[\u064B-\u0652\u0640]", "", text)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        text = text.replace(a, b)
    return " ".join(text.split())


def parse_hijri_header(html: str) -> tuple[int, int] | None:
    """(year, month 1-12) from the page header such as "ربيع الآخر 1448", else None."""
    text = _norm_ar(re.sub(r"<[^>]+>", " ", html))
    names = sorted(((_norm_ar(n), m) for n, m in _HIJRI_MONTHS.items()), key=lambda x: -len(x[0]))
    for name, month in names:
        m = re.search(re.escape(name) + r"\s+(1[3-5]\d\d)\b", text)
        if m:
            return int(m.group(1)), month
    return None


def parse_hijri(html: str, today: date) -> dict[str, dict[str, int]]:
    """{YYYY-MM-DD: {"y": year, "m": month, "d": day}} for the month shown by the page.

    The page lists the days of one Hijri month in order, so row i is Hijri day i + 1. This is
    optional information: any problem (header missing, page not parseable) gives {} and never
    prevents the prayer times themselves from being published."""
    try:
        header = parse_hijri_header(html)
        if header is None:
            return {}
        dates = sorted(parse_month(html, today))
    except ParseError:
        return {}
    year, month = header
    if not 29 <= len(dates) <= 30:
        return {}
    return {d: {"y": year, "m": month, "d": i + 1} for i, d in enumerate(dates)}
