from __future__ import annotations

import csv
from datetime import datetime
from typing import Any

from app.config import csv_path, get_media_type


def format_date_mmddyy(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return dt.strftime("%m/%d/%y")


def read_entries(media_type: str, limit: int | None = None) -> list[dict[str, str]]:
    path = csv_path(media_type)
    if not path.exists():
        return []

    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    if limit is not None:
        return rows[:limit]
    return rows


def title_exists(media_type: str, title: str) -> bool:
    config = get_media_type(media_type)
    title_column = config["title_column"]
    normalized = title.strip().casefold()
    for row in read_entries(media_type):
        existing = (row.get(title_column) or "").strip().casefold()
        if existing == normalized:
            return True
    return False


def prepend_entry(media_type: str, row: dict[str, str]) -> dict[str, str]:
    config = get_media_type(media_type)
    path = csv_path(media_type)
    path.parent.mkdir(parents=True, exist_ok=True)

    columns = config["columns"]
    normalized = {column: (row.get(column) or "").strip() for column in columns}

    existing_rows: list[dict[str, str]] = []
    if path.exists():
        with path.open("r", encoding="utf-8", newline="") as handle:
            existing_rows = list(csv.DictReader(handle))

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerow(normalized)
        for existing in existing_rows:
            writer.writerow({column: existing.get(column, "") for column in columns})

    return normalized


def update_entry_rating(
    media_type: str,
    title: str,
    rating: str,
    date_rated: str | None = None
) -> dict[str, str] | None:
    config = get_media_type(media_type)
    path = csv_path(media_type)
    if not path.exists():
        return None

    title_column = config["title_column"]
    normalized_title = title.strip().casefold()
    columns = config["columns"]

    with path.open("r", encoding="utf-8", newline="") as handle:
        existing_rows = list(csv.DictReader(handle))

    updated_row = None
    for row in existing_rows:
        existing_title = (row.get(title_column) or "").strip().casefold()
        if existing_title == normalized_title:
            row["Rating"] = str(rating).strip()
            for field in config["auto_fields"]:
                row[field] = date_rated or format_date_mmddyy()
            updated_row = {column: str(row.get(column, "")).strip() for column in columns}
            break

    if updated_row:
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in existing_rows:
                writer.writerow({column: row.get(column, "") for column in columns})
        return updated_row

    return None


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

    for field in config["auto_fields"]:
        row[field] = date_rated or format_date_mmddyy()

    for field in config["api_fields"]:
        row[field] = api_values.get(field, "")

    return {column: str(row.get(column, "")) for column in config["columns"]}