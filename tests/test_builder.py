"""Tests du constructeur de données (sans accès réseau).

Lancer : python -m unittest discover -s tests -v
NB : la page HTML est SYNTHÉTIQUE (structure supposée) ; elle valide la logique,
pas la compatibilité avec la vraie page des Habous.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

TOOLS = Path(__file__).resolve().parent.parent / "tools"


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


parser = load("habous_parser")
check = load("citycheck")
build = load("build_data")


def cand(lat, lon, name="Ville", cls="place", rank=16):
    return {"lat": str(lat), "lon": str(lon), "name": name, "class": cls, "place_rank": rank}


def synthetic_page(start: date, n: int = 30) -> str:
    rows = []
    for i in range(n):
        d = start + timedelta(days=i)
        rows.append(
            f"<tr><td>{i + 1}</td><td>{d.day}</td><td>jour</td>"
            f"<td>05:{10 + i % 5:02d}</td><td>06:40</td><td>13:35</td>"
            f"<td>17:05</td><td>19:58</td><td>21:12</td></tr>"
        )
    cities = "".join(f'<option value="{i}">Ville {i}</option>' for i in range(1, 15))
    return f"<select name='ville'>{cities}</select><table>{''.join(rows)}</table>"


class ParserTests(unittest.TestCase):
    def test_month_crossing_two_gregorian_months(self):
        out = parser.parse_month(synthetic_page(date(2026, 9, 20)), today=date(2026, 10, 2))
        self.assertEqual(len(out), 30)
        self.assertEqual(out["2026-10-02"]["fajr"], "05:12")
        self.assertEqual(list(out)[0], "2026-09-20")

    def test_inconsistent_page_raises(self):
        html = synthetic_page(date(2026, 9, 20)).replace("<td>3</td><td>22</td>", "<td>3</td><td>9</td>")
        with self.assertRaises(parser.ParseError):
            parser.parse_month(html, today=date(2026, 10, 2))

    def test_garbage_raises(self):
        with self.assertRaises(parser.ParseError):
            parser.parse_month("<html>rien</html>", today=date(2026, 10, 2))


class BuilderTests(unittest.TestCase):
    def _run(self, argv, page):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(build, "http_get", return_value=page), \
             mock.patch.object(build, "geocode_candidates", return_value=[cand(34.0, -6.8)]) as geo, \
             mock.patch.object(build.time, "sleep"), \
             mock.patch.object(sys, "argv", ["build_data.py", "--data-dir", tmp, *argv]):
            code = build.main()
            files = {p.name: json.loads(p.read_text("utf-8")) for p in Path(tmp).rglob("*.json")}
            return code, files, geo

    def test_single_city_trial_writes_one_file_and_geocodes_once(self):
        page = synthetic_page(date.today() - timedelta(days=5))
        code, files, geo = self._run(["--city", "3"], page)
        self.assertEqual(code, 0)
        self.assertIn("3.json", files)
        self.assertEqual(sum(n.endswith(".json") and n[:-5].isdigit() for n in files), 1)
        self.assertEqual(geo.call_count, 1)
        self.assertEqual(files["3.json"]["timezone"], "Africa/Casablanca")
        self.assertNotIn("utc_offset", files["3.json"])

    def test_utc_offset_written_when_given(self):
        page = synthetic_page(date.today() - timedelta(days=5))
        _, files, _ = self._run(["--city", "3", "--utc-offset", "+00:00"], page)
        self.assertEqual(files["3.json"]["utc_offset"], "+00:00")

    def test_bad_offset_rejected(self):
        code, files, _ = self._run(["--utc-offset", "1h"], "")
        self.assertEqual(code, 2)
        self.assertEqual(files, {})

    def test_failure_writes_nothing(self):
        code, files, _ = self._run(["--city", "3"], "<html>rien</html>")
        self.assertEqual(code, 1)
        self.assertEqual(files, {})


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "habous_58_2026-10-03.html"


class RealPageTests(unittest.TestCase):
    """Page réelle (Casablanca) enregistrée le 2026-10-03."""

    html = FIXTURE.read_text("utf-8")

    def test_cities(self):
        cities = parser.parse_cities(self.html)
        self.assertEqual(len(cities), 191)
        self.assertEqual(cities[0], {"id": 1, "name": "الرباط"})
        self.assertIn(58, [c["id"] for c in cities])
        self.assertEqual(cities[-1]["id"], 322)

    def test_month(self):
        out = parser.parse_month(self.html, date(2026, 10, 3))
        self.assertEqual((min(out), max(out), len(out)), ("2026-09-13", "2026-10-12", 30))
        self.assertEqual(
            out["2026-10-03"],
            {"fajr": "04:58", "sunrise": "06:23", "dhuhr": "12:25",
             "asr": "15:41", "maghrib": "18:17", "isha": "19:30"},
        )

    def test_trial_city_58_from_real_page(self):
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(build, "http_get", return_value=self.html), \
             mock.patch.object(build, "geocode_candidates", return_value=[cand(33.59, -7.62, "Casablanca")]), \
             mock.patch.object(build.time, "sleep"), \
             mock.patch.object(build, "date") as fake_date, \
             mock.patch.object(sys, "argv", ["b", "--data-dir", tmp, "--city", "58", "--utc-offset", "+00:00"]):
            fake_date.today.return_value = date(2026, 10, 3)
            fake_date.side_effect = date
            self.assertEqual(build.main(), 0)
            data = json.loads((Path(tmp) / "times" / "58.json").read_text("utf-8"))
            cities = json.loads((Path(tmp) / "cities.json").read_text("utf-8"))["cities"]
        self.assertEqual(data["utc_offset"], "+00:00")
        self.assertEqual(data["days"]["2026-10-03"]["fajr"], "04:58")
        self.assertEqual(len(cities), 191)
        casa = next(c for c in cities if c["id"] == 58)
        self.assertEqual((casa["name_ar"], casa["name_fr"]), ("الدار البيضاء", "Casablanca"))
        self.assertNotIn("name_fr", next(c for c in cities if c["id"] == 1))


class SslTests(unittest.TestCase):
    CERT = Path(__file__).resolve().parent.parent / "certs" / "habous-intermediate.pem"

    def test_extra_ca_is_added_and_verification_stays_on(self):
        import ssl
        base = ssl.create_default_context().cert_store_stats()["x509_ca"]
        ctx = build.make_ssl_context(str(self.CERT))
        self.assertEqual(ctx.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(ctx.check_hostname)
        self.assertEqual(ctx.cert_store_stats()["x509_ca"], base + 1)

    def test_ca_bundle_option_is_wired(self):
        page = synthetic_page(date.today() - timedelta(days=5))
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(build, "http_get", return_value=page), \
             mock.patch.object(build, "geocode_candidates", return_value=[cand(34.0, -6.8)]), \
             mock.patch.object(build.time, "sleep"), \
             mock.patch.object(build, "_SSL_CONTEXT", None), \
             mock.patch.object(sys, "argv", ["b", "--data-dir", tmp, "--city", "3", "--ca-bundle", str(self.CERT)]):
            self.assertEqual(build.main(), 0)
            self.assertIsNotNone(build._SSL_CONTEXT)

    def test_workflow_passes_the_certificate(self):
        wf = (Path(__file__).resolve().parent.parent / ".github/workflows/update-data.yml").read_text("utf-8")
        self.assertIn("--ca-bundle certs/habous-intermediate.pem", wf)
        self.assertTrue(self.CERT.exists())


class CityCheckTests(unittest.TestCase):
    html = FIXTURE.read_text("utf-8")

    def test_casablanca_longitude_from_dhuhr(self):
        days = parser.parse_month(self.html, date(2026, 10, 3))
        lon = check.city_implied_longitude(days, "+00:00")
        self.assertAlmostEqual(lon, -7.6, delta=0.3)
        self.assertIsNone(check.city_implied_longitude(days, None))  # sans décalage, pas de contrôle

    def test_offset_matters(self):
        days = parser.parse_month(self.html, date(2026, 10, 3))
        self.assertAlmostEqual(
            check.city_implied_longitude(days, "+01:00") - check.city_implied_longitude(days, "+00:00"),
            15, delta=0.01,  # 12:25 à +01:00 = 11:25 UTC : midi plus tôt, donc plus à l’est
        )

    def test_is_place_rejects_streets_countries_and_far_away(self):
        self.assertTrue(check.is_place(cand(31.63, -8.0, "Marrakech")))
        self.assertFalse(check.is_place(cand(33.58, -7.62, "Rue de Sebta", cls="highway", rank=26)))
        self.assertFalse(check.is_place(cand(28.3, -10.4, "Maroc", cls="boundary", rank=4)))
        self.assertFalse(check.is_place(cand(48.85, 2.35, "Paris")))
        self.assertFalse(check.is_place({"lat": "x"}))

    def test_pick_candidate_uses_dhuhr(self):
        implied = -8.0  # Marrakech d'après son Dhuhr
        wrong, right = cand(28.33, -10.37, "Tiznit"), cand(31.63, -7.98, "Marrakech")
        self.assertEqual(check.pick_candidate([wrong, right], implied), (right, True))
        self.assertIsNone(check.pick_candidate([wrong], implied))
        self.assertEqual(check.pick_candidate([wrong], None), (wrong, False))
        self.assertIsNone(check.pick_candidate([], implied))


class NameVariantTests(unittest.TestCase):
    def test_fold_and_variants(self):
        self.assertEqual(check.fold_arabic("آيت أَنزاران"), "ايت انزاران")
        v = check.name_variants("اكودال املشيل ميدلت")
        self.assertEqual(v[0], "اكودال املشيل ميدلت, المغرب")
        self.assertIn("اكودال املشيل, المغرب", v)
        self.assertEqual(len(v), len(set(v)))
        short = check.name_variants("آيت القاق")
        self.assertNotIn("ايت, المغرب", short)
        self.assertIn("القاق, المغرب", short)


class RefineTests(unittest.TestCase):
    """Reproduit l'erreur réelle : Marrakech géocodée près de Tiznit avec le nom « Maroc »."""

    def _run(self, cities, found):
        page = synthetic_page(date.today())
        days = parser.parse_month(page, date.today())
        # Dhuhr 13:35 +00:00 -> longitude implicite ~ -22° : on fixe plutôt Dhuhr à 12:25 (≈ -7,6°)
        days = {d: {**t, "dhuhr": "12:25"} for d, t in days.items()}
        with tempfile.TemporaryDirectory() as tmp:
            for c in cities:
                (Path(tmp) / "times").mkdir(exist_ok=True)
                (Path(tmp) / "times" / f"{c['id']}.json").write_text(
                    json.dumps({"days": days, "utc_offset": "+00:00"}), "utf-8")
            with mock.patch.object(build, "geocode_candidates", return_value=found) as geo, \
                 mock.patch.object(build, "load_curated", return_value={}):
                report = build.refine_coordinates(cities, Path(tmp))
            return report, geo

    def test_incoherent_coordinates_and_name_are_replaced(self):
        city = {"id": 104, "name_ar": "مراكش", "name_fr": "Maroc", "lat": 28.33, "lon": -10.37}
        report, geo = self._run([city], [cand(31.63, -7.6, "Marrakech")])
        self.assertEqual(report["removed"], [104])
        self.assertEqual((city["lat"], city["lon"], city["name_fr"]), (31.63, -7.6, "Marrakech"))
        self.assertTrue(city["verified"])

    def test_coherent_coordinates_are_kept_without_any_request(self):
        city = {"id": 58, "name_ar": "الدار البيضاء", "name_fr": "Casablanca", "lat": 33.59, "lon": -7.62}
        report, geo = self._run([city], [])
        self.assertEqual(geo.call_count, 0)
        self.assertEqual(report, {"removed": [], "unverified": [], "missing": []})
        self.assertTrue(city["verified"])

    def test_no_acceptable_candidate_leaves_city_without_coordinates(self):
        city = {"id": 9, "name_ar": "مدينة"}
        report, _ = self._run([city], [cand(28.0, -10.0, "Loin")])
        self.assertEqual(report["missing"], [9])
        self.assertNotIn("lat", city)

    def test_curated_file_is_well_formed(self):
        curated = json.loads((TOOLS / "cities_curated.json").read_text("utf-8"))
        entries = {k: v for k, v in curated.items() if not k.startswith("_")}
        self.assertGreaterEqual(len(entries), 20)
        for key, value in entries.items():
            self.assertTrue(key.isdigit(), key)
            self.assertTrue(value["name_fr"])
            if "lat" in value:
                self.assertTrue(check.LAT_RANGE[0] <= value["lat"] <= check.LAT_RANGE[1], key)
                self.assertTrue(check.LON_RANGE[0] <= value["lon"] <= check.LON_RANGE[1], key)

    def test_curated_entries_apply_and_verified(self):
        page = (FIXTURE).read_text("utf-8")
        with tempfile.TemporaryDirectory() as tmp, \
             mock.patch.object(build, "http_get", return_value=page), \
             mock.patch.object(build, "geocode_candidates", return_value=[]), \
             mock.patch.object(build.time, "sleep"), \
             mock.patch.object(sys, "argv", ["b", "--data-dir", tmp, "--city", "58"]):
            self.assertEqual(build.main(), 0)
            cities = {c["id"]: c for c in json.loads((Path(tmp) / "cities.json").read_text("utf-8"))["cities"]}
        self.assertEqual(cities[104]["name_fr"], "Marrakech")
        self.assertEqual(cities[104]["lat"], 31.6295)
        self.assertEqual(cities[40]["name_fr"], "Melilla")
        self.assertTrue(cities[24]["verified"])


