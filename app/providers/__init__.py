from __future__ import annotations

from typing import Any, Protocol

from app.providers import openlibrary, tmdb


class SearchProvider(Protocol):
    async def search(self, query: str) -> list[dict[str, Any]]: ...

    async def lookup(self, external_id: str) -> dict[str, str]: ...


class TmdbMovieProvider:
    async def search(self, query: str) -> list[dict[str, Any]]:
        return await tmdb.search_movies(query)

    async def lookup(self, external_id: str) -> dict[str, str]:
        return await tmdb.lookup_movie(external_id)


class TmdbTvProvider:
    async def search(self, query: str) -> list[dict[str, Any]]:
        return await tmdb.search_tv(query)

    async def lookup(self, external_id: str) -> dict[str, str]:
        return await tmdb.lookup_tv(external_id)


class OpenLibraryProvider:
    async def search(self, query: str) -> list[dict[str, Any]]:
        return await openlibrary.search_books(query)

    async def lookup(self, external_id: str) -> dict[str, str]:
        return await openlibrary.lookup_book(external_id)


PROVIDERS: dict[str, SearchProvider] = {
    "tmdb_movie": TmdbMovieProvider(),
    "tmdb_tv": TmdbTvProvider(),
    "openlibrary": OpenLibraryProvider(),
}


def get_provider(name: str) -> SearchProvider:
    if name not in PROVIDERS:
        raise KeyError(f"Unknown provider: {name}")
    return PROVIDERS[name]
