from __future__ import annotations

import csv
import os
import tempfile
import threading
from functools import wraps
from pathlib import Path
from datetime import datetime
from typing import Any

from app.config import csv_path, get_media_type, watchlist_path


storage_lock = threading.RLock()


def synchronized(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        with storage_lock:
            return func(*args, **kwargs)
    return wrapped


def _write_rows(path: Path, columns: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".diary-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in rows:
                writer.writerow({column: row.get(column, "") for column in columns})
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def format_date_mmddyy(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%m/%d/%y")


@synchronized
def read_entries(media_type: str, limit: int | None = None, *, use_watchlist: bool = False, offset: int = 0) -> list[dict[str, str]]:
    path = watchlist_path(media_type) if use_watchlist else csv_path(media_type)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if limit is not None:
        return rows[offset:offset + limit]
    return rows[offset:]


@synchronized
def title_exists(media_type: str, title: str, *, use_watchlist: bool = False) -> bool:
    config = get_media_type(media_type)
    title_column = config["title_column"]
    normalized = title.strip().casefold()
    for row in read_entries(media_type, use_watchlist=use_watchlist):
        existing = (row.get(title_column) or "").strip().casefold()
        if existing == normalized:
            return True
    return False


@synchronized
def prepend_entry(media_type: str, row: dict[str, str], *, use_watchlist: bool = False) -> dict[str, str]:
    config = get_media_type(media_type)
    path = watchlist_path(media_type) if use_watchlist else csv_path(media_type)
    path.parent.mkdir(parents=True, exist_ok=True)

    columns = config["columns"]
    normalized = {column: (row.get(column) or "").strip() for column in columns}

    existing_rows: list[dict[str, str]] = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            existing_rows = list(csv.DictReader(handle))

    _write_rows(path, columns, [normalized, *existing_rows])

    return normalized


def build_row(
    media_type: str,
    *,
    title: str,
    rating: str,
    date_rated: str | None = None,
    api_values: dict[str, str] | None = None,
) -> dict[str, str]:
    config = get_media_type(media_type)
    api_values = api_values or {}
    row: dict[str, Any] = {}

    for column in config["columns"]:
        row[column] = ""

    row[config["title_column"]] = title.strip()
    row["Rating"] = str(rating).strip()

    date_str = date_rated.strip() if date_rated else format_date_mmddyy()
    for field in config["auto_fields"]:
        row[field] = date_str

    for field in config["api_fields"]:
        row[field] = api_values.get(field, "").strip()

    return row


def build_watchlist_row(
    media_type: str,
    *,
    title: str,
    api_values: dict[str, str] | None = None,
) -> dict[str, str]:
    config = get_media_type(media_type)
    api_values = api_values or {}
    row: dict[str, Any] = {}

    for column in config["columns"]:
        row[column] = ""

    row[config["title_column"]] = title.strip()
    # Rating and auto_fields (Date Watched) are left empty for watchlist entries

    for field in config["api_fields"]:
        row[field] = api_values.get(field, "").strip()

    return row


@synchronized
def update_entry_rating(media_type: str, title: str, rating: str, date_rated: str | None = None) -> dict[str, str] | None:
    config = get_media_type(media_type)
    path = csv_path(media_type)
    if not path.exists():
        return None

    title_column = config["title_column"]
    auto_fields = config["auto_fields"]
    date_column = auto_fields[0] if auto_fields else "Date Watched/Rated"

    existing_rows = read_entries(media_type)
    updated_row = None

    for row in existing_rows:
        row_title = (row.get(title_column) or "").strip()
        row_date = (row.get(date_column) or "").strip()
        
        match_title = row_title.casefold() == title.strip().casefold()
        match_date = (date_rated is None) or (row_date == date_rated.strip())
        
        if updated_row is None and match_title and match_date:
            row["Rating"] = str(rating).strip()
            updated_row = row

    if updated_row is not None:
        columns = config["columns"]
        _write_rows(path, columns, existing_rows)
        return updated_row

    return None


@synchronized
def delete_entry(media_type: str, title: str, date_rated: str | None = None, *, use_watchlist: bool = False) -> bool:
    config = get_media_type(media_type)
    path = watchlist_path(media_type) if use_watchlist else csv_path(media_type)
    if not path.exists():
        return False

    title_column = config["title_column"]
    auto_fields = config["auto_fields"]
    date_column = auto_fields[0] if auto_fields else "Date Watched/Rated"

    existing_rows = read_entries(media_type, use_watchlist=use_watchlist)
    new_rows = []
    deleted = False

    for row in existing_rows:
        row_title = (row.get(title_column) or "").strip()
        row_date = (row.get(date_column) or "").strip()
        
        if use_watchlist:
            # Watchlist rows do not have a recorded date, so match purely on the title
            match = row_title.casefold() == title.strip().casefold()
        else:
            match = row_title.casefold() == title.strip().casefold() and row_date == (date_rated or "").strip()
        
        if not deleted and match:
            deleted = True
            continue
        new_rows.append(row)

    if deleted:
        columns = config["columns"]
        _write_rows(path, columns, new_rows)
        return True

    return False

@synchronized
def replace_entry_by_key(media_type: str, key: str, replacement: dict[str, str] | None, *, use_watchlist: bool = False) -> dict[str, str] | None:
    """Address the exact unchanged row, including repeated titles/dates; stale forms fail safely."""
    from app.presentation import records
    rows = read_entries(media_type, use_watchlist=use_watchlist)
    data = {media_type + ('_watchlist' if use_watchlist else ''): rows}
    matched = next((r for r in records(data, 'later' if use_watchlist else 'diary') if r['key'] == key), None)
    if matched is None:
        return None
    index = next(i for i, r in enumerate(records(data, 'later' if use_watchlist else 'diary')) if r['key'] == key)
    original = rows[index]
    if replacement is None:
        rows.pop(index)
    else:
        rows[index] = {column: str(replacement.get(column, '')).strip() for column in get_media_type(media_type)['columns']}
    path = watchlist_path(media_type) if use_watchlist else csv_path(media_type)
    _write_rows(path, get_media_type(media_type)['columns'], rows)
    return original
