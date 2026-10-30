#!/usr/bin/env python3
"""Refresh a public, allowlisted snapshot of ESPN score and standings JSON."""
import argparse
import json
import os
import queue
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlparse, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from validate_sports import MAX_SNAPSHOT_BYTES, _validate_scoreboard, expected_urls, normalize_previous, validate_json_tree, validate_payload, validate_snapshot

MAX_WORKERS = 6
TOTAL_FETCH_BUDGET = 240
REQUEST_TIMEOUT = 12
MAX_ENTRY_BYTES = 4 * 1024 * 1024
SCORE_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
STANDINGS_BASE = "https://site.api.espn.com/apis/v2/sports/"
RANKINGS_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
F1_STANDINGS_URL = STANDINGS_BASE + "racing/f1/standings"


def _pick(obj, keys):
    if not isinstance(obj, dict):
        return {}
    return {key: obj[key] for key in keys if key in obj}


def _provider_id(obj):
    value = obj.get("id") if isinstance(obj, dict) else None
    return str(value) if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value) else None


def _project_status(status):
    if not isinstance(status, dict):
        return None
    result = _pick(status, ("period", "displayClock", "displayPeriod", "periodPrefix"))
    kind = status.get("type")
    result["type"] = _pick(kind, ("name", "shortDetail", "detail", "description", "state", "completed")) if isinstance(kind, dict) else None
    return result


def _project_competitor(competitor):
    result = _pick(competitor, ("homeAway", "winner", "score", "order", "displayClock"))
    team = competitor.get("team") if isinstance(competitor, dict) else None
    athlete = competitor.get("athlete") if isinstance(competitor, dict) else None
    if isinstance(team, dict):
        result["team"] = {**_pick(team, ("abbreviation", "shortDisplayName", "displayName"))}
        team_id = _provider_id(team)
        if team_id:
            result["team"]["id"] = team_id
    if isinstance(athlete, dict):
        result["athlete"] = _pick(athlete, ("shortName", "displayName"))
    return result


def _project_competition(competition, event=None):
    if not isinstance(competition, dict):
        raise ValueError("ESPN event has no competition data")
    result = _pick(competition, ("date", "name", "shortName"))
    competition_id = _provider_id(competition)
    if competition_id:
        result["id"] = competition_id
    kind = competition.get("type")
    if isinstance(kind, dict):
        result["type"] = _pick(kind, ("abbreviation",))
    if not result.get("name") and isinstance(event, dict) and event.get("name"):
        result["name"] = event["name"]
    if not result.get("shortName") and isinstance(event, dict) and event.get("shortName"):
        result["shortName"] = event["shortName"]
    if "date" not in result and isinstance(event, dict) and event.get("date"):
        result["date"] = event["date"]
    result["status"] = _project_status(competition.get("status"))
    result["links"] = [
        _pick(link, ("href", "text")) for link in competition.get("links", []) if isinstance(link, dict)
    ]
    # ESPN exposes broadcast names separately from its larger geoBroadcasts object.
    # Keep only public market labels and names for the schedule tool.
    broadcasts = competition.get("broadcasts", [])
    if isinstance(broadcasts, list):
        result["broadcasts"] = [
            {"market": row["market"], "names": row["names"]}
            for row in broadcasts
            if isinstance(row, dict) and isinstance(row.get("market"), str)
            and isinstance(row.get("names"), list)
            and all(isinstance(name, str) for name in row["names"])
        ]
    competitors = competition.get("competitors", [])
    if not isinstance(competitors, list):
        raise ValueError("ESPN event has invalid competitor data")
    if any(not isinstance(competitor, dict) for competitor in competitors):
        raise ValueError("ESPN event has unsupported competitor data")
    result["competitors"] = [_project_competitor(competitor) for competitor in competitors]
    return result


def _project_scoreboard(payload, racing=False):
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("ESPN scoreboard has no event list")
    projected = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("competitions"), list) or not event["competitions"]:
            raise ValueError("ESPN scoreboard contains an unsupported event")
        competitions = []
        for item in event["competitions"]:
            if not isinstance(item, dict):
                raise ValueError("ESPN scoreboard contains an unsupported competition")
            competition = _project_competition(item, event)
            candidate = {"competitions": [competition], "status": _project_status(event.get("status"))}
            _validate_scoreboard({"events": [candidate]}, racing=racing)
            competitions.append(competition)
        row = {
            **_pick(event, ("date", "name", "shortName")),
            "status": _project_status(event.get("status")),
            "competitions": competitions,
        }
        event_id = _provider_id(event)
        if event_id:
            row["id"] = event_id
        projected.append(row)
    return {"events": projected}


