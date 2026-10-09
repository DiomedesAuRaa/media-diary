#!/usr/bin/env python3
"""Refresh public podcast metadata; retain last good episodes on failures."""
import argparse
import ipaddress
import json
import os
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import feedparser
import requests
import yaml

MAX_BYTES = 4 * 1024 * 1024
MAX_EPISODES = 5

def public_url(value, resolve=False):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError("Invalid URL")
    parsed = urlparse(value)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Invalid public URL")
    if parsed.port not in (None, 80, 443):
        raise ValueError("Unexpected URL port")
    if resolve:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError("Non-public feed host")
    return value

def fetch_bytes(url, attempts=3, max_redirects=5, total_timeout=30):
    # Validate every redirect; do not forward credentials or environment proxies.
    with requests.Session() as session:
        session.trust_env = False
        session.headers["User-Agent"] = "Media-Diary-feed-refresh/1.0 (+https://github.com/DiomedesAuRaa/media-diary)"
        for attempt in range(attempts):
            try:
                target = url
                deadline = time.monotonic() + total_timeout
                for redirect in range(max_redirects + 1):
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ValueError("Feed deadline exceeded")
                    public_url(target, resolve=True)
                    with session.get(target, timeout=(min(5, remaining), min(15, remaining)), stream=True, allow_redirects=False) as response:
                        if response.is_redirect:
                            if redirect == max_redirects:
                                raise ValueError("Too many redirects")
                            target = urljoin(target, response.headers.get("Location", ""))
                            continue
                        response.raise_for_status()
                        body = bytearray()
                        for chunk in response.iter_content(65536):
                            if time.monotonic() > deadline:
                                raise ValueError("Feed deadline exceeded")
                            body.extend(chunk)
                            if len(body) > MAX_BYTES:
                                raise ValueError("Feed too large")
                        return bytes(body)
                raise ValueError("Too many redirects")
            except (requests.RequestException, ValueError, OSError):
                if attempt == attempts - 1:
                    raise
                time.sleep(attempt + 1)

def parse_episodes(body):
    feed = feedparser.parse(body)
    if not feed.entries:
        raise ValueError("No usable entries")
    episodes = []
    for entry in feed.entries:
        enclosures = getattr(entry, "enclosures", [])
        audio = next((item.get("href") for item in enclosures if item.get("href")), None)
        if not audio:
            continue
        try:
            public_url(audio)
        except ValueError:
            continue
        title = getattr(entry, "title", "Untitled")
        if not isinstance(title, str) or not title.strip():
            continue
        parsed = next((getattr(entry, key, None) for key in ("published_parsed", "updated_parsed", "created_parsed") if getattr(entry, key, None)), None)
        stamp = datetime(*parsed[:6]) if parsed else None
        episodes.append({"title": title[:1000], "date": stamp.strftime("%b %d, %Y") if stamp else "", "dateSort": stamp.strftime("%Y-%m-%d") if stamp else "", "audioUrl": audio})
        if len(episodes) == MAX_EPISODES:
            break
    if not episodes:
        raise ValueError("No playable episodes")
    return episodes

def refresh(config, previous, fetch=fetch_bytes, now=None):
    subscriptions = config.get("podcasts") if isinstance(config, dict) else None
    if not isinstance(subscriptions, list) or not 1 <= len(subscriptions) <= 100:
        raise ValueError("Invalid podcast configuration")
    old = {item["name"]: item for item in previous if isinstance(item, dict) and isinstance(item.get("name"), str)}
    names = set()
    result = []
    stamp = now or datetime.now(timezone.utc).isoformat(timespec="seconds")
    for sub in subscriptions:
        if not isinstance(sub, dict) or not isinstance(sub.get("name"), str) or not sub["name"].strip() or len(sub["name"]) > 200 or sub["name"] in names:
            raise ValueError("Invalid or duplicate podcast name")
        name = sub["name"]
        names.add(name)
        public_url(sub.get("feed_url"))
        prior = old.get(name, {})
        try:
            episodes = parse_episodes(fetch(sub["feed_url"]))
            item = {"name": name, "episodes": episodes, "generatedAt": stamp, "lastAttemptAt": stamp, "fetchStatus": "ok"}
        except (requests.RequestException, ValueError, OSError):
            item = {"name": name, "episodes": prior.get("episodes", []), "generatedAt": prior.get("generatedAt"), "lastAttemptAt": stamp, "fetchStatus": "stale" if prior.get("episodes") else "unavailable"}
        result.append(item)
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    config = yaml.safe_load((args.root / "sub.yaml").read_text())
    path = args.root / "podcast-manifest.json"
    previous = json.loads(path.read_text()) if path.exists() else []
    if not isinstance(previous, list):
        raise ValueError("Invalid previous manifest")
    result = refresh(config, previous)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(result, indent=2) + "\n")
    os.replace(temporary, path)
    print("Manifest refreshed: %d feeds, %d successful" % (len(result), sum(item["fetchStatus"] == "ok" for item in result)))

if __name__ == "__main__":
    main()
