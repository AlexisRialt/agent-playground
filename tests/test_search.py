"""The google_search tool (SerpAPI-backed).

Every test runs against an `httpx.MockTransport`; nothing here reaches the
network. The autouse `_no_search_key` fixture in conftest means the default
state is "unconfigured", and tests opt into the live path explicitly.
"""

from __future__ import annotations

import httpx
import pytest

from app.tools.search import TOOL_DEFINITION, google_search
from tests.conftest import json_client, mock_client


def result_payload(*results: dict) -> dict:
    return {"organic_results": list(results)}


ONE_RESULT = result_payload(
    {
        "title": "Python 3.14 release notes",
        "link": "https://docs.python.org/3.14/whatsnew/",
        "snippet": "What's new in Python 3.14.",
    }
)


@pytest.fixture
def with_key(patch_settings):
    patch_settings("app.tools.search", serper_api_key="test-serp-key")


# --------------------------------------------------------------------------
# Tool definition
# --------------------------------------------------------------------------


def test_tool_definition_shape():
    assert TOOL_DEFINITION["name"] == "google_search"
    assert TOOL_DEFINITION["description"]
    schema = TOOL_DEFINITION["input_schema"]
    assert schema["required"] == ["query"]
    assert set(schema["properties"]) == {"query", "num_results"}
    assert schema["properties"]["num_results"]["type"] == "integer"


# --------------------------------------------------------------------------
# Unconfigured (no API key)
# --------------------------------------------------------------------------


async def test_without_a_key_it_returns_a_stub_and_makes_no_request(http_client):
    # `http_client` raises on any outbound request, so reaching the network fails.
    out = await google_search(http_client, query="rust vs zig")

    assert "not configured" in out
    assert "SERPER_API_KEY" in out
    assert "'rust vs zig'" in out


async def test_stub_mentions_where_to_get_a_key(http_client):
    assert "serpapi.com" in await google_search(http_client, query="q")


# --------------------------------------------------------------------------
# Request construction
# --------------------------------------------------------------------------


async def test_request_targets_serpapi_with_the_expected_params(with_key):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ONE_RESULT)

    async with mock_client(handler) as client:
        await google_search(client, query="what is uv", num_results=3)

    request = seen[0]
    assert request.method == "GET"
    assert str(request.url).startswith("https://serpapi.com/search")
    params = request.url.params
    assert params["engine"] == "google"
    assert params["q"] == "what is uv"
    assert params["num"] == "3"
    assert params["api_key"] == "test-serp-key"


async def test_the_api_key_is_never_echoed_into_the_model_visible_output(with_key):
    async with json_client(ONE_RESULT) as client:
        out = await google_search(client, query="q")
    assert "test-serp-key" not in out


# --------------------------------------------------------------------------
# num_results handling
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("requested", "sent"),
    [(1, "1"), (5, "5"), (10, "10"), (0, "1"), (-7, "1"), (11, "10"), (999, "10")],
)
async def test_num_results_is_clamped_to_1_10(with_key, requested, sent):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ONE_RESULT)

    async with mock_client(handler) as client:
        await google_search(client, query="q", num_results=requested)

    assert seen[0].url.params["num"] == sent


async def test_num_results_accepts_a_numeric_string(with_key):
    """The model supplies tool input as JSON; be forgiving about the type."""
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=ONE_RESULT)

    async with mock_client(handler) as client:
        await google_search(client, query="q", num_results="4")

    assert seen[0].url.params["num"] == "4"


async def test_extra_results_from_the_api_are_truncated_locally(with_key):
    payload = result_payload(
        *(
            {"title": f"r{i}", "link": f"https://x/{i}", "snippet": "s"}
            for i in range(8)
        )
    )
    async with json_client(payload) as client:
        out = await google_search(client, query="q", num_results=2)

    assert "1. r0" in out
    assert "2. r1" in out
    assert "3. r2" not in out


# --------------------------------------------------------------------------
# Result formatting
# --------------------------------------------------------------------------


async def test_results_are_formatted_as_a_numbered_list(with_key):
    payload = result_payload(
        {"title": "First", "link": "https://one.example", "snippet": "snippet one"},
        {"title": "Second", "link": "https://two.example", "snippet": "snippet two"},
    )
    async with json_client(payload) as client:
        out = await google_search(client, query="agents", num_results=5)

    assert out.splitlines() == [
        "Google results for 'agents':",
        "1. First",
        "   https://one.example",
        "   snippet one",
        "2. Second",
        "   https://two.example",
        "   snippet two",
    ]


async def test_missing_result_fields_fall_back_to_placeholders(with_key):
    async with json_client(result_payload({})) as client:
        out = await google_search(client, query="q")

    assert "1. (no title)" in out


async def test_empty_organic_results(with_key):
    async with json_client(result_payload()) as client:
        assert await google_search(client, query="obscure") == (
            "No results found for 'obscure'."
        )


async def test_missing_organic_results_key(with_key):
    async with json_client({"search_metadata": {"status": "Success"}}) as client:
        assert "No results found" in await google_search(client, query="obscure")


# --------------------------------------------------------------------------
# Failure modes
# --------------------------------------------------------------------------


async def test_serpapi_error_field_is_surfaced_as_text_not_an_exception(with_key):
    """SerpAPI reports quota/param problems as HTTP 200 with an `error` key."""
    async with json_client(
        {"error": "Your account has run out of searches."}
    ) as client:
        out = await google_search(client, query="q")

    assert out == "google_search failed for 'q': Your account has run out of searches."


@pytest.mark.parametrize("status", [400, 401, 429, 500, 503])
async def test_http_errors_propagate(with_key, status):
    async with json_client({"whatever": True}, status_code=status) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await google_search(client, query="q")


async def test_transport_errors_propagate(with_key):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host", request=request)

    async with mock_client(handler) as client:
        with pytest.raises(httpx.ConnectError):
            await google_search(client, query="q")


async def test_non_json_body_propagates(with_key):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    async with mock_client(handler) as client:
        with pytest.raises(ValueError):
            await google_search(client, query="q")
