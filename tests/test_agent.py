"""The manual Claude tool-use loop."""

from __future__ import annotations

import httpx
import pytest

from app import agent
from app.agent import (
    SYSTEM_PROMPT,
    TOOLS,
    _dispatch_tool,
    _no_progress,
    _Run,
    run_agent,
)
from app.logs import job_logger
from app.tools import filesystem, search
from tests.conftest import (
    FakeAnthropic,
    json_client,
    make_message,
    mock_client,
    text_block,
    thinking_block,
    tool_use_block,
)


@pytest.fixture
def run(job, fs, http_client):
    """A `_Run` with a real sandbox, a stubbed HTTP client, and no Claude client."""
    return make_run(job, fs, None, http_client)


def make_run(job, fs, anthropic, http, on_progress=_no_progress) -> _Run:
    return _Run(
        job=job,
        fs=fs,
        anthropic=anthropic,
        http=http,
        log=job_logger(job.id),
        on_progress=on_progress,
    )


# --------------------------------------------------------------------------
# Static wiring
# --------------------------------------------------------------------------


def test_system_prompt_describes_both_tools():
    assert "filesystem" in SYSTEM_PROMPT
    assert "google_search" in SYSTEM_PROMPT
    assert "PLAN" in SYSTEM_PROMPT


def test_the_agent_is_given_exactly_the_two_tools():
    assert TOOLS == [filesystem.TOOL_DEFINITION, search.TOOL_DEFINITION]
    assert [t["name"] for t in TOOLS] == ["filesystem", "google_search"]


# --------------------------------------------------------------------------
# _dispatch_tool
# --------------------------------------------------------------------------


async def test_dispatch_filesystem_write_then_read(run):
    out, is_error = await _dispatch_tool(
        run, "filesystem", {"command": "write", "path": "a.txt", "content": "hi"}
    )
    assert (out, is_error) == ("wrote 2 characters to a.txt", False)

    out, is_error = await _dispatch_tool(
        run, "filesystem", {"command": "read", "path": "a.txt"}
    )
    assert (out, is_error) == ("hi", False)


async def test_dispatch_filesystem_defaults_path_to_the_workspace_root(run):
    out, is_error = await _dispatch_tool(run, "filesystem", {"command": "list"})
    assert (out, is_error) == (". is empty", False)


async def test_dispatch_filesystem_error_is_returned_not_raised(run):
    out, is_error = await _dispatch_tool(
        run, "filesystem", {"command": "read", "path": "missing.txt"}
    )
    assert is_error is True
    assert out.startswith("FileNotFoundError: ")


async def test_dispatch_sandbox_escape_is_reported_to_the_model(run):
    out, is_error = await _dispatch_tool(
        run, "filesystem", {"command": "read", "path": "../../etc/passwd"}
    )
    assert is_error is True
    assert "escapes the workspace sandbox" in out


async def test_dispatch_missing_required_input_becomes_a_tool_error(run):
    out, is_error = await _dispatch_tool(run, "filesystem", {})
    assert (is_error, out) == (True, "KeyError: 'command'")


async def test_dispatch_google_search_without_a_key_returns_the_stub(run):
    out, is_error = await _dispatch_tool(run, "google_search", {"query": "agents"})
    assert is_error is False
    assert "not configured" in out


async def test_dispatch_google_search_hits_the_tool(job, fs, patch_settings):
    patch_settings("app.tools.search", serper_api_key="k")
    payload = {"organic_results": [{"title": "T", "link": "L", "snippet": "S"}]}
    async with json_client(payload) as client:
        run = make_run(job, fs, None, client)
        out, is_error = await _dispatch_tool(run, "google_search", {"query": "uv"})

    assert is_error is False
    assert "1. T" in out


async def test_dispatch_google_search_defaults_to_five_results(job, fs, patch_settings):
    patch_settings("app.tools.search", serper_api_key="k")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"organic_results": []})

    async with mock_client(handler) as client:
        run = make_run(job, fs, None, client)
        await _dispatch_tool(run, "google_search", {"query": "q"})

    assert seen[0].url.params["num"] == "5"


async def test_dispatch_search_transport_failure_becomes_a_tool_error(
    job, fs, patch_settings
):
    patch_settings("app.tools.search", serper_api_key="k")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    async with mock_client(handler) as client:
        run = make_run(job, fs, None, client)
        out, is_error = await _dispatch_tool(run, "google_search", {"query": "q"})

    assert is_error is True
    assert out.startswith("ConnectError: ")


