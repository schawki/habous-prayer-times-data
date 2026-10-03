#!/usr/bin/env python3
"""Construit les fichiers JSON (data/) à partir de habous.gov.ma.

Exécuté par le workflow GitHub (.github/workflows/update-data.yml), ou à la main :

    python tools/build_data.py --data-dir data                 # toutes les villes
    python tools/build_data.py --data-dir /tmp/essai --city 58 # essai sur UNE ville

Principes :
- 1 requête / ville seulement quand le cache couvre moins de --lookahead jours
  (donc ~1 passage complet par mois hijri), avec une pause entre requêtes ;
- coordonnées des villes : fichier relu à la main (cities_curated.json), sinon recherche
  OpenStreetMap (Nominatim, 1 req/s) en ne gardant que les lieux habités ; chaque résultat
  est contrôlé avec l'heure du Dhuhr de la ville (tools/citycheck.py), les incohérents
  sont écartés. Les coordonnées sont conservées dans data/cities.json ;
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


def _load_check():
    spec = importlib.util.spec_from_file_location("citycheck", Path(__file__).with_name("citycheck.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check = _load_check()
CURATED_FILE = Path(__file__).with_name("cities_curated.json")


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


def geocode_candidates(name: str) -> list[dict]:
    """Résultats OpenStreetMap (jusqu'à 5) pour un nom, noms en français quand ils existent."""
    query = urllib.parse.urlencode({
        "q": name, "format": "json", "limit": 5, "accept-language": "fr",
        "countrycodes": "ma,eh,es", "addressdetails": 0,
    })
    try:
        results = json.loads(http_get(f"{NOMINATIM}?{query}"))
    except Exception as err:  # noqa: BLE001
        print(f"  recherche échouée pour {name}: {err}")
        results = []
    time.sleep(1.1)
    return results if isinstance(results, list) else []


def load_curated() -> dict[int, dict]:
    return {int(k): v for k, v in read_json(CURATED_FILE, {}).items() if not k.startswith("_")}


def build_cities(data_dir: Path, delay: float) -> list[dict]:
    """Liste des villes (1 requête Habous) ; le fichier relu à la main prime sur tout."""
    path = data_dir / "cities.json"
    existing = {int(c["id"]): c for c in read_json(path, {}).get("cities", [])}
    html = http_get(f"{HABOUS_URL}?ville=58")
    time.sleep(delay)
    listed = parser.parse_cities(html)
    curated = load_curated()

    cities = []
    for item in listed:
        cid, label = item["id"], item["name"]
        city = existing.get(cid, {"id": cid})
        key = "name_ar" if ARABIC.search(label) else "name_fr"
        city[key] = label
        if cid in curated:
            for field in ("name_fr", "lat", "lon"):
                if curated[cid].get(field) is not None:
                    city[field] = curated[cid][field]
            if curated[cid].get("lat") is not None:
                city["verified"] = True
        cities.append(city)
    cities.sort(key=lambda c: c["id"])
    save_cities(path, cities)
    return cities


def save_cities(path: Path, cities: list[dict]) -> None:
    write_json(path, {"updated": datetime.now(timezone.utc).isoformat(timespec="seconds"), "cities": cities})


def refine_coordinates(
    cities: list[dict], data_dir: Path, only: int | None = None, utc_offset: str | None = None
) -> dict[str, list[int]]:
    """Contrôle (et au besoin cherche) les coordonnées avec l'heure du Dhuhr de chaque ville."""
    curated = load_curated()
    report: dict[str, list[int]] = {"removed": [], "unverified": [], "missing": []}
    for city in cities:
        cid = city["id"]
        if only not in (None, cid) or (cid in curated and curated[cid].get("lat") is not None):
            continue
        payload = read_json(data_dir / "times" / f"{cid}.json", {})
        implied = check.city_implied_longitude(
            payload.get("days", {}), payload.get("utc_offset") or utc_offset
        )
        if city.get("lat") is not None:
            if implied is None or abs(city["lon"] - implied) <= check.TOLERANCE_DEG:
                city["verified"] = implied is not None
                continue
            report["removed"].append(cid)  # coordonnées incompatibles avec les horaires
            for field in ("lat", "lon", "verified"):
                city.pop(field, None)
            if cid not in curated or not curated[cid].get("name_fr"):
                city.pop("name_fr", None)  # le nom venait de la même mauvaise recherche
        names = [n for n in (city.get("name_ar"), city.get("name_fr")) if n]
        picked = None
        for name in names:
            picked = check.pick_candidate(geocode_candidates(f"{name}, المغرب" if ARABIC.search(name) else f"{name}, Maroc"), implied)
            if picked:
                break
        if not picked:
            report["missing"].append(cid)
            continue
        cand, verified = picked
        city["lat"], city["lon"] = round(float(cand["lat"]), 4), round(float(cand["lon"]), 4)
        if verified:
            city["verified"] = True
        else:
            report["unverified"].append(cid)
        name_fr = cand.get("name") or ""
        if not city.get("name_fr") and name_fr and not ARABIC.search(name_fr):
            city["name_fr"] = name_fr
    return report


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
        all_cities = build_cities(data_dir, args.delay)
    except Exception as err:  # noqa: BLE001
        print(f"Impossible de construire la liste des villes : {err}")
        return 1
    cities = all_cities
    if args.city is not None:
        cities = [c for c in all_cities if c["id"] == args.city]
        if not cities:
            print(f"Ville {args.city} absente de la liste Habous")
            return 1
    ok, failed = build_times(cities, data_dir, args.lookahead, args.delay, args.utc_offset)
    report = refine_coordinates(cities, data_dir, args.city, args.utc_offset)
    save_cities(data_dir / "cities.json", all_cities)  # toujours la liste complète
    without = [c["id"] for c in cities if c.get("lat") is None]
    print(
        f"Coordonnées : {sum(1 for c in cities if c.get('verified'))} vérifiées, "
        f"{len(report['removed'])} retirées car incohérentes avec les horaires {report['removed']}, "
        f"{len(report['unverified'])} non vérifiables {report['unverified']}, "
        f"{len(without)} sans coordonnées {without} (à renseigner dans tools/cities_curated.json)"
    )
    print(f"Horaires : {ok} villes mises à jour, {failed} échecs")
    return 1 if failed and not ok else 0


if __name__ == "__main__":
    sys.exit(main())
