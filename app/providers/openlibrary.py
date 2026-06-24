from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

OPENLIBRARY_SEARCH = "https://openlibrary.org/search.json"
OPENLIBRARY_WORKS = "https://openlibrary.org/works"


def _format_publish_date(value: str | None) -> str:
    if not value:
        return ""
    value = value.strip()
    if re.fullmatch(r"\d{4}", value):
        return f"01/01/{value[-2:]}"
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").strftime("%m/%d/%y")
    except ValueError:
        pass
    try:
        return datetime.strptime(value[:7], "%Y-%m").strftime("%m/%d/%y")
    except ValueError:
        pass
    if len(value) >= 4 and value[:4].isdigit():
        return f"01/01/{value[2:4]}"
    return ""


def _work_id(raw: str) -> str:
    return raw.replace("/works/", "").strip("/")


async def search_books(query: str) -> list[dict[str, Any]]:
    params = {"q": query, "limit": 8, "fields": "key,title,author_name,first_publish_year"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(OPENLIBRARY_SEARCH, params=params)
        response.raise_for_status()
        docs = response.json().get("docs", [])

    results = []
    for doc in docs:
        title = (doc.get("title") or "").strip()
        if not title:
            continue

        authors = doc.get("author_name") or []
        author = ", ".join(authors[:3])
        year = str(doc.get("first_publish_year", "")) if doc.get("first_publish_year") else ""
        work_id = _work_id(doc.get("key", ""))
        if not work_id:
            continue

        label = title
        if year:
            label = f"{title} ({year})"
        if author:
            label = f"{label} — {author}"

        results.append(
            {
                "id": work_id,
                "title": title,
                "year": year,
                "author": author,
                "subtitle": label,
            }
        )
    return results


async def lookup_book(work_id: str) -> dict[str, str]:
    work_id = _work_id(work_id)
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{OPENLIBRARY_WORKS}/{work_id}.json")
        if response.status_code == 404:
            return {"Date Published": "", "Author": ""}
        response.raise_for_status()
        work = response.json()

        author_names: list[str] = []
        for author_ref in work.get("authors", [])[:3]:
            author_key = author_ref.get("author", {}).get("key")
            if not author_key:
                continue
            author_response = await client.get(f"https://openlibrary.org{author_key}.json")
            if author_response.is_success:
                name = author_response.json().get("name", "")
                if name:
                    author_names.append(name)

        publish_raw = work.get("first_publish_date") or ""
        if not publish_raw and work.get("created"):
            publish_raw = str(work["created"].get("value", ""))[:10]

    return {
        "Date Published": _format_publish_date(publish_raw),
        "Author": ", ".join(author_names),
    }
