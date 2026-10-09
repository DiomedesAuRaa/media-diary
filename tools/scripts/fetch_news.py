#!/usr/bin/env python3
"""Bounded RSS headline collector with durable per-feed last-good retention."""
import argparse
import json
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import feedparser
import requests
from fetch_feeds import fetch_bytes, public_url
from validate_news import validate_config, validate_digest

MAX_WORKERS = 4
TOTAL_FETCH_BUDGET = 15


def stamp_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_headlines(body, limit):
    parsed = feedparser.parse(body)
    if not parsed.entries:
        raise ValueError("No RSS entries")
    result, seen = [], set()
    for entry in parsed.entries:
        title = entry.get("title", "")
        link = entry.get("link", "")
        if not isinstance(title, str) or not title.strip():
            continue
        try:
            public_url(link)
        except ValueError:
            continue
        key = (" ".join(title.split()).casefold(), link.rstrip("/").casefold())
        if key in seen:
            continue
        seen.add(key)
        title = " ".join(title.split())[:300]
        parsed_date = entry.get("published_parsed") or entry.get("updated_parsed")
        date = ""
        if parsed_date:
            try:
                date = datetime(*parsed_date[:6], tzinfo=timezone.utc).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OverflowError):
                pass
        result.append({"title": title, "url": link, "date": date})
        if len(result) >= limit:
            break
    if not result:
        raise ValueError("No usable headlines")
    return result


def _fetch_one(spec):
    # Existing shared fetcher validates each redirect and enforces byte limits.
    body = fetch_bytes(spec["url"], attempts=1, max_redirects=3, total_timeout=12)
    return parse_headlines(body, spec["limit"])


def refresh(config, previous, fetch=None, now=None, budget=TOTAL_FETCH_BUDGET):
    validate_config(config)
    if previous is not None:
        validate_digest(previous, config)
    stamp = now or stamp_now()
    prior_rows = {row["id"]: row for row in previous["feeds"]} if previous else {}
    fetcher = fetch or _fetch_one
    rows = [None] * len(config["feeds"])
    work, completed = queue.Queue(), queue.Queue()
    for index, spec in enumerate(config["feeds"]):
        work.put((index, spec))
    def worker():
        while True:
            try:
                index, spec = work.get_nowait()
            except queue.Empty:
                return
            try:
                completed.put((index, spec, fetcher(spec), None))
            except Exception as exc:
                completed.put((index, spec, None, exc))
            finally:
                work.task_done()
    # Daemon threads let the publisher honor the total deadline even if DNS or
    # a remote server ignores its socket timeout. Workers are strictly capped.
    for _ in range(min(MAX_WORKERS, len(config["feeds"]))):
        threading.Thread(target=worker, daemon=True).start()
    deadline = time.monotonic() + budget
    received = 0
    while received < len(config["feeds"]) and time.monotonic() < deadline:
        try:
            index, spec, items, error = completed.get(timeout=max(0.01, deadline - time.monotonic()))
        except queue.Empty:
            break
        received += 1
        old = prior_rows.get(spec["id"], {})
        if error is None and isinstance(items, list) and items:
            row = {**{key: spec[key] for key in ("id", "category", "name", "url")}, "status": "ok", "generatedAt": stamp, "lastAttemptAt": stamp, "items": items}
        else:
            row = {**{key: spec[key] for key in ("id", "category", "name", "url")}, "status": "stale" if old.get("items") else "unavailable", "generatedAt": old.get("generatedAt"), "lastAttemptAt": stamp, "items": old.get("items", [])}
        rows[index] = row
    for index, spec in enumerate(config["feeds"]):
        if rows[index] is None:
            old = prior_rows.get(spec["id"], {})
            rows[index] = {**{key: spec[key] for key in ("id", "category", "name", "url")}, "status": "stale" if old.get("items") else "unavailable", "generatedAt": old.get("generatedAt"), "lastAttemptAt": stamp, "items": old.get("items", [])}
    any_success = any(row["status"] == "ok" for row in rows)
    return {"schemaVersion": 1, "generatedAt": stamp if any_success else (previous or {}).get("generatedAt"), "lastAttemptAt": stamp, "provenance": "publisher-rss-headlines", "feeds": rows}


def atomic_write(path, data):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--budget", type=int, default=TOTAL_FETCH_BUDGET, choices=range(1, 16))
    args = parser.parse_args()
    config_path = args.root / "scripts/news-config.json"
    digest_path = args.root / "news-digest.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    previous = json.loads(digest_path.read_text(encoding="utf-8")) if digest_path.exists() else None
    result = refresh(config, previous, budget=args.budget)
    validate_digest(result, config)
    atomic_write(digest_path, result)
    counts = {status: sum(row["status"] == status for row in result["feeds"]) for status in ("ok", "stale", "unavailable")}
    print("News refresh: " + ", ".join(f"{key}={value}" for key, value in counts.items()))
    if counts["ok"] == 0:
        print("No feed refreshed; retained prior valid headlines where available", file=sys.stderr)


if __name__ == "__main__":
    main()