async def test_dispatch_unknown_tool(run):
    assert await _dispatch_tool(run, "shell", {"cmd": "rm -rf /"}) == (
        "unknown tool 'shell'",
        True,
    )


# --------------------------------------------------------------------------
# _ask_claude
# --------------------------------------------------------------------------


async def test_ask_claude_sends_the_configured_request(job, fs, http_client):
    client = FakeAnthropic(make_message([text_block("ok")]))
    run = make_run(job, fs, client, http_client)

    await agent._ask_claude(run, [{"role": "user", "content": "hello"}])

    (kwargs,) = client.calls
    assert kwargs["model"] == agent.settings.model
    assert kwargs["max_tokens"] == agent.settings.max_tokens
    assert kwargs["system"] == SYSTEM_PROMPT
    assert kwargs["thinking"] == {"type": "adaptive"}
    assert kwargs["output_config"] == {"effort": agent.settings.effort}
    assert kwargs["tools"] == TOOLS
    assert kwargs["messages"] == [{"role": "user", "content": "hello"}]


async def test_ask_claude_honours_overridden_settings(
    job, fs, http_client, patch_settings
):
    patch_settings("app.agent", model="claude-sonnet-5", max_tokens=999, effort="low")
    client = FakeAnthropic(make_message([text_block("ok")]))
    run = make_run(job, fs, client, http_client)

    await agent._ask_claude(run, [])

    (kwargs,) = client.calls
    assert kwargs["model"] == "claude-sonnet-5"
    assert kwargs["max_tokens"] == 999
    assert kwargs["output_config"] == {"effort": "low"}


async def test_ask_claude_returns_the_response_unchanged(job, fs, http_client):
    expected = make_message([text_block("ok")])
    run = make_run(job, fs, FakeAnthropic(expected), http_client)
    assert await agent._ask_claude(run, []) is expected


async def test_ask_claude_tolerates_thinking_blocks(job, fs, http_client):
    """Thinking blocks are logged; they must not break the call path."""
    message = make_message([thinking_block("pondering"), text_block("ok")])
    run = make_run(job, fs, FakeAnthropic(message), http_client)
    assert await agent._ask_claude(run, []) is message


# --------------------------------------------------------------------------
# _record_text
# --------------------------------------------------------------------------


def test_record_text_collects_and_logs_text_blocks(run):
    text = agent._record_text(
        run, make_message([text_block("PLAN:"), text_block(" step 1")])
    )
    assert text == "PLAN: step 1"
    assert run.job.log == ["PLAN:", " step 1"]


def test_record_text_ignores_non_text_blocks(run):
    message = make_message(
        [
            thinking_block("private reasoning"),
            text_block("visible"),
            tool_use_block("filesystem", {"command": "list"}),
        ]
    )
    assert agent._record_text(run, message) == "visible"
    assert run.job.log == ["visible"]


def test_record_text_on_a_tool_only_response(run):
    message = make_message([tool_use_block("filesystem", {"command": "list"})])
    assert agent._record_text(run, message) == ""
    assert run.job.log == []


def test_record_text_strips_the_joined_result_but_not_the_log(run):
    agent._record_text(run, make_message([text_block("  padded answer  ")]))
    assert run.job.log == ["  padded answer  "]


# --------------------------------------------------------------------------
# _run_tools
# --------------------------------------------------------------------------


async def test_run_tools_returns_tool_result_blocks(run):
    message = make_message(
        [
            tool_use_block(
                "filesystem",
                {"command": "write", "path": "a.txt", "content": "x"},
                block_id="toolu_abc",
            )
        ],
        "tool_use",
    )
    results = await agent._run_tools(run, message)

    assert results == [
        {
            "type": "tool_result",
            "tool_use_id": "toolu_abc",
            "content": "wrote 1 characters to a.txt",
            "is_error": False,
        }
    ]


async def test_run_tools_records_every_call_on_the_job(run):
    message = make_message(
        [
            tool_use_block("filesystem", {"command": "list"}, "t1"),
            tool_use_block("filesystem", {"command": "read", "path": "no.txt"}, "t2"),
        ],
        "tool_use",
    )
    results = await agent._run_tools(run, message)

    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert [c.is_error for c in run.job.tool_calls] == [False, True]
    assert run.job.tool_calls[0].input == {"command": "list"}
    assert run.job.tool_calls[1].output.startswith("FileNotFoundError")


