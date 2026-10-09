import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import fetch_sports
import validate_sports

CONFIG_PATH = Path(__file__).resolve().parents[1] / "sports-config.json"
CONFIG = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
STAMP_A = "2026-10-09T12:00:00+00:00"
STAMP_B = "2026-10-09T12:15:00+00:00"


def raw_payload(url):
    if url.endswith("/scoreboard"):
        racing = "/racing/" in url
        competitors = ([
            {"order": 1, "score": "1", "displayClock": "1:30.000", "athlete": {"shortName": "Driver One", "displayName": "Driver One Full"}},
            {"order": 2, "score": "2", "athlete": {"shortName": "Driver Two"}},
        ] if racing else [
            {"homeAway": "away", "winner": False, "score": "0", "team": {"abbreviation": "AWY", "shortDisplayName": "Away", "displayName": "Away Team", "color": "ignored"}},
            {"homeAway": "home", "winner": True, "score": "7", "team": {"abbreviation": "HME", "shortDisplayName": "Home", "displayName": "Home Team"}},
        ])
        comp = {
            "date": STAMP_A,
            "name": "Competition",
            "shortName": "CMP",
            "status": {"type": {"name": "STATUS_FINAL", "shortDetail": "Final", "ignored": True}, "period": 4, "ignored": True},
            "links": [{"href": "https://www.espn.com/gamecast/1", "text": "Gamecast", "ignored": True}],
            "competitors": competitors,
            "ignored": "large vendor data omitted",
        }
        return {"events": [
            {"date": STAMP_A, "name": "Event One", "shortName": "E1", "status": {"type": {"name": "STATUS_FINAL"}}, "competitions": [comp]},
            {"date": STAMP_A, "name": "Event Two", "competitions": [copy.deepcopy(comp)]},
        ], "ignoredVendorBlob": "omitted"}
    if url.endswith("/rankings"):
        return {"rankings": [{
            "name": "AP Top 25", "shortName": "AP", "type": "poll", "ignored": True,
            "ranks": [{"current": 1, "previous": 0, "recordSummary": "5-0", "team": {
                "location": "Home", "name": "Home Team", "abbreviation": "HME", "nickname": "Home", "ignored": True
            }}],
        }]}
    return {"name": "League", "children": [{
        "name": "Division", "abbreviation": "DIV", "ignored": True,
        "standings": {"entries": [{
            "team": {"abbreviation": "HME", "shortDisplayName": "Home", "displayName": "Home Team", "ignored": True},
            "stats": [{"name": "wins", "abbreviation": "W", "displayValue": "5", "value": 5},
                      {"name": "losses", "displayValue": "0", "value": 0}],
        }]},
        "children": [{"name": "Nested", "standings": {"entries": []}}],
    }]}


