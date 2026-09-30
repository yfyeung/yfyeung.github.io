"""Offline tests for the Scholar parser and its cached snapshot behavior."""

from datetime import datetime
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/update_scholar.py"
SPEC = importlib.util.spec_from_file_location("update_scholar", MODULE_PATH)
scholar = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = scholar
SPEC.loader.exec_module(scholar)


def profile_html(total="1,234", since="987"):
    # Synthetic fixtures model Scholar's public table; these are not live counts.
    return f"""<!doctype html><html><body>
      <table><tr><td>Unrelated table</td><td>99999</td></tr></table>
      <table id="gsc_rsb_st">
        <thead><tr><th></th><th>All</th><th>Since 2021</th></tr></thead>
        <tbody>
          <tr><td class="gsc_rsb_sc1"><a>Citations</a></td>
              <td class="gsc_rsb_std">{total}</td><td class="gsc_rsb_std">{since}</td></tr>
          <tr><td class="gsc_rsb_sc1">h-index</td>
              <td class="gsc_rsb_std">18</td><td class="gsc_rsb_std">17</td></tr>
          <tr><td class="gsc_rsb_sc1">i10-index</td>
              <td class="gsc_rsb_std">25</td><td class="gsc_rsb_std">24</td></tr>
        </tbody>
      </table>
    </body></html>"""


class ParseTotalTests(unittest.TestCase):
    def test_reads_all_citations_not_since_or_other_metrics(self):
        self.assertEqual(scholar.parse_total_citations(profile_html()), 1234)

    def test_accepts_zero_plain_and_comma_grouped_integers(self):
        for text, expected in (("0", 0), ("42", 42), ("12345", 12345), ("1,234,567", 1234567)):
            with self.subTest(text=text):
                self.assertEqual(scholar.parse_total_citations(profile_html(text)), expected)

    def test_allows_markup_and_surrounding_whitespace(self):
        html = profile_html("&nbsp;<span>1,234</span>\n")
        html = html.replace("<a>Citations</a>", "<a>\n Citations&nbsp;</a>")
        html = html.replace('class="gsc_rsb_std"', 'class="extra gsc_rsb_std"')
        self.assertEqual(scholar.parse_total_citations(html), 1234)

    def test_rejects_invalid_totals(self):
        for value in ("", "-1", "+1", "1.5", "1 234", "1,23", "01", "1k", "NaN", "١٢٣"):
            with self.subTest(value=value):
                with self.assertRaises(scholar.ScholarUpdateError):
                    scholar.parse_total_citations(profile_html(value))

    def test_rejects_missing_or_incomplete_table(self):
        html = profile_html()
        variants = {
            "no statistics table": html.replace('id="gsc_rsb_st"', 'id="something_else"'),
            "no table ending": html.rsplit("</table>", 1)[0],
            "missing numeric cell": html.replace('<td class="gsc_rsb_std">987</td>', ""),
            "missing cell ending": html.replace("1,234</td>", "1,234"),
            "missing row ending": html.replace("987</td></tr>", "987</td>"),
            "missing citations row": html.replace("Citations", "Views"),
            "wrong numeric class": html.replace('class="gsc_rsb_std"', 'class="other"'),
            "wrong first column": html.replace("<th>All</th>", "<th>Since 2021</th>"),
            "missing headings": html.replace("<thead><tr><th></th><th>All</th><th>Since 2021</th></tr></thead>", ""),
        }
        for description, malformed in variants.items():
            with self.subTest(description=description):
                with self.assertRaises(scholar.ScholarUpdateError):
                    scholar.parse_total_citations(malformed)

    def test_rejects_ambiguous_rows_and_tables(self):
        html = profile_html()
        for malformed in (html + html, html.replace("h-index", "Citations")):
            with self.assertRaises(scholar.ScholarUpdateError):
                scholar.parse_total_citations(malformed)

    def test_rejects_traffic_challenges_even_if_a_table_is_present(self):
        challenges = (
            "Our systems have detected unusual traffic from your computer network.",
            '<form id="captcha-form"></form>',
            '<div class="g-recaptcha"></div>',
            '<form action="/sorry/index"></form>',
        )
        for challenge in challenges:
            with self.subTest(challenge=challenge):
                with self.assertRaises(scholar.ScholarUpdateError):
                    scholar.parse_total_citations(challenge + profile_html())


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / "scholar.json"
        self.previous = b'{"total_citations": 321, "updated_at": "2026-01-01T00:00:00Z"}\n'
        self.output.write_bytes(self.previous)

    def test_success_writes_total_source_and_utc_timestamp(self):
        snapshot = scholar.update_snapshot(self.output, fetcher=lambda: profile_html("0"))
        self.assertEqual(json.loads(self.output.read_text()), snapshot)
        self.assertEqual(snapshot["total_citations"], 0)
        self.assertEqual(snapshot["profile_url"], scholar.PROFILE_URL)
        self.assertTrue(snapshot["updated_at"].endswith("Z"))
        timestamp = datetime.fromisoformat(snapshot["updated_at"].replace("Z", "+00:00"))
        self.assertEqual(timestamp.utcoffset().total_seconds(), 0)

    def test_parse_failure_preserves_previous_snapshot_byte_for_byte(self):
        with self.assertRaises(scholar.ScholarUpdateError):
            scholar.update_snapshot(self.output, fetcher=lambda: "<html>temporarily unavailable</html>")
        self.assertEqual(self.output.read_bytes(), self.previous)

    def test_fetch_failure_preserves_previous_snapshot_byte_for_byte(self):
        def failed_fetch():
            raise URLError("connection timed out")

        with self.assertRaises(URLError):
            scholar.update_snapshot(self.output, fetcher=failed_fetch)
        self.assertEqual(self.output.read_bytes(), self.previous)

    def test_failed_first_fetch_does_not_create_an_invented_snapshot(self):
        output = Path(self.directory.name) / "new-directory/scholar.json"
        with self.assertRaises(scholar.ScholarUpdateError):
            scholar.update_snapshot(output, fetcher=lambda: "<html>no Scholar data</html>")
        self.assertFalse(output.exists())

    def test_atomic_replace_failure_keeps_previous_file_and_removes_temporary_file(self):
        with patch.object(scholar.os, "replace", side_effect=OSError("simulated write failure")):
            with self.assertRaises(OSError):
                scholar.update_snapshot(self.output, fetcher=lambda: profile_html())
        self.assertEqual(self.output.read_bytes(), self.previous)
        self.assertEqual(list(Path(self.directory.name).iterdir()), [self.output])


if __name__ == "__main__":
    unittest.main()
