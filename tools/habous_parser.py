"""Analyse de la page HTML des Habous (horaire_hijri_2.php).

Ce module n'a aucune dépendance à Home Assistant afin d'être testable seul
et réutilisable par tools/build_data.py.

ATTENTION : la structure réelle de la page n'a pas pu être vérifiée au moment
de l'écriture (robots.txt). Le parseur est donc volontairement tolérant et
*strict sur le résultat* : si les dates reconstituées ne sont pas cohérentes,
il lève ParseError au lieu de produire des horaires faux.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from html.parser import HTMLParser

PRAYERS = ["fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"]
_TIME_RE = re.compile(r"^\s*(\d{1,2})\s*[:hH]\s*(\d{2})\s*$")
_INT_RE = re.compile(r"^\s*(\d{1,2})\s*$")


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
        valid = [(v, t) for v, t in options if v.strip().isdigit() and t]
        if len(valid) > len(best):
            best = valid
    if len(best) < 10:
        raise ParseError("Sélecteur de villes introuvable")
    return [{"id": int(v), "name": t} for v, t in best]


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
