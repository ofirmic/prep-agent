"""Tavily search wrapper. One function, structured output."""
from __future__ import annotations

import asyncio
from typing import Any

from tavily import TavilyClient

from prep_agent.models import SearchResult


class SearchClient:
    def __init__(self, api_key: str) -> None:
        self._client = TavilyClient(api_key=api_key)

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """Run a Tavily search. Wrapped in to_thread because the SDK is sync."""
        raw = await asyncio.to_thread(
            self._client.search,
            query=query,
            max_results=max_results,
            search_depth="advanced",
        )
        return [_to_result(r) for r in raw.get("results", [])]

    async def search_many(self, queries: list[str], max_results: int = 5) -> list[SearchResult]:
        """Fan out queries in parallel, flatten and dedupe by URL."""
        batches = await asyncio.gather(*(self.search(q, max_results) for q in queries))
        seen: set[str] = set()
        merged: list[SearchResult] = []
        for batch in batches:
            for r in batch:
                if r.url in seen:
                    continue
                seen.add(r.url)
                merged.append(r)
        return merged


def _to_result(raw: dict[str, Any]) -> SearchResult:
    return SearchResult(
        url=raw["url"],
        title=raw.get("title", ""),
        content=raw.get("content", ""),
        score=raw.get("score"),
    )
