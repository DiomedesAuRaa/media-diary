import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit
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
    path = urlsplit(url).path
    if path.endswith("/scoreboard"):
        racing = "/racing/" in path
        if racing:
            sessions = []
            for index, abbreviation in enumerate(("FP1", "FP2", "FP3", "QUAL", "RACE")):
                session_date = datetime.fromisoformat(STAMP_A.replace("Z", "+00:00")) + timedelta(days=index)
                sessions.append({
                    "id": str(900 + index), "date": session_date.isoformat(), "name": abbreviation,
                    "type": {"abbreviation": abbreviation},
                    "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre"}},
                    "competitors": [],
                })
            return {"events": [{
                "id": "f1-weekend", "name": "Grand Prix", "status": {"type": {"name": "STATUS_SCHEDULED", "state": "pre"}},
                "competitions": sessions,
            }]}
        competitors = ([
            {"order": 1, "score": "1", "displayClock": "1:30.000", "athlete": {"shortName": "Driver One", "displayName": "Driver One Full"}},
            {"order": 2, "score": "2", "athlete": {"shortName": "Driver Two"}},
        ] if racing else [
            {"homeAway": "away", "winner": False, "score": "0", "team": {"id": "8", "abbreviation": "AWY", "shortDisplayName": "Away", "displayName": "Away Team", "color": "ignored"}},
            {"homeAway": "home", "winner": True, "score": "7", "team": {"id": "6", "abbreviation": "HME", "shortDisplayName": "Home", "displayName": "Home Team"}},
        ])
        comp = {
            "id": "comp-1",
            "type": {"abbreviation": "REG", "ignored": True},
            "date": STAMP_A,
            "name": "Competition",
            "shortName": "CMP",
            "status": {"type": {"name": "STATUS_FINAL", "shortDetail": "Final", "ignored": True}, "period": 4, "ignored": True},
            "links": [{"href": "https://www.espn.com/gamecast/1", "text": "Gamecast", "ignored": True}],
            "broadcasts": [{"market": "national", "names": ["Prime Video"], "ignored": True}],
            "geoBroadcasts": [{"media": {"shortName": "ignored"}}],
            "competitors": competitors,
            "ignored": "large vendor data omitted",
        }
        return {"events": [
            {"id": "event-1", "date": STAMP_A, "name": "Event One", "shortName": "E1", "status": {"type": {"name": "STATUS_FINAL"}}, "competitions": [comp]},
            {"id": "event-2", "date": STAMP_A, "name": "Event Two", "competitions": [{**copy.deepcopy(comp), "id": "comp-2"}]},
        ], "ignoredVendorBlob": "omitted"}
    if path.endswith("/rankings"):
        return {"rankings": [{
            "name": "AP Top 25", "shortName": "AP", "type": "poll", "ignored": True,
            "ranks": [{"current": 1, "previous": 0, "recordSummary": "5-0", "team": {
                "id": "130", "location": "Home", "name": "Home Team", "abbreviation": "HME", "nickname": "Home", "ignored": True
            }}],
        }]}
    return {"name": "League", "children": [{
        "name": "Division", "abbreviation": "DIV", "ignored": True,
        "standings": {"entries": [{
            "team": {"id": "8", "abbreviation": "HME", "shortDisplayName": "Home", "displayName": "Home Team", "ignored": True},
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
        self.assertEqual(CONFIG["favorite_team_ids"], {
            "NFL": ["8"], "NBA": ["8"], "MLB": ["6"], "NHL": ["5"], "NCAAFB": ["130"], "NCAAB": ["130"]
        })

    def test_refresh_projects_all_real_response_shapes_and_validates(self):
        snapshot = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        validate_sports.validate_snapshot(snapshot, CONFIG)
        self.assertEqual(set(snapshot), {"version", "lastAttemptAt", "entries"})
        self.assertEqual(set(snapshot["entries"]), set(validate_sports.expected_urls(CONFIG)))
        scoreboard = next(row["payload"] for url, row in snapshot["entries"].items() if url.endswith("/scoreboard") and "/racing/" not in url)
        self.assertEqual(len(scoreboard["events"]), 2)
        self.assertEqual([event["id"] for event in scoreboard["events"]], ["event-1", "event-2"])
        self.assertEqual(scoreboard["events"][0]["competitions"][0]["id"], "comp-1")
        self.assertEqual(scoreboard["events"][0]["competitions"][0]["type"]["abbreviation"], "REG")
        self.assertEqual(scoreboard["events"][0]["competitions"][0]["competitors"][0]["score"], "0")
        self.assertNotIn("ignoredVendorBlob", scoreboard)
        self.assertEqual(scoreboard["events"][0]["competitions"][0]["broadcasts"], [{"market": "national", "names": ["Prime Video"]}])
        self.assertNotIn("geoBroadcasts", scoreboard["events"][0]["competitions"][0])
        self.assertEqual(scoreboard["events"][0]["competitions"][0]["competitors"][0]["team"], {
            "abbreviation": "AWY", "shortDisplayName": "Away", "displayName": "Away Team", "id": "8"
        })
        race = next(row["payload"] for url, row in snapshot["entries"].items() if "/racing/" in url and url.endswith("/scoreboard"))
        self.assertEqual(race["events"][0]["id"], "f1-weekend")
        self.assertEqual(len(race["events"][0]["competitions"]), 5)
        self.assertEqual(race["events"][0]["competitions"][0]["competitors"], [])
        self.assertEqual(race["events"][0]["competitions"][0]["type"]["abbreviation"], "FP1")
        rankings = next(row["payload"] for url, row in snapshot["entries"].items() if url.endswith("/rankings"))
        self.assertEqual(rankings["rankings"][0]["ranks"][0]["previous"], 0)
        self.assertEqual(rankings["rankings"][0]["ranks"][0]["team"]["id"], "130")
        standings = next(row["payload"] for url, row in snapshot["entries"].items() if url.endswith("/standings"))
        self.assertEqual(standings["children"][0]["children"][0]["name"], "Nested")
        self.assertEqual(standings["children"][0]["standings"]["entries"][0]["stats"][1]["value"], 0)
        self.assertEqual(standings["children"][0]["standings"]["entries"][0]["team"]["id"], "8")

    def test_scoreboards_request_nine_dates_with_league_specific_groups_and_merge_overlaps(self):
        calls = []
        snapshot = fetch_sports.refresh(CONFIG, fetch=lambda url: (calls.append(url), raw_payload(url))[1], now=STAMP_A)
        score_calls = [url for url in calls if urlsplit(url).path.endswith("/scoreboard")]
        self.assertEqual(len(score_calls), 14 * 9)
        for path in ("football/nfl", "basketball/nba", "baseball/mlb", "hockey/nhl", "racing/f1", "soccer/eng.1"):
            rows = [url for url in score_calls if f"/sports/{path}/scoreboard" in url]
            self.assertEqual(len(rows), 9)
            self.assertTrue(all(parse_qs(urlsplit(row).query).get("limit") == ["100"] for row in rows))
        cfb = [url for url in score_calls if "/football/college-football/scoreboard" in url]
        self.assertEqual(parse_qs(urlsplit(cfb[0]).query).get("groups"), ["80"])
        self.assertEqual(parse_qs(urlsplit(cfb[0]).query).get("limit"), ["100"])
        cbb = [url for url in score_calls if "/mens-college-basketball/scoreboard" in url]
        self.assertEqual(parse_qs(urlsplit(cbb[0]).query).get("groups"), ["50"])
        self.assertEqual(parse_qs(urlsplit(cbb[0]).query).get("limit"), ["365"])
        requested_dates = sorted({parse_qs(urlsplit(row).query)["dates"][0] for row in score_calls})
        self.assertEqual(requested_dates, [f"202610{day:02d}" for day in range(8, 17)])
        row = snapshot["entries"][next(url for url in snapshot["entries"] if url.endswith("/football/nfl/scoreboard"))]
        coverage_dates = [f"2026-10-{day:02d}" for day in range(8, 17)]
        self.assertEqual(row["coverage"], {"start": "2026-10-08", "end": "2026-10-16", "dates": coverage_dates, "complete": True})
        self.assertEqual(len(row["payload"]["events"]), 2)
        validate_sports.validate_snapshot(snapshot, CONFIG)

    def test_failed_endpoint_retains_last_good_payload_and_provenance(self):
        first = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        target = next(url for url in first["entries"] if url.endswith("/scoreboard"))
        old = copy.deepcopy(first["entries"][target])

        def fail_one(url):
            if urlsplit(url)._replace(query="").geturl() == target:
                raise OSError("provider unavailable")
            return raw_payload(url)

        second = fetch_sports.refresh(CONFIG, first, fetch=fail_one, now=STAMP_B)
        row = second["entries"][target]
        self.assertEqual(row["status"], "stale")
        self.assertEqual(row["payload"], old["payload"])
        self.assertEqual(row["generatedAt"], STAMP_A)
        self.assertEqual(row["lastAttemptAt"], STAMP_B)
        self.assertEqual(row["coverage"], old["coverage"])
        validate_sports.validate_snapshot(second, CONFIG)

    def test_partial_day_window_retains_last_good_payload_and_coverage(self):
        first = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        target = next(url for url in first["entries"] if url.endswith("/scoreboard"))
        original = first["entries"][target]
        failed_date = "20261010"
        def partial(url):
            if urlsplit(url)._replace(query="").geturl() == target and parse_qs(urlsplit(url).query).get("dates") == [failed_date]:
                raise OSError("one date unavailable")
            return raw_payload(url)
        result = fetch_sports.refresh(CONFIG, first, fetch=partial, now=STAMP_B)
        row = result["entries"][target]
        self.assertEqual(row["status"], "stale")
        self.assertEqual(row["payload"], original["payload"])
        self.assertEqual(row["generatedAt"], original["generatedAt"])
        self.assertEqual(row["coverage"], original["coverage"])
        validate_sports.validate_snapshot(result, CONFIG)

    def test_window_filter_uses_instants_across_offsets_and_deduplicates_provider_ids(self):
        target = next(url for url in validate_sports.expected_urls(CONFIG) if url.endswith("/football/nfl/scoreboard"))
        events = []
        for event_id, comp_id, date in (
            ("before", "c-before", "2026-10-09T07:59:59-04:00"),
            ("start", "c-start", "2026-10-09T08:00:00-04:00"),
            ("end", "c-end", "2026-10-16T08:00:00-04:00"),
            ("after", "c-after", "2026-10-16T08:00:01-04:00"),
        ):
            payload = raw_payload(target)["events"][0]
            payload["id"] = event_id
            payload["competitions"][0]["id"] = comp_id
            payload["competitions"][0]["date"] = date
            events.append(payload)
        calls = set()
        def fetch(url):
            canonical = urlsplit(url)._replace(query="").geturl()
            if canonical == target:
                calls.add(parse_qs(urlsplit(url).query)["dates"][0])
                return {"events": copy.deepcopy(events)}
            return raw_payload(url)
        snapshot = fetch_sports.refresh(CONFIG, fetch=fetch, now=STAMP_A)
        row = snapshot["entries"][target]
        self.assertEqual(len(calls), 9)
        self.assertEqual([event["id"] for event in row["payload"]["events"]], ["start", "end"])
        validate_sports.validate_snapshot(snapshot, CONFIG)

    def test_legacy_snapshot_without_coverage_and_valid_events_with_bad_rows(self):
        snapshot = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        for url, row in snapshot["entries"].items():
            row.pop("coverage", None)
        validate_sports.validate_snapshot(snapshot, CONFIG)
        url = next(url for url in snapshot["entries"] if url.endswith("/football/nfl/scoreboard"))
        valid = snapshot["entries"][url]["payload"]["events"][0]
        with self.assertRaises(ValueError):
            fetch_sports.project_payload(url, {"events": [copy.deepcopy(valid), None]})
        with self.assertRaises(ValueError):
            fetch_sports.project_payload(url, {"events": [copy.deepcopy(valid), {"competitions": [None]}]})
        with self.assertRaises(ValueError):
            fetch_sports.project_payload(url, {"events": {"unexpected": "shape"}})

    def test_mixed_valid_and_malformed_day_never_claims_fresh_complete_coverage(self):
        first = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        target = next(url for url in first["entries"] if url.endswith("/football/nfl/scoreboard"))
        original = copy.deepcopy(first["entries"][target])
        failed_date = "20261010"

        def mixed_day(url):
            if (urlsplit(url)._replace(query="").geturl() == target
                    and parse_qs(urlsplit(url).query).get("dates") == [failed_date]):
                return {"events": [*raw_payload(url)["events"], {"id": "broken", "competitions": [None]}]}
            return raw_payload(url)

        result = fetch_sports.refresh(CONFIG, first, fetch=mixed_day, now=STAMP_B)
        row = result["entries"][target]
        self.assertEqual(row["status"], "stale")
        self.assertEqual(row["payload"], original["payload"])
        self.assertEqual(row["generatedAt"], original["generatedAt"])
        self.assertEqual(row["coverage"], original["coverage"])
        validate_sports.validate_snapshot(result, CONFIG)

        initial = fetch_sports.refresh(CONFIG, fetch=lambda url: mixed_day(url), now=STAMP_B)
        fresh_row = initial["entries"][target]
        self.assertEqual(fresh_row["status"], "unavailable")
        self.assertIsNone(fresh_row["payload"])
        self.assertFalse(fresh_row["coverage"]["complete"])
        self.assertEqual(len(fresh_row["coverage"]["dates"]), 8)
        self.assertNotIn("2026-10-10", fresh_row["coverage"]["dates"])
        validate_sports.validate_snapshot(initial, CONFIG)

    def test_config_add_remove_drops_removed_and_marks_new_endpoint_unavailable(self):
        first = fetch_sports.refresh(CONFIG, fetch=raw_payload, now=STAMP_A)
        changed = copy.deepcopy(CONFIG)
        changed["leagues"] = changed["leagues"][1:]
        changed["favorite_team_ids"].pop("NFL")
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
        bad["entries"][url]["payload"]["events"][0]["competitions"][0]["broadcasts"] = [{"market": "national", "names": [42]}]
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