def _endpoint_path(url):
    return urlsplit(url).path


def _canonical_url(url):
    parsed = urlsplit(url)
    return parsed._replace(query="", fragment="").geturl()


def _project_team(team):
    result = _pick(team, ("abbreviation", "shortDisplayName", "displayName"))
    team_id = _provider_id(team)
    if team_id:
        result["id"] = team_id
    return result


def _project_stat(stat):
    return _pick(stat, ("name", "abbreviation", "displayValue", "value"))


def _project_standings_group(group):
    if not isinstance(group, dict):
        raise ValueError("Invalid ESPN standings group")
    result = _pick(group, ("name", "abbreviation"))
    if isinstance(group.get("children"), list):
        result["children"] = [_project_standings_group(child) for child in group["children"] if isinstance(child, dict)]
    standings = group.get("standings")
    if isinstance(standings, dict):
        entries = standings.get("entries", [])
        if not isinstance(entries, list):
            raise ValueError("Invalid ESPN standings entries")
        result["standings"] = {"entries": [
            {"team": _project_team(entry.get("team")), "stats": [_project_stat(item) for item in entry.get("stats", []) if isinstance(item, dict)]}
            for entry in entries if isinstance(entry, dict)
        ]}
    return result


def _project_standings(payload):
    result = _pick(payload, ("name", "abbreviation"))
    if isinstance(payload.get("children"), list):
        result["children"] = [_project_standings_group(group) for group in payload["children"] if isinstance(group, dict)]
    standings = payload.get("standings")
    if isinstance(standings, dict):
        result["standings"] = _project_standings_group({"standings": standings})["standings"]
    if not ("children" in result or "standings" in result):
        raise ValueError("ESPN standings response has no groups or entries")
    return result


def _project_rankings(payload):
    rankings = payload.get("rankings")
    if not isinstance(rankings, list):
        raise ValueError("ESPN rankings response has no ranking list")
    projected = []
    for ranking in rankings:
        if not isinstance(ranking, dict):
            continue
        item = _pick(ranking, ("name", "shortName", "type"))
        if isinstance(ranking.get("ranks"), list):
            item["ranks"] = []
            for rank in ranking["ranks"]:
                if not isinstance(rank, dict):
                    continue
                row = _pick(rank, ("current", "previous", "recordSummary"))
                team = rank.get("team")
                row["team"] = _pick(team, ("location", "name", "abbreviation", "nickname")) if isinstance(team, dict) else {}
                team_id = _provider_id(team)
                if team_id:
                    row["team"]["id"] = team_id
                item["ranks"].append(row)
        projected.append(item)
    return {"rankings": projected}


def project_payload(url, payload, racing_urls=()):
    validate_json_tree(payload)
    canonical = _canonical_url(url)
    if _endpoint_path(url).endswith("/scoreboard"):
        projected = _project_scoreboard(payload, racing=canonical in racing_urls)
    elif _endpoint_path(url).endswith("/rankings"):
        projected = _project_rankings(payload)
    elif _endpoint_path(url).endswith("/standings"):
        projected = _project_standings(payload)
    else:
        raise ValueError("Unknown ESPN endpoint type")
    validate_payload(canonical, projected, racing_urls)
    return projected