async def test_run_tools_marks_errors_on_both_the_result_and_the_record(run):
    message = make_message([tool_use_block("nope", {}, "t1")], "tool_use")
    (result,) = await agent._run_tools(run, message)

    assert result["is_error"] is True
    assert result["content"] == "unknown tool 'nope'"
    assert run.job.tool_calls[0].is_error is True


async def test_run_tools_skips_text_and_thinking_blocks(run):
    message = make_message(
        [
            thinking_block("hmm"),
            text_block("about to look"),
            tool_use_block("filesystem", {"command": "list"}, "t1"),
        ],
        "tool_use",
    )
    assert len(await agent._run_tools(run, message)) == 1


async def test_run_tools_on_a_response_with_no_tool_calls(run):
    assert await agent._run_tools(run, make_message([text_block("hi")])) == []
    assert run.job.tool_calls == []


# --------------------------------------------------------------------------
# run_agent — the loop
# --------------------------------------------------------------------------


async def test_end_turn_on_the_first_iteration_returns_the_answer(job, fs, http_client):
    client = FakeAnthropic(make_message([text_block("the answer")], "end_turn"))

    assert await run_agent(job, fs, client, http_client) == "the answer"
    assert len(client.calls) == 1
    assert job.log == ["the answer"]
    assert job.tool_calls == []


async def test_the_first_message_is_the_job_task(job, fs, http_client):
    client = FakeAnthropic(make_message([text_block("done")], "end_turn"))
    await run_agent(job, fs, client, http_client)
    assert client.calls[0]["messages"] == [{"role": "user", "content": job.task}]


async def test_tool_use_round_trip(job, fs, http_client):
    tool_response = make_message(
        [
            text_block("PLAN: write a file"),
            tool_use_block(
                "filesystem",
                {"command": "write", "path": "out.txt", "content": "hello"},
                "toolu_1",
            ),
        ],
        "tool_use",
    )
    client = FakeAnthropic(
        tool_response, make_message([text_block("saved to out.txt")], "end_turn")
    )

    result = await run_agent(job, fs, client, http_client)

    assert result == "saved to out.txt"
    assert (fs.root / "out.txt").read_text() == "hello"
    assert job.log == ["PLAN: write a file", "saved to out.txt"]
    assert len(job.tool_calls) == 1

    # Second turn replays the assistant content, then answers the tool call.
    second_turn = client.calls[1]["messages"]
    assert len(second_turn) == 3
    assert second_turn[0] == {"role": "user", "content": job.task}
    assert second_turn[1] == {"role": "assistant", "content": tool_response.content}
    assert second_turn[2]["role"] == "user"
    assert second_turn[2]["content"][0]["tool_use_id"] == "toolu_1"


async def test_multiple_tool_iterations(job, fs, http_client):
    client = FakeAnthropic(
        make_message(
            [tool_use_block("filesystem", {"command": "list"}, "t1")], "tool_use"
        ),
        make_message(
            [
                tool_use_block(
                    "filesystem",
                    {"command": "write", "path": "n.md", "content": "notes"},
                    "t2",
                )
            ],
            "tool_use",
        ),
        make_message([text_block("finished")], "end_turn"),
    )

    assert await run_agent(job, fs, client, http_client) == "finished"
    assert len(client.calls) == 3
    assert [c.input["command"] for c in job.tool_calls] == ["list", "write"]
    # user task + (assistant, tool results) x 2
    assert len(client.calls[2]["messages"]) == 5


async def test_pause_turn_resumes_without_adding_a_user_message(job, fs, http_client):
    paused = make_message([text_block("partial")], "pause_turn")
    client = FakeAnthropic(paused, make_message([text_block("complete")], "end_turn"))

    assert await run_agent(job, fs, client, http_client) == "complete"

    resumed = client.calls[1]["messages"]
    assert resumed == [
        {"role": "user", "content": job.task},
        {"role": "assistant", "content": paused.content},
    ]


async def test_refusal_raises(job, fs, http_client):
    client = FakeAnthropic(make_message([text_block("I can't")], "refusal"))
    with pytest.raises(RuntimeError, match="refusal"):
        await run_agent(job, fs, client, http_client)


async def test_unexpected_stop_reason_raises(job, fs, http_client):
    client = FakeAnthropic(make_message([text_block("cut off")], "max_tokens"))
    with pytest.raises(RuntimeError, match="unexpected stop_reason: max_tokens"):
        await run_agent(job, fs, client, http_client)


async def test_text_seen_before_a_failure_is_still_recorded(job, fs, http_client):
    client = FakeAnthropic(make_message([text_block("partial work")], "max_tokens"))
    with pytest.raises(RuntimeError):
        await run_agent(job, fs, client, http_client)
    assert job.log == ["partial work"]


