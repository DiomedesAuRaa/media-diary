#!/usr/bin/env python3
"""Refresh a public, allowlisted snapshot of ESPN score and standings JSON."""
import argparse
import json
import os
import queue
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from validate_sports import MAX_SNAPSHOT_BYTES, expected_urls, normalize_previous, validate_json_tree, validate_payload, validate_snapshot

MAX_WORKERS = 4
TOTAL_FETCH_BUDGET = 45
REQUEST_TIMEOUT = 10
MAX_ENTRY_BYTES = 4 * 1024 * 1024
SCORE_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
STANDINGS_BASE = "https://site.api.espn.com/apis/v2/sports/"
RANKINGS_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
F1_STANDINGS_URL = STANDINGS_BASE + "racing/f1/standings"


def _pick(obj, keys):
    if not isinstance(obj, dict):
        return {}
    return {key: obj[key] for key in keys if key in obj}


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
        result["team"] = _pick(team, ("abbreviation", "shortDisplayName", "displayName"))
    if isinstance(athlete, dict):
        result["athlete"] = _pick(athlete, ("shortName", "displayName"))
    return result


def _project_competition(competition, event=None):
    if not isinstance(competition, dict):
        raise ValueError("ESPN event has no competition data")
    result = _pick(competition, ("date", "name", "shortName"))
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
    result["competitors"] = [_project_competitor(competitor) for competitor in competitors if isinstance(competitor, dict)]
    return result


def _project_scoreboard(payload):
    events = payload.get("events")
    if not isinstance(events, list):
        raise ValueError("ESPN scoreboard has no event list")
    projected = []
    for event in events:
        if not isinstance(event, dict) or not isinstance(event.get("competitions"), list) or not event["competitions"]:
            raise ValueError("ESPN scoreboard event has no competition")
        projected.append({
            **_pick(event, ("date", "name", "shortName")),
            "status": _project_status(event.get("status")),
            "competitions": [_project_competition(item, event) for item in event["competitions"]],
        })
    return {"events": projected}


def _project_team(team):
    return _pick(team, ("abbreviation", "shortDisplayName", "displayName"))


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
                item["ranks"].append(row)
        projected.append(item)
    return {"rankings": projected}


def project_payload(url, payload, racing_urls=()):
    validate_json_tree(payload)
    if url.endswith("/scoreboard"):
        projected = _project_scoreboard(payload)
    elif url.endswith("/rankings"):
        projected = _project_rankings(payload)
    elif url.endswith("/standings"):
        projected = _project_standings(payload)
    else:
        raise ValueError("Unknown ESPN endpoint type")
    validate_payload(url, projected, racing_urls)
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
    deadline = time.monotonic() + budget
    work, completed = queue.Queue(), queue.Queue()
    for url in urls:
        work.put(url)

    def worker():
        while time.monotonic() < deadline:
            try:
                url = work.get_nowait()
            except queue.Empty:
                return
            try:
                projected = project_payload(url, fetcher(url), racing_urls)
                completed.put((url, validate_payload(url, projected, racing_urls), None))
            except Exception as exc:
                completed.put((url, None, exc))
            finally:
                work.task_done()

    for _ in range(min(MAX_WORKERS, len(urls))):
        threading.Thread(target=worker, daemon=True).start()

    entries = {}
    received = 0
    while received < len(urls) and time.monotonic() < deadline:
        try:
            url, payload, error = completed.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            break
        received += 1
        if error is None:
            entries[url] = {"payload": payload, "generatedAt": stamp, "lastAttemptAt": stamp, "status": "ok"}
        else:
            old = prior.get(url)
            entries[url] = {
                "payload": old["payload"] if old else None,
                "generatedAt": old["generatedAt"] if old else None,
                "lastAttemptAt": stamp,
                "status": "stale" if old and old["payload"] is not None else "unavailable",
            }
    for url in urls:
        if url not in entries:
            old = prior.get(url)
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
