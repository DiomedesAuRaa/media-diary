from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_enabled_types, get_media_type
from app.csv_store import (
    build_row,
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
    title: str = Field(min_length=1)
    rating: int = Field(ge=1, le=10)
    external_id: str = Field(min_length=1)
    date_rated: str | None = None
    api_values: dict[str, str] | None = None
    strategy: Literal["update", "rewatch"] | None = None


def _require_type(media_type: str) -> dict[str, Any]:
    try:
        return get_media_type(media_type)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/{media_type}/entries")
def list_entries(media_type: str, limit: int = Query(default=20, ge=1, le=200)) -> dict[str, Any]:
    _require_type(media_type)
    rows = read_entries(media_type, limit=limit)
    return {"entries": rows}


@router.post("/{media_type}/entries")
async def create_entry(media_type: str, payload: EntryCreate) -> dict[str, Any]:
    config = _require_type(media_type)
    title = payload.title.strip()

    duplicate = title_exists(media_type, title)

    if duplicate and payload.strategy == "update":
        updated = update_entry_rating(media_type, title, str(payload.rating), payload.date_rated)
        if updated:
            commit_message = f"{media_type}: update rating for {title} to {payload.rating}/10"
            sync_csv_async(media_type, commit_message)
            return {
                "status": "updated",
                "entry": updated,
                "git_sync": get_sync_status(),
            }

    api_values = payload.api_values
    if api_values is None:
        provider = get_provider(config["provider"])
        try:
            api_values = await provider.lookup(payload.external_id)
        except (NotImplementedError, RuntimeError) as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    row = build_row(
        media_type,
        title=title,
        rating=str(payload.rating),
        date_rated=payload.date_rated,
        api_values=api_values,
    )
    saved = prepend_entry(media_type, row)

    action = "rewatch" if duplicate else "rate"
    commit_message = f"{media_type}: {action} {title} {payload.rating}/10"
    sync_csv_async(media_type, commit_message)

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