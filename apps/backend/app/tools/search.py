"""A Google search tool backed by SerpAPI.

If no SERPER_API_KEY is configured, the tool returns a clear, explicit message
rather than failing — so the server runs end-to-end with zero extra setup, and
you can drop in a real key later without touching any other code.
"""

from __future__ import annotations

import httpx
from loguru import logger as log

from app.config import settings

TOOL_DEFINITION = {
    "name": "google_search",
    "description": (
        "Search Google for up-to-date information on the public web. "
        "Use this whenever the task needs current facts, recent events, or anything "
        "beyond your training data. Returns a ranked list of results with titles, "
        "URLs, and snippets."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query.",
            },
            "num_results": {
                "type": "integer",
                "description": "How many results to return (1-10). Defaults to 5.",
            },
        },
        "required": ["query"],
    },
}

_SERPAPI_URL = "https://serpapi.com/search"


async def google_search(
    client: httpx.AsyncClient,
    query: str,
    num_results: int = 5,
) -> str:
    """Run a Google search via SerpAPI. Returns formatted results as text."""
    num_results = max(1, min(int(num_results), 10))
    log.info("search {!r} (num_results={})", query, num_results)

    if not settings.serper_api_key:
        log.warning("search skipped: SERPER_API_KEY is not set")
        return (
            "google_search is not configured: set the SERPER_API_KEY environment "
            "variable (get a key at https://serpapi.com) to enable live Google "
            f"results. Requested query was: {query!r}."
        )

    resp = await client.get(
        _SERPAPI_URL,
        params={
            "engine": "google",
            "q": query,
            "num": num_results,
            "api_key": settings.serper_api_key,
        },
        timeout=20.0,
    )
    resp.raise_for_status()
    data = resp.json()

    # SerpAPI reports quota/param problems as a 200 with an "error" field.
    if error := data.get("error"):
        log.warning("search error for {!r}: {}", query, error)
        return f"google_search failed for {query!r}: {error}"

    organic = data.get("organic_results", [])[:num_results]
    log.info("search {!r} -> {} result(s)", query, len(organic))
    if not organic:
        return f"No results found for {query!r}."

    lines = [f"Google results for {query!r}:"]
    for i, item in enumerate(organic, start=1):
        title = item.get("title", "(no title)")
        link = item.get("link", "")
        snippet = item.get("snippet", "")
        lines.append(f"{i}. {title}\n   {link}\n   {snippet}")
    return "\n".join(lines)
