from __future__ import annotations

import asyncio
import os
from datetime import datetime
from typing import Any

import httpx

TMDB_BASE = "https://api.themoviedb.org/3"


def _api_key() -> str:
    key = os.environ.get("TMDB_API_KEY", "").strip()
    if not key:
        raise RuntimeError("TMDB_API_KEY is not set")
    return key


def _format_tmdb_date(value: str | None) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return ""
    return parsed.strftime("%m/%d/%y")


def _directors_from_credits(credits: dict[str, Any]) -> str:
    directors = [
        person.get("name", "")
        for person in credits.get("crew", [])
        if person.get("job") == "Director" and person.get("name")
    ]
    return ", ".join(directors)


async def _fetch_director(client: httpx.AsyncClient, movie_id: str) -> str:
    params = {"api_key": _api_key()}
    response = await client.get(f"{TMDB_BASE}/movie/{movie_id}/credits", params=params)
    response.raise_for_status()
    return _directors_from_credits(response.json())


async def search_movies(query: str) -> list[dict[str, Any]]:
    params = {
        "api_key": _api_key(),
        "query": query,
        "include_adult": "false",
        "language": "en-US",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{TMDB_BASE}/search/movie", params=params)
        response.raise_for_status()
        payload = response.json()

        top = payload.get("results", [])[:8]
        director_tasks = [
            _fetch_director(client, str(item.get("id")))
            for item in top
            if item.get("id")
        ]
        directors = await asyncio.gather(*director_tasks, return_exceptions=True)

    results = []
    for item, director_result in zip(top, directors):
        year = (item.get("release_date") or "")[:4]
        director = director_result if isinstance(director_result, str) else ""
        label = item.get("title") or ""
        if year:
            label = f"{label} ({year})"
        if director:
            label = f"{label} — {director}"

        results.append(
            {
                "id": str(item.get("id")),
                "title": item.get("title") or "",
                "year": year,
                "director": director,
                "subtitle": label,
            }
        )
    return results


async def lookup_movie(movie_id: str) -> dict[str, str]:
    params = {"api_key": _api_key()}
    async with httpx.AsyncClient(timeout=15.0) as client:
        details_response = await client.get(
            f"{TMDB_BASE}/movie/{movie_id}",
            params={**params, "language": "en-US"},
        )
        details_response.raise_for_status()
        details = details_response.json()

        credits_response = await client.get(
            f"{TMDB_BASE}/movie/{movie_id}/credits",
            params=params,
        )
        credits_response.raise_for_status()
        credits = credits_response.json()

    return {
        "Date Released": _format_tmdb_date(details.get("release_date")),
        "Director": _directors_from_credits(credits),
    }


def _creators_from_details(details: dict[str, Any]) -> str:
    creators = [
        person.get("name", "")
        for person in details.get("created_by", [])
        if person.get("name")
    ]
    return ", ".join(creators)


async def _fetch_tv_creator(client: httpx.AsyncClient, tv_id: str) -> str:
    params = {"api_key": _api_key(), "language": "en-US"}
    response = await client.get(f"{TMDB_BASE}/tv/{tv_id}", params=params)
    response.raise_for_status()
    return _creators_from_details(response.json())


async def search_tv(query: str) -> list[dict[str, Any]]:
    params = {
        "api_key": _api_key(),
        "query": query,
        "include_adult": "false",
        "language": "en-US",
    }
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{TMDB_BASE}/search/tv", params=params)
        response.raise_for_status()
        payload = response.json()

        top = payload.get("results", [])[:8]
        creator_tasks = [
            _fetch_tv_creator(client, str(item.get("id")))
            for item in top
            if item.get("id")
        ]
        creators = await asyncio.gather(*creator_tasks, return_exceptions=True)

    results = []
    for item, creator_result in zip(top, creators):
        year = (item.get("first_air_date") or "")[:4]
        creator = creator_result if isinstance(creator_result, str) else ""
        title = item.get("name") or ""
        label = title
        if year:
            label = f"{title} ({year})"
        if creator:
            label = f"{label} — {creator}"

        results.append(
            {
                "id": str(item.get("id")),
                "title": title,
                "year": year,
                "creator": creator,
                "subtitle": label,
            }
        )
    return results


async def lookup_tv(tv_id: str) -> dict[str, str]:
    params = {"api_key": _api_key(), "language": "en-US"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(f"{TMDB_BASE}/tv/{tv_id}", params=params)
        response.raise_for_status()
        details = response.json()

    return {
        "Date Premiered": _format_tmdb_date(details.get("first_air_date")),
        "Creator": _creators_from_details(details),
    }
