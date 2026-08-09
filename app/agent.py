"""The Claude agent loop.

Given a task string, the agent first makes a plan, then decides what to do using
two tools — a sandboxed filesystem and google search — iterating until it has an
answer. This is a manual tool-use loop (rather than the SDK tool runner) so every
plan step and tool call can be recorded into the Job record for status reporting.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from anthropic import AsyncAnthropic
from anthropic.types import Message

from app.config import settings
from app.jobs import Job
from app.logs import job_logger, short
from app.tools import filesystem, search

if TYPE_CHECKING:  # loguru only exports `Logger` to type checkers, not at runtime
    from loguru import Logger

SYSTEM_PROMPT = """\
You are an autonomous agent that completes a user's task end to end.

You have exactly two tools:
- filesystem: read/write/list files in your private, sandboxed workspace. Use it to \
save intermediate work, notes, and any output artifacts the task calls for.
- google_search: search Google for current information on the public web.

How to work:
1. Start by writing a short, explicit PLAN as plain text: the steps you intend to \
take and which tools each step will use. Keep it to a few bullet points.
2. Then execute the plan, calling tools as needed. Search when you need facts you \
don't already have; use the filesystem to persist anything worth keeping.
3. Adapt the plan as you learn more — you don't have to follow it rigidly.
4. When the task is complete, produce a final answer as plain text. If you created \
files, mention their workspace paths.

You are operating autonomously — the user is not watching in real time and cannot \
answer questions mid-task. For reversible actions that follow from the request, \
proceed without asking. Ground any progress claims in actual tool results.
"""

# The two tools, exactly as specified.
TOOLS = [filesystem.TOOL_DEFINITION, search.TOOL_DEFINITION]

# Called after each iteration so the caller can persist partial progress.
OnProgress = Callable[[], Awaitable[None]]


async def _no_progress() -> None:
    """Default `on_progress`: keep whatever the job accumulated in memory only."""


@dataclass(frozen=True, slots=True)
class _Run:
    """One agent run: the job record it reports into, plus its sandbox and clients."""

    job: Job
    fs: filesystem.Filesystem
    anthropic: AsyncAnthropic
    http: httpx.AsyncClient
    log: Logger
    on_progress: OnProgress


async def _dispatch_tool(run: _Run, name: str, tool_input: dict) -> tuple[str, bool]:
    """Execute a tool call. Returns (result_text, is_error)."""
    try:
        if name == "filesystem":
            out = run.fs.run(
                command=tool_input["command"],
                path=tool_input.get("path", "."),
                content=tool_input.get("content"),
            )
            return out, False
        if name == "google_search":
            out = await search.google_search(
                run.http,
                query=tool_input["query"],
                num_results=tool_input.get("num_results", 5),
            )
            return out, False
        run.log.warning("tool: unknown tool {!r} requested", name)
        return f"unknown tool '{name}'", True
    except Exception as exc:  # noqa: BLE001 - surface any tool error to the model so it can recover
        return f"{type(exc).__name__}: {exc}", True


async def _ask_claude(run: _Run, messages: list[dict]) -> Message:
    run.log.info(
        "-> claude (model={}, effort={}, messages={})",
        settings.model,
        settings.effort,
        len(messages),
    )
    started = time.perf_counter()
    response = await run.anthropic.messages.create(
        model=settings.model,
        max_tokens=settings.max_tokens,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={"effort": settings.effort},
        tools=TOOLS,
        messages=messages,
    )
    run.log.info(
        "<- claude in {:.1f}s (stop_reason={}, in={} tok, out={} tok)",
        time.perf_counter() - started,
        response.stop_reason,
        response.usage.input_tokens,
        response.usage.output_tokens,
    )
    for block in response.content:
        if block.type == "thinking":
            run.log.debug("thinking: {}", short(block.thinking, 500))
    return response


def _record_text(run: _Run, response: Message) -> str:
    """Log any assistant text (the plan, narration, or final answer) and return it."""
    parts = [block.text for block in response.content if block.type == "text"]
    for part in parts:
        run.job.add_log(part)
        run.log.info("text: {}", short(part, 600))
    return "".join(parts).strip()


async def _run_tools(run: _Run, response: Message) -> list[dict]:
    """Execute every tool_use block in the response and record what happened."""
    results = []
    calls = [block for block in response.content if block.type == "tool_use"]
    run.log.info("{} tool call(s) requested", len(calls))
    for block in response.content:
        if block.type != "tool_use":
            continue
        run.log.info("tool {} -> {}", block.name, short(dict(block.input), 300))
        started = time.perf_counter()
        output, is_error = await _dispatch_tool(run, block.name, block.input)
        elapsed = time.perf_counter() - started
        if is_error:
            run.log.warning(
                "tool {} FAILED in {:.2f}s: {}", block.name, elapsed, short(output, 300)
            )
        else:
            run.log.info(
                "tool {} ok in {:.2f}s: {}", block.name, elapsed, short(output, 300)
            )
        run.job.add_tool_call(block.name, dict(block.input), output, is_error)
        results.append(
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": output,
                "is_error": is_error,
            }
        )
    return results


async def run_agent(
    job: Job,
    fs: filesystem.Filesystem,
    anthropic_client: AsyncAnthropic,
    http_client: httpx.AsyncClient,
    on_progress: OnProgress | None = None,
) -> str:
    """Drive the agent to completion and return the final text answer.

    `on_progress` is awaited once per iteration, after the job record has been
    updated with that iteration's narration and tool calls — the runner uses it
    to flush partial progress to the database.
    """
    log = job_logger(job.id)
    run = _Run(
        job=job,
        fs=fs,
        anthropic=anthropic_client,
        http=http_client,
        log=log,
        on_progress=on_progress or _no_progress,
    )
    messages: list[dict] = [{"role": "user", "content": job.task}]
    log.info("agent starting (workspace={}, task={})", fs.root, short(job.task, 200))

    for iteration in range(1, settings.max_iterations + 1):
        log.info("--- iteration {}/{} ---", iteration, settings.max_iterations)
        response = await _ask_claude(run, messages)
        text = _record_text(run, response)

        match response.stop_reason:
            case "end_turn":
                log.info("agent finished after {} iteration(s)", iteration)
                return text

            # Server-side loop paused; re-send the turn so far to let it resume.
            case "pause_turn":
                log.info("turn paused server-side; resuming")
                messages.append({"role": "assistant", "content": response.content})
                await run.on_progress()

            case "tool_use":
                # Echo back the full assistant content (incl. thinking + tool_use
                # blocks), then answer every tool call in a single user message.
                messages.append({"role": "assistant", "content": response.content})
                messages.append(
                    {"role": "user", "content": await _run_tools(run, response)}
                )
                await run.on_progress()

            case "refusal":
                log.error("model refused the task")
                raise RuntimeError("the model declined to complete this task (refusal)")

            case other:
                log.error("unexpected stop_reason: {}", other)
                raise RuntimeError(f"unexpected stop_reason: {other}")

    log.error("iteration budget exhausted ({})", settings.max_iterations)
    raise RuntimeError(
        f"agent did not finish within {settings.max_iterations} iterations"
    )
