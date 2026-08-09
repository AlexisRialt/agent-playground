"""`execute_job` — the background job lifecycle."""

from __future__ import annotations

import pytest

from app import runner
from app.jobs import Job, JobStatus
from app.runner import execute_job
from tests.conftest import FakeAnthropic, make_message, text_block


@pytest.fixture
def workspace_root(tmp_path, patch_settings):
    root = tmp_path / "workspaces"
    patch_settings("app.runner", workspace_root=root)
    return root


@pytest.fixture
def stub_agent(monkeypatch):
    """Replace `run_agent` with a recorder; returns the captured call list."""
    calls = []

    def _install(impl):
        async def wrapper(job, fs, anthropic_client, http_client):
            calls.append(
                {
                    "job": job,
                    "fs": fs,
                    "anthropic": anthropic_client,
                    "http": http_client,
                    "status_during_run": job.status,
                }
            )
            return await impl(job, fs)

        monkeypatch.setattr(runner, "run_agent", wrapper)
        return calls

    return _install


async def test_successful_job_is_recorded(workspace_root, stub_agent, http_client):
    async def impl(job, fs):
        return "the final answer"

    stub_agent(impl)
    job = Job(task="do it")

    await execute_job(job, FakeAnthropic(), http_client)

    assert job.status is JobStatus.COMPLETED
    assert job.result == "the final answer"
    assert job.error is None


async def test_the_job_is_running_while_the_agent_works(
    workspace_root, stub_agent, http_client
):
    async def impl(job, fs):
        return "ok"

    calls = stub_agent(impl)
    await execute_job(Job(task="t"), FakeAnthropic(), http_client)

    assert calls[0]["status_during_run"] is JobStatus.RUNNING


async def test_clients_are_passed_through_to_the_agent(
    workspace_root, stub_agent, http_client
):
    async def impl(job, fs):
        return "ok"

    calls = stub_agent(impl)
    anthropic = FakeAnthropic()
    job = Job(task="t")

    await execute_job(job, anthropic, http_client)

    assert calls[0]["job"] is job
    assert calls[0]["anthropic"] is anthropic
    assert calls[0]["http"] is http_client


async def test_each_job_gets_its_own_workspace_directory(
    workspace_root, stub_agent, http_client
):
    async def impl(job, fs):
        fs.run("write", "artifact.txt", "content")
        return "ok"

    calls = stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client)

    assert calls[0]["fs"].root == workspace_root / job.id
    assert (workspace_root / job.id / "artifact.txt").read_text() == "content"


async def test_two_jobs_do_not_share_a_workspace(
    workspace_root, stub_agent, http_client
):
    async def impl(job, fs):
        fs.run("write", "mine.txt", job.task)
        return "ok"

    stub_agent(impl)
    a, b = Job(task="alpha"), Job(task="beta")

    await execute_job(a, FakeAnthropic(), http_client)
    await execute_job(b, FakeAnthropic(), http_client)

    assert (workspace_root / a.id / "mine.txt").read_text() == "alpha"
    assert (workspace_root / b.id / "mine.txt").read_text() == "beta"


async def test_the_workspace_is_created_even_if_the_agent_fails(
    workspace_root, stub_agent, http_client
):
    async def impl(job, fs):
        raise RuntimeError("nope")

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client)

    assert (workspace_root / job.id).is_dir()


async def test_agent_failure_is_recorded_not_raised(
    workspace_root, stub_agent, http_client
):
    async def impl(job, fs):
        raise RuntimeError("the model declined to complete this task (refusal)")

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client)  # must not raise

    assert job.status is JobStatus.FAILED
    assert job.error == (
        "RuntimeError: the model declined to complete this task (refusal)"
    )
    assert job.result is None


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (ValueError("bad input"), "ValueError: bad input"),
        (KeyError("missing"), "KeyError: 'missing'"),
        (TimeoutError(), "TimeoutError: "),
    ],
)
async def test_error_text_names_the_exception_type(
    workspace_root, stub_agent, http_client, exc, expected
):
    async def impl(job, fs):
        raise exc

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client)

    assert job.error == expected
    assert job.status is JobStatus.FAILED


async def test_partial_progress_survives_a_failure(
    workspace_root, stub_agent, http_client
):
    async def impl(job, fs):
        job.add_log("PLAN: step one")
        job.add_tool_call("filesystem", {"command": "list"}, ". is empty", False)
        raise RuntimeError("gave up")

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client)

    assert job.status is JobStatus.FAILED
    assert job.log == ["PLAN: step one"]
    assert len(job.tool_calls) == 1


@pytest.mark.parametrize("fails", [False, True])
async def test_updated_at_is_touched_either_way(
    workspace_root, stub_agent, http_client, fails
):
    async def impl(job, fs):
        if fails:
            raise RuntimeError("boom")
        return "ok"

    stub_agent(impl)
    job = Job(task="t")
    job.updated_at = "2000-01-01T00:00:00+00:00"

    await execute_job(job, FakeAnthropic(), http_client)

    assert job.updated_at > "2000-01-01T00:00:00+00:00"


async def test_end_to_end_against_the_real_agent_loop(workspace_root, http_client):
    """No `run_agent` stub: the real loop, driven by a fake Claude client."""
    anthropic = FakeAnthropic(
        make_message([text_block("PLAN: answer directly")], "end_turn")
    )
    job = Job(task="what is 2+2")

    await execute_job(job, anthropic, http_client)

    assert job.status is JobStatus.COMPLETED
    assert job.result == "PLAN: answer directly"
    assert job.log == ["PLAN: answer directly"]
