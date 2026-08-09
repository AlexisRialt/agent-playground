"""Shared fixtures and factories for the test suite.

Nothing here touches the network or a real Anthropic account: the Claude client
is a hand-rolled fake that hands back pre-built `Message` objects, and every
httpx client is wired to a `MockTransport`.
"""

from __future__ import annotations

import dataclasses
from typing import Any

import httpx
import pytest
from anthropic.types import Message

from app.config import settings as real_settings
from app.jobs import Job
from app.tools.filesystem import Filesystem

# --------------------------------------------------------------------------
# Message factories — real anthropic.types objects, so the tests exercise the
# same attribute access (block.type, block.input, usage.input_tokens, …) the
# agent loop performs against live SDK responses.
# --------------------------------------------------------------------------


def text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def thinking_block(thinking: str) -> dict[str, Any]:
    return {"type": "thinking", "thinking": thinking, "signature": "sig"}


def tool_use_block(
    name: str, tool_input: dict[str, Any], block_id: str = "toolu_1"
) -> dict[str, Any]:
    return {"type": "tool_use", "id": block_id, "name": name, "input": tool_input}


def make_message(
    content: list[dict[str, Any]] | None = None,
    stop_reason: str = "end_turn",
    *,
    message_id: str = "msg_test",
    model: str = "claude-opus-4-8",
    input_tokens: int = 11,
    output_tokens: int = 22,
) -> Message:
    """Build a real `Message`. `stop_reason` must be a valid SDK literal."""
    return Message.model_validate(
        {
            "id": message_id,
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": content or [],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
        }
    )


# --------------------------------------------------------------------------
# Fake Claude client
# --------------------------------------------------------------------------


class FakeMessages:
    """Stands in for `client.messages`, replaying a queue of responses."""

    def __init__(self, responses: list[Message | Exception]) -> None:
        self.queue: list[Message | Exception] = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> Message:
        self.calls.append(kwargs)
        if not self.queue:
            raise AssertionError(
                f"FakeAnthropic ran out of queued responses on call "
                f"#{len(self.calls)}; the agent looped more than expected"
            )
        nxt = self.queue.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


class FakeAnthropic:
    """Minimal `AsyncAnthropic` stand-in: only `.messages.create` is used."""

    def __init__(self, *responses: Message | Exception) -> None:
        self.messages = FakeMessages(list(responses))

    @property
    def calls(self) -> list[dict[str, Any]]:
        return self.messages.calls


@pytest.fixture
def fake_anthropic() -> FakeAnthropic:
    """A client that replies `end_turn` with a single text block."""
    return FakeAnthropic(make_message([text_block("done")], "end_turn"))


# --------------------------------------------------------------------------
# httpx
# --------------------------------------------------------------------------


def mock_client(handler) -> httpx.AsyncClient:
    """An `AsyncClient` whose requests are served by `handler(request)`."""
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def json_client(payload: dict[str, Any], status_code: int = 200) -> httpx.AsyncClient:
    """An `AsyncClient` that answers every request with the same JSON body."""
    return mock_client(lambda _req: httpx.Response(status_code, json=payload))


@pytest.fixture
async def http_client():
    """A client that fails loudly if anything actually tries to use it."""

    def unexpected(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"unexpected HTTP request: {request.method} {request.url}")

    client = mock_client(unexpected)
    yield client
    await client.aclose()


# --------------------------------------------------------------------------
# Domain fixtures
# --------------------------------------------------------------------------


@pytest.fixture
def job() -> Job:
    return Job(task="summarise the news")


@pytest.fixture
def workspace(tmp_path):
    return tmp_path / "workspace"


@pytest.fixture
def fs(workspace) -> Filesystem:
    return Filesystem(workspace)


@pytest.fixture
def patch_settings(monkeypatch):
    """Override settings *as seen by one module*.

    `settings` is a frozen module-level singleton that each module imports by
    value, so tests rebind the importing module's name rather than mutating it.

        patch_settings("app.agent", max_iterations=2)
    """

    def _patch(module: str, **overrides: Any):
        replacement = dataclasses.replace(real_settings, **overrides)
        monkeypatch.setattr(f"{module}.settings", replacement)
        return replacement

    return _patch


@pytest.fixture(autouse=True)
def _no_search_key(patch_settings):
    """Default every test to a search-disabled config.

    Otherwise a developer with `SERPER_API_KEY` exported in their shell would
    get different results than CI. Tests that exercise the live path override
    this by calling `patch_settings("app.tools.search", serper_api_key=...)`.
    """
    patch_settings("app.tools.search", serper_api_key=None)
