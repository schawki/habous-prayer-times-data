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
build = load("build_data")


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
             mock.patch.object(build, "geocode", return_value=(34.0, -6.8, "Ville")) as geo, \
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
             mock.patch.object(build, "geocode", return_value=(33.57, -7.59, "Casablanca")), \
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
             mock.patch.object(build, "geocode", return_value=(34.0, -6.8, "Ville")), \
             mock.patch.object(build.time, "sleep"), \
             mock.patch.object(build, "_SSL_CONTEXT", None), \
             mock.patch.object(sys, "argv", ["b", "--data-dir", tmp, "--city", "3", "--ca-bundle", str(self.CERT)]):
            self.assertEqual(build.main(), 0)
            self.assertIsNotNone(build._SSL_CONTEXT)

    def test_workflow_passes_the_certificate(self):
        wf = (Path(__file__).resolve().parent.parent / ".github/workflows/update-data.yml").read_text("utf-8")
        self.assertIn("--ca-bundle certs/habous-intermediate.pem", wf)
        self.assertTrue(self.CERT.exists())