class FreshnessTests(unittest.TestCase):
    """--skip-if-fresh : aucune requête quand tous les fichiers couvrent déjà la période."""

    TODAY = date(2026, 10, 3)

    def _write(self, tmp, covered_until):
        (Path(tmp) / "times").mkdir(exist_ok=True)
        (Path(tmp) / "cities.json").write_text(json.dumps({"cities": [{"id": 1}, {"id": 2}]}), "utf-8")
        for cid, last in covered_until.items():
            days = {(self.TODAY + timedelta(days=i)).isoformat(): {} for i in range((last - self.TODAY).days + 1)}
            (Path(tmp) / "times" / f"{cid}.json").write_text(json.dumps({"days": days}), "utf-8")

    def test_fresh_when_every_city_covers_today(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, {1: date(2026, 10, 12), 2: date(2026, 10, 12)})
            self.assertFalse(build.needs_refresh(Path(tmp), 0, self.TODAY))

    def test_refresh_when_one_city_expired_or_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, {1: date(2026, 10, 12), 2: date(2026, 10, 2)})
            self.assertTrue(build.needs_refresh(Path(tmp), 0, self.TODAY))
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, {1: date(2026, 10, 12)})  # fichier de la ville 2 absent
            self.assertTrue(build.needs_refresh(Path(tmp), 0, self.TODAY))

    def test_lookahead_widens_the_margin(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._write(tmp, {1: date(2026, 10, 5), 2: date(2026, 10, 5)})
            self.assertFalse(build.needs_refresh(Path(tmp), 0, self.TODAY))
            self.assertTrue(build.needs_refresh(Path(tmp), 7, self.TODAY))

    def test_refresh_when_no_city_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(build.needs_refresh(Path(tmp), 0, self.TODAY))

    def test_main_skips_without_any_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            today = date.today()
            (Path(tmp) / "times").mkdir()
            (Path(tmp) / "cities.json").write_text(json.dumps({"cities": [{"id": 1}]}), "utf-8")
            days = {(today + timedelta(days=i)).isoformat(): {} for i in range(5)}
            (Path(tmp) / "times" / "1.json").write_text(json.dumps({"days": days}), "utf-8")
            with mock.patch.object(build, "http_get", side_effect=AssertionError("réseau interdit")), \
                 mock.patch.object(sys, "argv", ["b", "--data-dir", tmp, "--lookahead", "0", "--skip-if-fresh"]):
                self.assertEqual(build.main(), 0)

    def test_workflow_is_scheduled_and_automatic_runs_stay_gentle(self):
        wf = (Path(__file__).resolve().parent.parent / ".github/workflows/update-data.yml").read_text("utf-8")
        self.assertRegex(wf, r"(?m)^  schedule:")
        self.assertIn("--skip-if-fresh", wf)
        self.assertIn("--no-geocode", wf)
        self.assertIn("--lookahead 0", wf)


class DocsTests(unittest.TestCase):
    def test_format_doc_covers_every_published_field(self):
        root = Path(__file__).resolve().parent.parent
        doc = (root / "docs" / "DATA_FORMAT.md").read_text("utf-8")
        for field in ("id", "name_ar", "name_fr", "lat", "lon", "verified", "city_id", "timezone",
                      "utc_offset", "updated", "days", "fajr", "sunrise", "dhuhr", "asr", "maghrib", "isha"):
            self.assertIn(f"`{field}`", doc, field)
        self.assertIn("docs/DATA_FORMAT.md", (root / "README.md").read_text("utf-8"))
