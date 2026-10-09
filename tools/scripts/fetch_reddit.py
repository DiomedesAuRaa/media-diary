#!/usr/bin/env python3
"""Public Reddit RSS refresh, preserving configured feeds and last-good posts."""
import argparse
import calendar
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import feedparser
import requests
from fetch_feeds import fetch_bytes, public_url

def validate_config(config):
    if not isinstance(config, dict) or set(config) != {'subreddits', 'feeds'}:
        raise ValueError('Invalid Reddit configuration')
    subs, feeds = config['subreddits'], config['feeds']
    if not isinstance(subs, list) or not 1 <= len(subs) <= 30 or len(set(subs)) != len(subs) or any(not isinstance(s, str) or not re.fullmatch(r'[A-Za-z0-9_]{1,50}', s) for s in subs):
        raise ValueError('Invalid subreddit names')
    if not isinstance(feeds, list) or not 1 <= len(feeds) <= 10:
        raise ValueError('Invalid feeds')
    labels = set()
    for feed in feeds:
        if not isinstance(feed, dict) or set(feed) != {'label', 'sort', 'timeframe'} or not isinstance(feed['label'], str) or not feed['label'].strip() or len(feed['label']) > 100 or feed['label'] in labels:
            raise ValueError('Invalid feed label')
        labels.add(feed['label'])
        if feed['sort'] not in ('top', 'hot', 'new', 'rising') or feed['timeframe'] not in (None, 'hour', 'day', 'week', 'month', 'year', 'all'):
            raise ValueError('Invalid feed query')

def parse_posts(body, subreddit):
    feed = feedparser.parse(body)
    posts = []
    for entry in feed.entries:
        url = entry.get('link', '')
        try:
            public_url(url)
        except ValueError:
            continue
        title = entry.get('title', '')
        if not isinstance(title, str) or not title.strip():
            continue
        author = str(entry.get('author', '[deleted]'))
        if author.startswith('/u/'):
            author = author[3:]
        elif author.startswith('u/'):
            author = author[2:]
        parsed = entry.get('published_parsed') or entry.get('updated_parsed')
        identifier = str(entry.get('id', '')).split('_')[-1][:200]
        posts.append({'title': title[:1000], 'author': author[:200], 'score': 0, 'url': url, 'selftext': '', 'created_utc': calendar.timegm(parsed) if parsed else 0, 'num_comments': 0, 'id': identifier, 'subreddit': subreddit, 'link_url': url, 'is_self': 'reddit.com/r/' in url, 'upvote_ratio': 0, 'flair': '', 'comments': [], 'metadata_source': 'rss'})
        if len(posts) == 5:
            break
    if not posts:
        raise ValueError('No usable posts')
    return posts

def refresh(config, previous, fetch=None, now=None, delay=2, budget=600):
    validate_config(config)
    if not isinstance(previous, dict):
        raise ValueError('Invalid previous digest')
    stamp = now or datetime.now(timezone.utc).isoformat(timespec='seconds')
    # Keep each RSS request short so the overall refresh budget can stop before
    # the workflow timeout even when a feed stalls.
    fetch = fetch or (lambda url: fetch_bytes(url, attempts=1, max_redirects=3, total_timeout=20))
    data, errors, statuses = {}, {}, {}
    successes = 0
    deadline = time.monotonic() + budget
    for subreddit in config['subreddits']:
        data[subreddit], statuses[subreddit] = {}, {}
        for feed in config['feeds']:
            label = feed['label']
            prior = previous.get('data', {}).get(subreddit, {}).get(label, [])
            old_status = previous.get('feed_status', {}).get(subreddit, {}).get(label, {})
            generated = old_status.get('generated_at', previous.get('timestamp'))
            try:
                if time.monotonic() >= deadline:
                    raise ValueError('Refresh budget exhausted')
                if delay:
                    time.sleep(delay)
                url = 'https://www.reddit.com/r/%s/%s.rss' % (subreddit, feed['sort'])
                if feed['sort'] == 'top' and feed['timeframe']:
                    url += '?' + urlencode({'t': feed['timeframe']})
                posts = parse_posts(fetch(url), subreddit)
                successes += 1
                generated, status = stamp, 'ok'
            except (requests.RequestException, ValueError, OSError):
                posts = prior
                status = 'stale' if prior else 'unavailable'
                errors.setdefault(subreddit, []).append(label)
            data[subreddit][label] = posts
            statuses[subreddit][label] = {'status': status, 'generated_at': generated, 'last_attempt_at': stamp}
    count = len(config['subreddits']) * len(config['feeds'])
    refresh_status = 'ok' if successes == count else 'partial' if successes else 'stale' if any(posts for feeds in data.values() for posts in feeds.values()) else 'unavailable'
    timestamp = stamp if successes else previous.get('timestamp')
    generated_at = datetime.fromisoformat(stamp).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') if successes else previous.get('generated_at')
    return {'schema_version': 2, 'timestamp': timestamp, 'generated_at': generated_at, 'subreddits_count': len(data), 'total_posts': sum(len(posts) for feeds in data.values() for posts in feeds.values()), 'feeds': [feed['label'] for feed in config['feeds']], 'comments_feed': 'Disabled for RSS', 'fetch_errors': errors, 'data': data, 'refresh_status': refresh_status, 'last_attempt_at': stamp, 'feed_status': statuses}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    path = args.root / 'reddit-digest.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    config = json.loads((args.root / 'scripts/reddit-config.json').read_text())
    result = refresh(config, previous)
    temporary = path.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    os.replace(temporary, path)
    print('Reddit RSS refresh status:', result['refresh_status'])

if __name__ == '__main__':
    main()
