#!/usr/bin/env python3
"""Construit les fichiers JSON (data/) à partir de habous.gov.ma.

Exécuté par le workflow GitHub (.github/workflows/update-data.yml), ou à la main :

    python tools/build_data.py --data-dir data                 # toutes les villes
    python tools/build_data.py --data-dir /tmp/essai --city 58 # essai sur UNE ville

Principes :
- 1 requête / ville seulement quand le cache couvre moins de --lookahead jours
  (donc ~1 passage complet par mois hijri), avec une pause entre requêtes ;
- géocodage des villes (OpenStreetMap Nominatim, 1 req/s) une seule fois,
  les coordonnées sont ensuite conservées dans data/cities.json ;
- aucune donnée n'est écrite si le parseur lève une erreur (pas d'horaires faux).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TIMEZONE = "Africa/Casablanca"
HABOUS_URL = "https://www.habous.gov.ma/prieres/horaire_hijri_2.php"
NOMINATIM = "https://nominatim.openstreetmap.org/search"
UA = "habous-prayer-times-data/0.1 (+https://github.com/schawki/habous-prayer-times-data; non-commercial personal use)"
_SSL_CONTEXT: ssl.SSLContext | None = None
ARABIC = re.compile(r"[؀-ۿ]")


def _load_parser():
    spec = importlib.util.spec_from_file_location("habous_parser", Path(__file__).with_name("habous_parser.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


parser = _load_parser()


def make_ssl_context(extra_ca_file: str) -> ssl.SSLContext:
    """Certificats du système + un fichier supplémentaire (la vérification reste active)."""
    ctx = ssl.create_default_context()
    ctx.load_verify_locations(cafile=extra_ca_file)
    return ctx


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
        return resp.read().decode("utf-8", errors="replace")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n", "utf-8")


def geocode(name: str) -> tuple[float, float, str | None] | None:
    """(lat, lon, nom français ou None) ; le nom français vient d'OpenStreetMap."""
    query = urllib.parse.urlencode(
        {"q": f"{name}, Maroc", "format": "json", "limit": 1, "accept-language": "fr"}
    )
    try:
        results = json.loads(http_get(f"{NOMINATIM}?{query}"))
    except Exception as err:  # noqa: BLE001
        print(f"  géocodage échoué pour {name}: {err}")
        return None
    time.sleep(1.1)
    if not results:
        return None
    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    # Garde-fou : Maroc, Sahara occidental, Sebta et Melilla.
    if not (20.0 <= lat <= 37.5 and -18.0 <= lon <= 0.0):
        print(f"  coordonnées hors du Maroc pour {name}: {lat},{lon} -> ignorées")
        return None
    name_fr = results[0].get("name") or results[0].get("display_name", "").split(",")[0].strip()
    if not name_fr or ARABIC.search(name_fr):
        name_fr = None  # OSM n'a pas de nom français : on garde l'arabe
    return round(lat, 4), round(lon, 4), name_fr


def build_cities(data_dir: Path, delay: float, only: int | None = None) -> list[dict]:
    """Liste des villes (1 requête Habous) ; géocodage seulement pour les nouvelles."""
    path = data_dir / "cities.json"
    existing = {int(c["id"]): c for c in read_json(path, {}).get("cities", [])}
    html = http_get(f"{HABOUS_URL}?ville=58")
    time.sleep(delay)
    listed = parser.parse_cities(html)

    cities = []
    for item in listed:
        cid, label = item["id"], item["name"]
        city = existing.get(cid, {"id": cid})
        key = "name_ar" if ARABIC.search(label) else "name_fr"
        city[key] = label
        if city.get("lat") is None and only in (None, cid):
            found = geocode(city.get("name_fr") or label)
            if found:
                city["lat"], city["lon"] = found[0], found[1]
                if not city.get("name_fr") and found[2]:
                    city["name_fr"] = found[2]
        cities.append(city)
    cities.sort(key=lambda c: c["id"])
    write_json(path, {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cities": cities})
    missing = [c["id"] for c in cities if c.get("lat") is None]
    print(f"{len(cities)} villes, {len(missing)} sans coordonnées {missing[:10]}")
    return cities


def times_payload(cid: int, days: dict, utc_offset: str | None) -> dict:
    """Contenu d'un fichier times/<id>.json (le décalage n'est écrit que s'il est fourni)."""
    payload = {
        "city_id": cid,
        "timezone": TIMEZONE,
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "days": days,
    }
    if utc_offset:
        payload["utc_offset"] = utc_offset
    return payload


def build_times(
    cities: list[dict], data_dir: Path, lookahead: int, delay: float, utc_offset: str | None = None
) -> tuple[int, int]:
    today = date.today()
    horizon = (today + timedelta(days=lookahead)).isoformat()
    ok = failed = 0
    for city in cities:
        cid = city["id"]
        path = data_dir / "times" / f"{cid}.json"
        current = read_json(path, {"days": {}})
        days = current.get("days", {})
        if days and max(days) >= horizon:
            continue
        try:
            html = http_get(f"{HABOUS_URL}?ville={cid}")
            fresh = parser.parse_month(html, today)
        except Exception as err:  # noqa: BLE001
            print(f"ville {cid}: ÉCHEC ({err})")
            failed += 1
            time.sleep(delay)
            continue
        days.update(fresh)
        cutoff = (today - timedelta(days=7)).isoformat()
        days = {d: t for d, t in days.items() if d >= cutoff}
        write_json(path, times_payload(cid, days, utc_offset))
        ok += 1
        time.sleep(delay)
    return ok, failed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--lookahead", type=int, default=3, help="jours de marge avant re-scraping")
    ap.add_argument("--delay", type=float, default=2.0, help="pause (s) entre deux requêtes Habous")
    ap.add_argument("--city", type=int, help="ne traiter que cette ville (essai) ; ex. 58")
    ap.add_argument("--utc-offset", help='décalage UTC écrit dans les fichiers, ex. "+00:00" (facultatif)')
    ap.add_argument("--ca-bundle", help="fichier de certificats (chaîne complète du site Habous)")
    args = ap.parse_args()
    data_dir = Path(args.data_dir)
    if args.utc_offset and not re.fullmatch(r"[+-]\d{2}:\d{2}", args.utc_offset):
        print("--utc-offset doit ressembler à +00:00 ou +01:00")
        return 2
    if args.ca_bundle:
        global _SSL_CONTEXT
        _SSL_CONTEXT = make_ssl_context(args.ca_bundle)

    try:
        cities = build_cities(data_dir, args.delay, args.city)
    except Exception as err:  # noqa: BLE001
        print(f"Impossible de construire la liste des villes : {err}")
        return 1
    if args.city is not None:
        cities = [c for c in cities if c["id"] == args.city]
        if not cities:
            print(f"Ville {args.city} absente de la liste Habous")
            return 1
    ok, failed = build_times(cities, data_dir, args.lookahead, args.delay, args.utc_offset)
    print(f"Horaires : {ok} villes mises à jour, {failed} échecs")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