async def test_iteration_budget_is_enforced(job, fs, http_client, patch_settings):
    patch_settings("app.agent", max_iterations=3)
    looping = [
        make_message(
            [tool_use_block("filesystem", {"command": "list"}, f"t{i}")], "tool_use"
        )
        for i in range(3)
    ]
    client = FakeAnthropic(*looping)

    with pytest.raises(RuntimeError, match="did not finish within 3 iterations"):
        await run_agent(job, fs, client, http_client)

    assert len(client.calls) == 3
    assert len(job.tool_calls) == 3


async def test_the_loop_stops_exactly_at_the_budget(
    job, fs, http_client, patch_settings
):
    """A run that finishes on the final allowed iteration must succeed."""
    patch_settings("app.agent", max_iterations=2)
    client = FakeAnthropic(
        make_message(
            [tool_use_block("filesystem", {"command": "list"}, "t1")], "tool_use"
        ),
        make_message([text_block("just in time")], "end_turn"),
    )
    assert await run_agent(job, fs, client, http_client) == "just in time"


async def test_api_errors_propagate_out_of_the_loop(job, fs, http_client):
    client = FakeAnthropic(RuntimeError("anthropic exploded"))
    with pytest.raises(RuntimeError, match="anthropic exploded"):
        await run_agent(job, fs, client, http_client)


async def test_search_results_flow_back_into_the_job_record(job, fs, patch_settings):
    patch_settings("app.tools.search", serper_api_key="k")
    payload = {
        "organic_results": [
            {"title": "uv docs", "link": "https://docs.astral.sh/uv/", "snippet": "s"}
        ]
    }
    client = FakeAnthropic(
        make_message(
            [tool_use_block("google_search", {"query": "uv", "num_results": 1}, "t1")],
            "tool_use",
        ),
        make_message([text_block("uv is a package manager")], "end_turn"),
    )

    async with json_client(payload) as http:
        result = await run_agent(job, fs, client, http)

    assert result == "uv is a package manager"
    assert job.tool_calls[0].tool == "google_search"
    assert "uv docs" in job.tool_calls[0].output
    assert job.tool_calls[0].is_error is False


# --------------------------------------------------------------------------
# on_progress — how the runner persists partial progress
# --------------------------------------------------------------------------


@pytest.fixture
def progress(job):
    """Snapshots the job each time the loop reports progress."""
    seen = []

    async def _on_progress():
        seen.append((list(job.log), len(job.tool_calls)))

    _on_progress.seen = seen
    return _on_progress


async def test_on_progress_is_optional(job, fs, http_client):
    client = FakeAnthropic(make_message([text_block("done")], "end_turn"))
    assert await run_agent(job, fs, client, http_client) == "done"


async def test_on_progress_fires_after_each_tool_use_iteration(
    job, fs, http_client, progress
):
    client = FakeAnthropic(
        make_message(
            [
                text_block("PLAN: list, then answer"),
                tool_use_block("filesystem", {"command": "list", "path": "."}, "t1"),
            ],
            "tool_use",
        ),
        make_message([text_block("nothing there")], "end_turn"),
    )

    await run_agent(job, fs, client, http_client, progress)

    # One checkpoint, taken once the tool call had been recorded.
    assert progress.seen == [(["PLAN: list, then answer"], 1)]


async def test_on_progress_fires_on_a_paused_turn(job, fs, http_client, progress):
    client = FakeAnthropic(
        make_message([text_block("still working")], "pause_turn"),
        make_message([text_block("done")], "end_turn"),
    )

    await run_agent(job, fs, client, http_client, progress)

    assert progress.seen == [(["still working"], 0)]


async def test_on_progress_does_not_fire_on_the_final_turn(
    job, fs, http_client, progress
):
    """The runner saves the finished job itself; no need to double-write."""
    client = FakeAnthropic(make_message([text_block("done")], "end_turn"))

    await run_agent(job, fs, client, http_client, progress)

    assert progress.seen == []


async def test_a_failing_checkpoint_stops_the_run(job, fs, http_client):
    async def broken():
        raise RuntimeError("postgres is down")

    client = FakeAnthropic(
        make_message(
            [tool_use_block("filesystem", {"command": "list", "path": "."}, "t1")],
            "tool_use",
        ),
        make_message([text_block("done")], "end_turn"),
    )

    with pytest.raises(RuntimeError, match="postgres is down"):
        await run_agent(job, fs, client, http_client, broken)
