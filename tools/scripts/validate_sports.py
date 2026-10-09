#!/usr/bin/env python3
"""Strict validation for the bounded ESPN data used by the public tools."""
import argparse
import json
import math
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

MAX_ENTRY_BYTES = 4 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 4 * 1024 * 1024
MAX_JSON_DEPTH = 64
MAX_JSON_NODES = 250_000
MAX_STRING_LENGTH = 1_000_000
MAX_EVENTS = 2000
SCORE_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
STANDINGS_BASE = "https://site.api.espn.com/apis/v2/sports/"
RANKINGS_BASE = "https://site.api.espn.com/apis/site/v2/sports/"
F1_STANDINGS_URL = STANDINGS_BASE + "racing/f1/standings"
STATUSES = {"ok", "stale", "unavailable"}


def timestamp(value, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Invalid sports timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid sports timestamp") from exc
    if parsed.utcoffset() is None:
        raise ValueError("Sports timestamp must include a timezone")


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {"priority_teams", "leagues"}:
        raise ValueError("Invalid sports configuration")
    priorities, leagues = config["priority_teams"], config["leagues"]
    if not isinstance(priorities, list) or any(not isinstance(x, str) or not x or len(x) > 100 for x in priorities):
        raise ValueError("Invalid priority team configuration")
    if not isinstance(leagues, list) or not 1 <= len(leagues) <= 50:
        raise ValueError("Invalid sports league list")
    names, paths = set(), set()
    allowed = {"name", "enabled", "espn_path", "color", "standings", "standings_type", "scores_type"}
    for league in leagues:
        if not isinstance(league, dict) or set(league) - allowed or not {"name", "enabled", "espn_path", "color", "standings"} <= set(league):
            raise ValueError("Invalid league fields")
        if not isinstance(league["name"], str) or not league["name"].strip() or len(league["name"]) > 100 or league["name"] in names:
            raise ValueError("Invalid or duplicate league name")
        names.add(league["name"])
        if type(league["enabled"]) is not bool or type(league["standings"]) is not bool:
            raise ValueError("Invalid league state")
        path = league["espn_path"]
        if not isinstance(path, str) or len(path) > 200 or not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*(?:/[a-z0-9]+(?:[.-][a-z0-9]+)*)*", path) or path in paths:
            raise ValueError("Invalid or duplicate ESPN path")
        paths.add(path)
        if not isinstance(league["color"], str) or not re.fullmatch(r"#[0-9a-fA-F]{3,8}", league["color"]):
            raise ValueError("Invalid league color")
        if league.get("standings_type", "division") not in {"division", "rankings", "soccer", "f1"}:
            raise ValueError("Invalid standings type")
        if league.get("scores_type", "default") not in {"default", "racing"}:
            raise ValueError("Invalid scores type")


def expected_urls(config):
    validate_config(config)
    urls = []
    for league in config["leagues"]:
        if not league["enabled"]:
            continue
        path = league["espn_path"]
        urls.append(SCORE_BASE + path + "/scoreboard")
        if league["standings"]:
            kind = league.get("standings_type", "division")
            if kind == "rankings":
                urls.append(RANKINGS_BASE + path + "/rankings")
            elif kind == "f1":
                urls.append(F1_STANDINGS_URL)
            else:
                urls.append(STANDINGS_BASE + path + "/standings")
    if len(urls) != len(set(urls)):
        raise ValueError("Duplicate ESPN endpoint in sports configuration")
    return urls


def validate_json_tree(payload):
    if not isinstance(payload, dict):
        raise ValueError("Sports payload must be a JSON object")
    stack, nodes = [(payload, 0)], 0
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            raise ValueError("Sports payload is too complex")
        if isinstance(value, dict):
            for key, child in value.items():
                if not isinstance(key, str) or len(key) > MAX_STRING_LENGTH:
                    raise ValueError("Invalid sports payload key")
                stack.append((child, depth + 1))
        elif isinstance(value, list):
            stack.extend((child, depth + 1) for child in value)
        elif isinstance(value, str):
            if len(value) > MAX_STRING_LENGTH:
                raise ValueError("Sports payload string is too long")
        elif value is None or isinstance(value, (bool, int)):
            continue
        elif isinstance(value, float) and math.isfinite(value):
            continue
        else:
            raise ValueError("Invalid sports payload value")
    try:
        packed = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Invalid sports payload JSON") from exc
    if len(packed) > MAX_ENTRY_BYTES:
        raise ValueError("Sports payload exceeds 4 MiB")


def _has_fields(value, allowed, required=()):
    if not isinstance(value, dict) or set(value) - allowed or not set(required) <= set(value):
        raise ValueError("Invalid projected ESPN fields")


def _validate_status(status, required=False):
    if status is None:
        if required:
            raise ValueError("Competition status is required")
        return
    _has_fields(status, {"type", "period", "displayClock", "displayPeriod", "periodPrefix"}, {"type"})
    if status["type"] is None:
        if required:
            raise ValueError("Competition status type is required")
        return
    _has_fields(status["type"], {"name", "shortDetail", "detail", "description", "state", "completed"}, {"name"})
    if not isinstance(status["type"]["name"], str) or not status["type"]["name"]:
        raise ValueError("Competition status name is required")


def _validate_links(links):
    if links is None:
        return
    if not isinstance(links, list) or len(links) > 100:
        raise ValueError("Invalid projected ESPN links")
    for link in links:
        _has_fields(link, {"href", "text"})
        if any(not isinstance(value, str) or len(value) > 4096 for value in link.values()):
            raise ValueError("Invalid projected ESPN link")
        if "href" in link:
            parsed = urlparse(link["href"])
            try:
                port = parsed.port
            except ValueError as exc:
                raise ValueError("Invalid projected ESPN link URL") from exc
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or port not in (None, 80, 443):
                raise ValueError("Unsafe projected ESPN link URL")


def _validate_scoreboard(payload, racing=False):
    _has_fields(payload, {"events"}, {"events"})
    events = payload["events"]
    if not isinstance(events, list) or len(events) > MAX_EVENTS:
        raise ValueError("Invalid ESPN event list")
    for event in events:
        _has_fields(event, {"date", "name", "shortName", "status", "competitions"}, {"competitions"})
        _validate_status(event.get("status"))
        if not isinstance(event["competitions"], list) or not 1 <= len(event["competitions"]) <= 20:
            raise ValueError("Invalid ESPN competitions")
        for competition in event["competitions"]:
            _has_fields(competition, {"date", "name", "shortName", "status", "links", "competitors", "broadcasts"}, {"date", "status", "competitors"})
            if not isinstance(competition["date"], str) or not competition["date"]:
                raise ValueError("Competition date is required")
            _validate_status(competition.get("status"), required=True)
            _validate_links(competition.get("links"))
            broadcasts = competition.get("broadcasts", [])
            if not isinstance(broadcasts, list) or len(broadcasts) > 50:
                raise ValueError("Invalid projected ESPN broadcasts")
            for broadcast in broadcasts:
                _has_fields(broadcast, {"market", "names"}, {"market", "names"})
                if (not isinstance(broadcast["market"], str) or len(broadcast["market"]) > 100
                        or not isinstance(broadcast["names"], list) or len(broadcast["names"]) > 30
                        or any(not isinstance(name, str) or not name or len(name) > 100 for name in broadcast["names"])):
                    raise ValueError("Invalid projected ESPN broadcast names")
            competitors = competition["competitors"]
            if not isinstance(competitors, list) or len(competitors) > 100:
                raise ValueError("Invalid ESPN competitors")
            sides = set()
            for competitor in competitors:
                _has_fields(competitor, {"homeAway", "winner", "score", "order", "displayClock", "team", "athlete"})
                if competitor.get("homeAway") in {"home", "away"}:
                    sides.add(competitor["homeAway"])
                if competitor.get("team") is not None:
                    _has_fields(competitor["team"], {"abbreviation", "shortDisplayName", "displayName"})
                    if not (competitor["team"].get("abbreviation") or competitor["team"].get("shortDisplayName")):
                        raise ValueError("Team scoreboard competitor has no display name")
                if competitor.get("athlete") is not None:
                    _has_fields(competitor["athlete"], {"shortName", "displayName"})
                if not racing and competitor.get("homeAway") in {"home", "away"} and not isinstance(competitor.get("team"), dict):
                    raise ValueError("Team scoreboard competitor has no team")
            if not racing and sides != {"home", "away"}:
                raise ValueError("Team scoreboard entry lacks home and away competitors")


def _validate_standings_group(group, depth=0):
    if depth > 32:
        raise ValueError("Standings groups are too deeply nested")
    _has_fields(group, {"name", "abbreviation", "children", "standings"})
    if "children" in group:
        if not isinstance(group["children"], list) or len(group["children"]) > 1000:
            raise ValueError("Invalid standings children")
        for child in group["children"]:
            _validate_standings_group(child, depth + 1)
    if "standings" in group:
        standings = group["standings"]
        _has_fields(standings, {"entries"}, {"entries"})
        if not isinstance(standings["entries"], list) or len(standings["entries"]) > 5000:
            raise ValueError("Invalid standings entries")
        for entry in standings["entries"]:
            _has_fields(entry, {"team", "stats"}, {"team", "stats"})
            _has_fields(entry["team"], {"abbreviation", "shortDisplayName", "displayName"})
            if not isinstance(entry["stats"], list) or len(entry["stats"]) > 100:
                raise ValueError("Invalid standings stats")
            for stat in entry["stats"]:
                _has_fields(stat, {"name", "abbreviation", "displayValue", "value"})


def _validate_standings(payload):
    _has_fields(payload, {"name", "abbreviation", "children", "standings"})
    if "children" in payload:
        if not isinstance(payload["children"], list) or len(payload["children"]) > 1000:
            raise ValueError("Invalid standings groups")
        for child in payload["children"]:
            _validate_standings_group(child)
    if "standings" in payload:
        _validate_standings_group({"standings": payload["standings"]})
    if "children" not in payload and "standings" not in payload:
        raise ValueError("Standings payload has no groups or entries")


def _validate_rankings(payload):
    _has_fields(payload, {"rankings"}, {"rankings"})
    rankings = payload["rankings"]
    if not isinstance(rankings, list) or len(rankings) > 100:
        raise ValueError("Invalid ESPN rankings")
    for ranking in rankings:
        _has_fields(ranking, {"name", "shortName", "type", "ranks"})
        if "ranks" not in ranking:
            continue
        if not isinstance(ranking["ranks"], list) or len(ranking["ranks"]) > 1000:
            raise ValueError("Invalid ranking rows")
        for rank in ranking["ranks"]:
            _has_fields(rank, {"current", "previous", "recordSummary", "team"}, {"team"})
            _has_fields(rank["team"], {"location", "name", "abbreviation", "nickname"})


def validate_payload(url, payload, racing_urls=()):
    validate_json_tree(payload)
    if url.endswith("/scoreboard"):
        _validate_scoreboard(payload, racing=url in racing_urls)
    elif url.endswith("/rankings"):
        _validate_rankings(payload)
    elif url.endswith("/standings"):
        _validate_standings(payload)
    else:
        raise ValueError("Unknown ESPN endpoint type")
    return payload


def validate_entry(url, row, racing=False):
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid ESPN endpoint port") from exc
    if parsed.scheme != "https" or parsed.hostname != "site.api.espn.com" or parsed.username or parsed.password or port not in (None, 443):
        raise ValueError("Unsafe ESPN endpoint")
    if not isinstance(row, dict) or set(row) != {"payload", "generatedAt", "lastAttemptAt", "status"} or row["status"] not in STATUSES:
        raise ValueError("Invalid sports entry fields")
    timestamp(row["generatedAt"], optional=True)
    timestamp(row["lastAttemptAt"])
    if row["status"] == "unavailable":
        if row["payload"] is not None or row["generatedAt"] is not None:
            raise ValueError("Unavailable sports entry cannot contain a payload")
    else:
        if row["payload"] is None or row["generatedAt"] is None:
            raise ValueError("Available sports entry must retain a payload")
        validate_payload(url, row["payload"], {url} if racing else ())


def validate_snapshot(snapshot, config):
    urls = expected_urls(config)
    racing_urls = {
        SCORE_BASE + league["espn_path"] + "/scoreboard"
        for league in config["leagues"] if league["enabled"] and league.get("scores_type") == "racing"
    }
    if not isinstance(snapshot, dict) or set(snapshot) != {"version", "lastAttemptAt", "entries"} or type(snapshot["version"]) is not int or snapshot["version"] != 1:
        raise ValueError("Invalid sports snapshot schema")
    timestamp(snapshot["lastAttemptAt"])
    entries = snapshot["entries"]
    if not isinstance(entries, dict) or list(entries) != urls:
        raise ValueError("Sports snapshot endpoints do not match configuration")
    for url, row in entries.items():
        validate_entry(url, row, racing=url in racing_urls)
    try:
        encoded = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ValueError("Invalid sports snapshot JSON") from exc
    if len(encoded) > MAX_SNAPSHOT_BYTES:
        raise ValueError("Sports snapshot exceeds 4 MiB")
    return snapshot


def normalize_previous(previous, config):
    """Keep valid current endpoints from a prior config and drop removed URLs."""
    urls = expected_urls(config)
    if previous is None:
        return {}
    if not isinstance(previous, dict) or set(previous) != {"version", "lastAttemptAt", "entries"} or type(previous["version"]) is not int or previous["version"] != 1:
        raise ValueError("Invalid previous sports snapshot")
    timestamp(previous["lastAttemptAt"])
    entries = previous["entries"]
    if not isinstance(entries, dict) or len(entries) > 100:
        raise ValueError("Invalid previous sports entries")
    racing_urls = {
        SCORE_BASE + league["espn_path"] + "/scoreboard"
        for league in config["leagues"] if league["enabled"] and league.get("scores_type") == "racing"
    }
    retained = {}
    for url, row in entries.items():
        parsed = urlparse(url) if isinstance(url, str) else None
        try:
            port = parsed.port if parsed is not None else None
        except ValueError as exc:
            raise ValueError("Unsafe previous ESPN endpoint") from exc
        if (parsed is None or parsed.scheme != "https" or parsed.hostname != "site.api.espn.com"
                or parsed.username or parsed.password or port not in (None, 443)):
            raise ValueError("Unsafe previous ESPN endpoint")
        if url in urls:
            validate_entry(url, row, racing=url in racing_urls)
            retained[url] = row
    return {url: retained[url] for url in urls if url in retained}


def validate(path, config_path=None):
    path = Path(path)
    if path.stat().st_size > MAX_SNAPSHOT_BYTES:
        raise ValueError("Sports snapshot too large")
    if config_path is None:
        config_path = Path(__file__).resolve().parents[1] / "sports-config.json"
    snapshot = json.loads(path.read_text(encoding="utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Invalid JSON constant: " + value)))
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    return validate_snapshot(snapshot, config)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("snapshot", type=Path)
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    validate(args.snapshot, args.config)
    print("Sports snapshot schema validated")