class SportsSnapshotTests(unittest.TestCase):
    def test_live_config_derives_fixed_endpoint_allowlist(self):
        urls = validate_sports.expected_urls(CONFIG)
        self.assertEqual(len(urls), 27)
        self.assertEqual(len(set(urls)), 27)
        self.assertTrue(all(url.startswith("https://site.api.espn.com/") for url in urls))

    def test_refresh_projects_all_real_response_shapes_and_validates(self):
        snapshot = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        validate_sports.validate_snapshot(snapshot, CONFIG)
        self.assertEqual(set(snapshot), {"version", "lastAttemptAt", "entries"})
        self.assertEqual(set(snapshot["entries"]), set(validate_sports.expected_urls(CONFIG)))
        scoreboard = next(row["payload"] for url, row in snapshot["entries"].items() if url.endswith("/scoreboard") and "/racing/" not in url)
        self.assertEqual(len(scoreboard["events"]), 2)
        self.assertEqual(scoreboard["events"][0]["competitions"][0]["competitors"][0]["score"], "0")
        self.assertNotIn("ignoredVendorBlob", scoreboard)
        self.assertEqual(scoreboard["events"][0]["competitions"][0]["competitors"][0]["team"], {
            "abbreviation": "AWY", "shortDisplayName": "Away", "displayName": "Away Team"
        })
        race = next(row["payload"] for url, row in snapshot["entries"].items() if "/racing/" in url and url.endswith("/scoreboard"))
        driver = race["events"][0]["competitions"][0]["competitors"][0]
        self.assertEqual(driver["order"], 1)
        self.assertEqual(driver["athlete"]["shortName"], "Driver One")
        rankings = next(row["payload"] for url, row in snapshot["entries"].items() if url.endswith("/rankings"))
        self.assertEqual(rankings["rankings"][0]["ranks"][0]["previous"], 0)
        standings = next(row["payload"] for url, row in snapshot["entries"].items() if url.endswith("/standings"))
        self.assertEqual(standings["children"][0]["children"][0]["name"], "Nested")
        self.assertEqual(standings["children"][0]["standings"]["entries"][0]["stats"][1]["value"], 0)

    def test_failed_endpoint_retains_last_good_payload_and_provenance(self):
        first = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        target = next(url for url in first["entries"] if url.endswith("/scoreboard"))
        old = copy.deepcopy(first["entries"][target])

        def fail_one(url):
            if url == target:
                raise OSError("provider unavailable")
            return raw_payload(url)

        second = fetch_sports.refresh(CONFIG, first, fetch=fail_one, now=STAMP_B)
        row = second["entries"][target]
        self.assertEqual(row["status"], "stale")
        self.assertEqual(row["payload"], old["payload"])
        self.assertEqual(row["generatedAt"], STAMP_A)
        self.assertEqual(row["lastAttemptAt"], STAMP_B)
        validate_sports.validate_snapshot(second, CONFIG)

    def test_config_add_remove_drops_removed_and_marks_new_endpoint_unavailable(self):
        first = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        changed = copy.deepcopy(CONFIG)
        changed["leagues"] = changed["leagues"][1:]
        changed["leagues"].append({
            "name": "New Test League", "enabled": True, "espn_path": "test/new-league",
            "color": "#123456", "standings": False,
        })
        next_snapshot = fetch_sports.refresh(
            changed, first,
            fetch=lambda url: (_ for _ in ()).throw(OSError("new endpoint unavailable")) if "/test/new-league/" in url else raw_payload(url),
            now=STAMP_B,
        )
        expected = validate_sports.expected_urls(changed)
        self.assertEqual(list(next_snapshot["entries"]), expected)
        added = next(url for url in expected if "/test/new-league/" in url)
        removed = validate_sports.expected_urls(CONFIG)[0]
        self.assertNotIn(removed, next_snapshot["entries"])
        self.assertEqual(next_snapshot["entries"][added]["status"], "unavailable")
        self.assertIsNone(next_snapshot["entries"][added]["payload"])
        validate_sports.validate_snapshot(next_snapshot, changed)

    def test_initial_failure_marks_unavailable_and_zero_budget_starts_no_fetch(self):
        calls = []
        result = fetch_sports.refresh(CONFIG, fetch=lambda url: calls.append(url), now=STAMP_A, budget=0)
        self.assertEqual(calls, [])
        self.assertTrue(all(row["status"] == "unavailable" and row["payload"] is None for row in result["entries"].values()))
        validate_sports.validate_snapshot(result, CONFIG)

    def test_schema_rejects_unknown_endpoint_missing_render_fields_and_non_https_port(self):
        snapshot = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        url = next(url for url in snapshot["entries"] if url.endswith("/scoreboard") and "/racing/" not in url)
        bad = copy.deepcopy(snapshot)
        del bad["entries"][url]["payload"]["events"][0]["competitions"][0]["status"]
        with self.assertRaises(ValueError):
            validate_sports.validate_snapshot(bad, CONFIG)
        bad = copy.deepcopy(snapshot)
        bad["entries"]["https://site.api.espn.com:8443/not-allowed"] = bad["entries"].pop(url)
        with self.assertRaises(ValueError):
            validate_sports.validate_snapshot(bad, CONFIG)
        with self.assertRaises(ValueError):
            fetch_sports.fetch_endpoint("https://site.api.espn.com:8443/apis/site/v2/sports/football/nfl/scoreboard")
        redirect = fetch_sports._SameHostRedirect()
        request = Request("https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard")
        with self.assertRaises(HTTPError):
            redirect.redirect_request(request, None, 302, "Found", {}, "https://site.api.espn.com:8443/redirect")

    def test_snapshot_total_size_is_bounded_before_atomic_write(self):
        snapshot = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        with tempfile.TemporaryDirectory() as folder, patch.object(fetch_sports, "MAX_SNAPSHOT_BYTES", 1):
            path = Path(folder) / "sports-snapshot.json"
            with self.assertRaises(ValueError):
                fetch_sports.atomic_write(path, snapshot)
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
