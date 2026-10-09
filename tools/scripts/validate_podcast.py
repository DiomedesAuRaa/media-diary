#!/usr/bin/env python3
"""Validate the untrusted fetch artifact before repository publication."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

def validate(path):
    if path.stat().st_size > 4 * 1024 * 1024:
        raise ValueError('Manifest too large')
    data = json.loads(path.read_text())
    if not isinstance(data, list) or not 1 <= len(data) <= 100:
        raise ValueError('Invalid manifest')
    names = set()
    for show in data:
        if not isinstance(show, dict) or set(show) != {'name', 'episodes', 'generatedAt', 'lastAttemptAt', 'fetchStatus'}:
            raise ValueError('Invalid show fields')
        name = show['name']
        if not isinstance(name, str) or not name.strip() or len(name) > 200 or name in names:
            raise ValueError('Invalid show name')
        names.add(name)
        if show['fetchStatus'] not in ('ok', 'stale', 'unavailable'):
            raise ValueError('Invalid refresh status')
        for key in ('generatedAt', 'lastAttemptAt'):
            value = show[key]
            if key == 'generatedAt' and value is None:
                continue
            if not isinstance(value, str) or datetime.fromisoformat(value.replace('Z', '+00:00')).tzinfo is None:
                raise ValueError('Invalid timestamp')
        if not isinstance(show['episodes'], list) or len(show['episodes']) > 5:
            raise ValueError('Invalid episodes')
        for episode in show['episodes']:
            if not isinstance(episode, dict) or set(episode) != {'title', 'date', 'dateSort', 'audioUrl'}:
                raise ValueError('Invalid episode fields')
            if not all(isinstance(value, str) for value in episode.values()) or len(episode['title']) > 1000:
                raise ValueError('Invalid episode text')
            parsed = urlparse(episode['audioUrl'])
            if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or len(episode['audioUrl']) > 4096 or parsed.port not in (None, 80, 443):
                raise ValueError('Invalid audio URL')
    return data

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    validate(args.manifest)
    print('Podcast artifact schema validated')
