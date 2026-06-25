from __future__ import annotations

import os
from pathlib import Path
from typing import Any

_root = os.environ.get("REPO_ROOT", "").strip()
REPO_ROOT = Path(_root) if _root else Path(__file__).resolve().parent.parent

MEDIA_TYPES: dict[str, dict[str, Any]] = {
    "movies": {
        "label": "Movies",
        "csv": "data/movies.csv",
        "watchlist_csv": "data/movies_watchlist.csv",
        "columns": [
            "Movie",
            "Date Watched/Rated",
            "Date Released",
            "Rating",
            "Director",
        ],
        "title_column": "Movie",
        "user_fields": ["Rating"],
        "auto_fields": ["Date Watched/Rated"],
        "api_fields": ["Date Released", "Director"],
        "provider": "tmdb_movie",
        "enabled": True,
    },
    "books": {
        "label": "Books",
        "csv": "data/books.csv",
        "watchlist_csv": "data/books_watchlist.csv",
        "columns": [
            "Book",
            "Date Read/Rated",
            "Date Published",
            "Rating",
            "Author",
        ],
        "title_column": "Book",
        "user_fields": ["Rating"],
        "auto_fields": ["Date Read/Rated"],
        "api_fields": ["Date Published", "Author"],
        "provider": "openlibrary",
        "enabled": True,
    },
    "tv": {
        "label": "TV Shows",
        "csv": "data/tv.csv",
        "watchlist_csv": "data/tv_watchlist.csv",
        "columns": [
            "Show",
            "Date Watched/Rated",
            "Date Premiered",
            "Rating",
            "Creator",
        ],
        "title_column": "Show",
        "user_fields": ["Rating"],
        "auto_fields": ["Date Watched/Rated"],
        "api_fields": ["Date Premiered", "Creator"],
        "provider": "tmdb_tv",
        "enabled": True,
    },
}


def get_media_type(media_type: str) -> dict[str, Any]:
    if media_type not in MEDIA_TYPES:
        raise KeyError(f"Unknown media type: {media_type}")
    config = MEDIA_TYPES[media_type]
    if not config.get("enabled"):
        raise KeyError(f"Media type not enabled: {media_type}")
    return config


def get_enabled_types() -> dict[str, dict[str, Any]]:
    return {key: value for key, value in MEDIA_TYPES.items() if value.get("enabled")}


def csv_path(media_type: str) -> Path:
    config = get_media_type(media_type)
    return REPO_ROOT / config["csv"]


def watchlist_path(media_type: str) -> Path:
    config = get_media_type(media_type)
    return REPO_ROOT / config["watchlist_csv"]