class _SameHostRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old = urlparse(req.full_url)
        new = urlparse(urljoin(req.full_url, newurl))
        try:
            old_port, new_port = old.port, new.port
        except ValueError as exc:
            raise HTTPError(req.full_url, code, "Invalid ESPN redirect port", headers, fp) from exc
        if (old.scheme != "https" or new.scheme != "https" or old.hostname != new.hostname
                or old.username or old.password or new.username or new.password
                or old_port not in (None, 443) or new_port not in (None, 443)):
            raise HTTPError(req.full_url, code, "Cross-host or insecure ESPN redirect rejected", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_endpoint(url):
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid ESPN endpoint port") from exc
    if parsed.scheme != "https" or parsed.hostname != "site.api.espn.com" or parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("Endpoint is outside the ESPN allowlist")
    opener = build_opener(ProxyHandler({}), _SameHostRedirect())
    request = Request(url, headers={
        "User-Agent": "Media-Diary-sports-snapshot/1.0",
        "Accept": "application/json",
    })
    deadline = time.monotonic() + REQUEST_TIMEOUT
    with opener.open(request, timeout=REQUEST_TIMEOUT) as response:
        if response.status != 200:
            raise ValueError("ESPN returned HTTP %d" % response.status)
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_ENTRY_BYTES:
            raise ValueError("ESPN response exceeds 4 MiB")
        body = bytearray()
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("ESPN response deadline exceeded")
            chunk = response.read(65536)
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > MAX_ENTRY_BYTES:
                raise ValueError("ESPN response exceeds 4 MiB")
    try:
        payload = json.loads(body.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON constant: " + value)))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("ESPN response is not valid UTF-8 JSON") from exc
    validate_json_tree(payload)
    return payload


def stamp_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _scoreboard_request_url(url, requested_date):
    path = _endpoint_path(url)
    limit = 100
    query = {"dates": requested_date.replace("-", "")}
    if path.endswith("/football/college-football/scoreboard"):
        query["groups"] = "80"  # ESPN's FBS group; the configured NCAAFB poll is FBS-only.
    elif path.endswith("/basketball/mens-college-basketball/scoreboard"):
        query["groups"] = "50"  # ESPN's Division I men's basketball group.
        limit = 365  # One day can exceed a normal league scoreboard's event count.
    query["limit"] = limit
    return url + "?" + urlencode(query)


def _parse_provider_datetime(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.utcoffset() is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _merge_scoreboards(day_payloads, window_start, window_end):
    """Merge overlapping day responses by ESPN IDs, then keep the requested time window."""
    events, event_order = {}, []
    for requested_date in sorted(day_payloads):
        for event in day_payloads[requested_date]["events"]:
            competitions = []
            for competition in event["competitions"]:
                start = _parse_provider_datetime(competition.get("date"))
                if start is not None and window_start <= start <= window_end:
                    competitions.append(competition)
            if not competitions:
                continue
            event_id = event.get("id")
            if event_id:
                event_key = ("id", event_id)
            else:
                event_key = ("fallback", event.get("date"), event.get("name"), event.get("shortName"))
            if event_key not in events:
                events[event_key] = {key: value for key, value in event.items() if key != "competitions"}
                events[event_key]["competitions"] = []
                events[event_key]["_competition_keys"] = set()
                event_order.append(event_key)
            merged = events[event_key]
            # Use the latest provider representation of event-level status/labels.
            merged.update({key: value for key, value in event.items() if key != "competitions"})
            for competition in competitions:
                competition_id = competition.get("id")
                competition_key = ("id", competition_id) if competition_id else (
                    "fallback", competition.get("date"), competition.get("name"), competition.get("shortName"),
                    (competition.get("type") or {}).get("abbreviation"),
                )
                if competition_key in merged["_competition_keys"]:
                    index = next(i for i, item in enumerate(merged["competitions"]) if _competition_key(item) == competition_key)
                    merged["competitions"][index] = competition
                else:
                    merged["_competition_keys"].add(competition_key)
                    merged["competitions"].append(competition)
    result = []
    for event_key in event_order:
        event = events[event_key]
        event.pop("_competition_keys", None)
        if event["competitions"]:
            result.append(event)
    return {"events": result}


def _competition_key(competition):
    competition_id = competition.get("id")
    if competition_id:
        return ("id", competition_id)
    return (
        "fallback", competition.get("date"), competition.get("name"), competition.get("shortName"),
        (competition.get("type") or {}).get("abbreviation"),
    )


def refresh(config, previous=None, fetch=None, now=None, budget=TOTAL_FETCH_BUDGET):
    urls = expected_urls(config)
    prior = normalize_previous(previous, config)
    if budget < 0:
        raise ValueError("Refresh budget must not be negative")
    stamp = now or stamp_now()
    fetcher = fetch or fetch_endpoint
    racing_urls = {
        SCORE_BASE + league["espn_path"] + "/scoreboard"
        for league in config["leagues"] if league["enabled"] and league.get("scores_type") == "racing"
    }
    current_time = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(timezone.utc)
    query_start = current_time.date() - timedelta(days=1)
    query_end = current_time.date() + timedelta(days=7)
    query_dates = [(query_start + timedelta(days=index)).isoformat() for index in range((query_end - query_start).days + 1)]
    window_start = current_time
    window_end = current_time + timedelta(days=7)
    scoreboard_urls = {url for url in urls if _endpoint_path(url).endswith("/scoreboard")}
    deadline = time.monotonic() + budget
    work, completed = queue.Queue(), queue.Queue()
    for url in urls:
        if url in scoreboard_urls:
            for requested_date in query_dates:
                work.put((url, requested_date))
        else:
            work.put((url, None))
    task_count = work.qsize()

    def worker():
        while time.monotonic() < deadline:
            try:
                url, requested_date = work.get_nowait()
            except queue.Empty:
                return
            try:
                request_url = _scoreboard_request_url(url, requested_date) if requested_date else url
                projected = project_payload(request_url, fetcher(request_url), racing_urls)
                completed.put((url, requested_date, validate_payload(url, projected, racing_urls), None))
            except Exception as exc:
                completed.put((url, requested_date, None, exc))
            finally:
                work.task_done()

    for _ in range(min(MAX_WORKERS, len(urls))):
        threading.Thread(target=worker, daemon=True).start()

    scoreboard_results = {url: {} for url in scoreboard_urls}
    scoreboard_errors = {url: set() for url in scoreboard_urls}
    single_results = {}
    received = 0
    while received < task_count and time.monotonic() < deadline:
        try:
            url, requested_date, payload, error = completed.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            break
        received += 1
        if url in scoreboard_urls:
            if error is None:
                scoreboard_results[url][requested_date] = payload
            else:
                scoreboard_errors[url].add(requested_date)
        elif error is None:
            single_results[url] = payload

    entries = {}
    # ESPN has no trustworthy total-page count here; complete means every
    # requested calendar-day query succeeded, not that the provider guarantees
    # its returned event list is exhaustive.
    coverage = {"start": query_start.isoformat(), "end": query_end.isoformat(), "dates": query_dates, "complete": True}
    for url in urls:
        old = prior.get(url)
        if url in scoreboard_urls:
            successful_dates = sorted(scoreboard_results[url])
            complete = successful_dates == query_dates and not scoreboard_errors[url]
            if complete:
                payload = _merge_scoreboards(scoreboard_results[url], window_start, window_end)
                entries[url] = {"payload": validate_payload(url, payload, racing_urls), "generatedAt": stamp, "lastAttemptAt": stamp, "status": "ok", "coverage": coverage}
            else:
                entry = {
                    "payload": old["payload"] if old else None,
                    "generatedAt": old["generatedAt"] if old else None,
                    "lastAttemptAt": stamp,
                    "status": "stale" if old and old["payload"] is not None else "unavailable",
                }
                if old and old["payload"] is not None:
                    if old.get("coverage") is not None:
                        entry["coverage"] = old["coverage"]
                else:
                    entry["coverage"] = {"start": query_start.isoformat(), "end": query_end.isoformat(), "dates": successful_dates, "complete": False}
                entries[url] = entry
        elif url in single_results:
            entries[url] = {"payload": single_results[url], "generatedAt": stamp, "lastAttemptAt": stamp, "status": "ok"}
        else:
            entries[url] = {
                "payload": old["payload"] if old else None,
                "generatedAt": old["generatedAt"] if old else None,
                "lastAttemptAt": stamp,
                "status": "stale" if old and old["payload"] is not None else "unavailable",
            }
    entries = {url: entries[url] for url in urls}
    return {"version": 1, "lastAttemptAt": stamp, "entries": entries}


def atomic_write(path, snapshot):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    encoded = (json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Sports snapshot exceeds 4 MiB")
    temp.write_bytes(encoded)
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--budget", type=int, default=TOTAL_FETCH_BUDGET, choices=range(1, TOTAL_FETCH_BUDGET + 1))
    args = parser.parse_args()
    config = json.loads((args.root / "sports-config.json").read_text(encoding="utf-8"))
    path = args.root / "sports-snapshot.json"
    if path.exists() and path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("Previous sports snapshot exceeds 4 MiB")
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    snapshot = refresh(config, previous, budget=args.budget)
    validate_snapshot(snapshot, config)
    atomic_write(path, snapshot)
    counts = {status: sum(row["status"] == status for row in snapshot["entries"].values()) for status in ("ok", "stale", "unavailable")}
    print("Sports refresh: " + ", ".join("%s=%d" % pair for pair in counts.items()))


if __name__ == "__main__":
    main()
