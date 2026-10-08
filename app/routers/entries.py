from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_enabled_types, get_media_type
from app.csv_store import (
    storage_lock,
    build_row,
    build_watchlist_row,
    delete_entry,
    prepend_entry,
    read_entries,
    title_exists,
    update_entry_rating,
)
from app.git_sync import get_sync_status, sync_csv_async
from app.providers import get_provider

router = APIRouter(prefix="/api", tags=["entries"])


class EntryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    rating: int = Field(ge=1, le=10)
    external_id: str | None = Field(default=None)
    date_rated: str | None = None
    api_values: dict[str, str] | None = None
    strategy: Literal["update", "rewatch"] | None = None


class WatchlistCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    external_id: str | None = Field(default=None)
    api_values: dict[str, str] | None = None


def _require_type(media_type: str) -> dict[str, Any]:
    try:
        return get_media_type(media_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Metadata provider unavailable; try again later") from exc


@router.get("/types")
def list_types() -> dict[str, Any]:
    enabled = get_enabled_types()
    payload = {}
    for key, config in enabled.items():
        payload[key] = {
            "label": config["label"],
            "columns": config["columns"],
            "title_column": config["title_column"],
            "user_fields": config["user_fields"],
            "auto_fields": config["auto_fields"],
            "api_fields": config["api_fields"],
        }
    return {"types": payload, "git_sync": get_sync_status()}


@router.get("/{media_type}/search")
async def search(media_type: str, q: str = Query(min_length=1)) -> dict[str, Any]:
    config = _require_type(media_type)
    provider = get_provider(config["provider"])
    try:
        results = await provider.search(q)
        return {"results": results}
    except Exception as exc:
        raise HTTPException(status_code=500, detail="Metadata provider unavailable; try again later") from exc


@router.get("/{media_type}/entries")
def list_entries(media_type: str, limit: int = Query(default=20, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> dict[str, Any]:
    _require_type(media_type)
    with storage_lock:
        all_rows = read_entries(media_type)
        rows = all_rows[offset:offset + limit]
    return {"entries": rows, "total": len(all_rows)}


@router.post("/{media_type}/entries")
async def create_entry(media_type: str, payload: EntryCreate) -> dict[str, Any]:
    config = _require_type(media_type)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required")

    api_values = payload.api_values
    # If api_values aren't provided, attempt provider lookup when an external_id is supplied.
    if api_values is None and payload.external_id:
        provider = get_provider(config["provider"])
        try:
            api_values = await provider.lookup(payload.external_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Metadata provider unavailable; try again later") from exc
    # If neither api_values nor external_id were supplied, treat this as a manual entry
    if api_values is None:
        api_values = {}

    row = build_row(
        media_type,
        title=title,
        rating=str(payload.rating),
        date_rated=payload.date_rated,
        api_values=api_values,
    )
    with storage_lock:
        duplicate = title_exists(media_type, title)
        if payload.strategy == "update":
            updated = update_entry_rating(media_type, title, str(payload.rating), payload.date_rated)
            if updated is None:
                raise HTTPException(status_code=404, detail="Entry to update not found")
            sync_csv_async(media_type, f"{media_type}: update rating")
            return {"status": "updated", "entry": updated, "git_sync": get_sync_status()}
        saved = prepend_entry(media_type, row)
        sync_csv_async(media_type, f"{media_type}: {'rewatch' if duplicate else 'rate'} {title}")

    return {
        "status": "created",
        "entry": saved,
        "git_sync": get_sync_status(),
    }


@router.delete("/{media_type}/entries")
def delete_diary_entry(media_type: str, title: str, date_rated: str) -> dict[str, Any]:
    _require_type(media_type)
    success = delete_entry(media_type, title, date_rated)
    if not success:
        raise HTTPException(status_code=404, detail="Entry not found.")

    commit_message = f"{media_type}: delete entry for {title} logged on {date_rated}"
    sync_csv_async(media_type, commit_message)
    return {"status": "deleted", "git_sync": get_sync_status()}


# --- WATCHLIST ENDPOINTS ---

@router.get("/{media_type}/watchlist")
def list_watchlist(media_type: str) -> dict[str, Any]:
    _require_type(media_type)
    rows = read_entries(media_type, use_watchlist=True)
    return {"entries": rows}


@router.post("/{media_type}/watchlist")
async def create_watchlist_entry(media_type: str, payload: WatchlistCreate) -> dict[str, Any]:
    config = _require_type(media_type)
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required")

    api_values = payload.api_values
    # Allow watchlist items to be created manually if no external_id is provided
    if api_values is None and payload.external_id:
        provider = get_provider(config["provider"])
        try:
            api_values = await provider.lookup(payload.external_id)
        except Exception as exc:
            raise HTTPException(status_code=500, detail="Metadata provider unavailable; try again later") from exc
    if api_values is None:
        api_values = {}

    row = build_watchlist_row(media_type, title=title, api_values=api_values)
    with storage_lock:
        if title_exists(media_type, title, use_watchlist=True):
            raise HTTPException(status_code=400, detail="Item is already in your watchlist.")
        saved = prepend_entry(media_type, row, use_watchlist=True)

    commit_message = f"{media_type}: add {title} to watchlist"
    sync_csv_async(media_type, commit_message)

    return {
        "status": "created",
        "entry": saved,
        "git_sync": get_sync_status(),
    }


@router.delete("/{media_type}/watchlist")
def delete_watchlist_entry(media_type: str, title: str) -> dict[str, Any]:
    _require_type(media_type)
    success = delete_entry(media_type, title, use_watchlist=True)
    if not success:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")

    commit_message = f"{media_type}: remove {title} from watchlist"
    sync_csv_async(media_type, commit_message)
    return {"status": "deleted", "git_sync": get_sync_status()}