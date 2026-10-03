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
             mock.patch.object(build, "geocode", return_value=(34.0, -6.8)) as geo, \
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
