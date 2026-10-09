#!/usr/bin/env python3
"""Strict validation for the deliberately small public news snapshot."""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

MAX_FEEDS = 40
MAX_ITEMS_PER_FEED = 8
MAX_TITLE = 300
MAX_DATE = 80
STATUSES = {"ok", "stale", "unavailable"}
REQUIRED_CATEGORIES = ["top", "general", "tech", "sports", "business", "science", "devops"]


def timestamp(value, optional=False):
    if optional and value is None:
        return
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("Invalid timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None:
            raise ValueError("Timezone required")
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc


def public_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError("Invalid URL")
    try:
        parsed = urlparse(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Invalid public URL") from exc
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid public URL")
    if port not in (None, 80, 443):
        raise ValueError("Unexpected URL port")
    if parsed.hostname.lower() in {"localhost", "localhost.localdomain"} or parsed.hostname.replace(".", "").isdigit():
        raise ValueError("Non-public URL")


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {"schemaVersion", "categories", "feeds"} or type(config["schemaVersion"]) is not int or config["schemaVersion"] != 1:
        raise ValueError("Invalid configuration schema")
    cats = config["categories"]
    if cats != REQUIRED_CATEGORIES:
        raise ValueError("Invalid categories")
    feeds = config["feeds"]
    if not isinstance(feeds, list) or not 1 <= len(feeds) <= MAX_FEEDS:
        raise ValueError("Invalid feed count")
    ids = set()
    for feed in feeds:
        if not isinstance(feed, dict) or set(feed) != {"id", "category", "name", "url", "limit"}:
            raise ValueError("Invalid feed definition")
        if not isinstance(feed["id"], str) or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", feed["id"]) or feed["id"] in ids:
            raise ValueError("Invalid or duplicate feed ID")
        ids.add(feed["id"])
        if feed["category"] not in cats:
            raise ValueError("Unknown feed category")
        if not isinstance(feed["name"], str) or not feed["name"].strip() or len(feed["name"]) > 100:
            raise ValueError("Invalid feed name")
        public_url(feed["url"])
        if type(feed["limit"]) is not int or not 1 <= feed["limit"] <= MAX_ITEMS_PER_FEED:
            raise ValueError("Invalid item limit")


def validate_digest(digest, config):
    validate_config(config)
    if not isinstance(digest, dict) or set(digest) != {"schemaVersion", "generatedAt", "lastAttemptAt", "provenance", "feeds"} or type(digest["schemaVersion"]) is not int or digest["schemaVersion"] != 1:
        raise ValueError("Invalid digest schema")
    timestamp(digest["generatedAt"], optional=True)
    timestamp(digest["lastAttemptAt"])
    if digest["provenance"] != "publisher-rss-headlines":
        raise ValueError("Invalid provenance")
    rows = digest["feeds"]
    if not isinstance(rows, list) or len(rows) != len(config["feeds"]):
        raise ValueError("Feed count does not match configuration")
    for row, spec in zip(rows, config["feeds"]):
        if not isinstance(row, dict) or set(row) != {"id", "category", "name", "url", "status", "generatedAt", "lastAttemptAt", "items"}:
            raise ValueError("Invalid feed snapshot")
        for key in ("id", "category", "name", "url"):
            if row[key] != spec[key]:
                raise ValueError("Feed identity mismatch")
        if row["status"] not in STATUSES:
            raise ValueError("Invalid feed status")
        timestamp(row["generatedAt"], optional=True)
        timestamp(row["lastAttemptAt"])
        items = row["items"]
        if not isinstance(items, list) or len(items) > spec["limit"]:
            raise ValueError("Invalid item count")
        if row["status"] == "ok" and not items:
            raise ValueError("Successful feed cannot be empty")
        for item in items:
            if not isinstance(item, dict) or set(item) != {"title", "url", "date"}:
                raise ValueError("Invalid headline")
            if not isinstance(item["title"], str) or not item["title"].strip() or len(item["title"]) > MAX_TITLE:
                raise ValueError("Invalid headline title")
            public_url(item["url"])
            if not isinstance(item["date"], str) or len(item["date"]) > MAX_DATE:
                raise ValueError("Invalid headline date")
    return True


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("digest", type=Path)
    parser.add_argument("config", type=Path)
    args = parser.parse_args()
    validate_digest(json.loads(args.digest.read_text()), json.loads(args.config.read_text()))
    print("News digest schema valid")


if __name__ == "__main__":
    main()
