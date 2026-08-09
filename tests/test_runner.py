"""`execute_job` — the background job lifecycle and its writes to the store."""

from __future__ import annotations

import pytest

from app import runner
from app.jobs import InMemoryJobStore, Job, JobStatus
from app.runner import execute_job
from tests.conftest import FakeAnthropic, make_message, text_block, tool_use_block


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
        async def wrapper(job, fs, anthropic_client, http_client, on_progress=None):
            calls.append(
                {
                    "job": job,
                    "fs": fs,
                    "anthropic": anthropic_client,
                    "http": http_client,
                    "on_progress": on_progress,
                    "status_during_run": job.status,
                }
            )
            return await impl(job, fs)

        monkeypatch.setattr(runner, "run_agent", wrapper)
        return calls

    return _install


class RecordingStore(InMemoryJobStore):
    """An in-memory store that also remembers a snapshot of every `save()`."""

    def __init__(self) -> None:
        super().__init__()
        self.saves: list[dict] = []

    async def save(self, job: Job) -> None:
        await super().save(job)
        # Snapshot: `to_dict()` aliases the job's live lists, and the runner
        # keeps mutating the same object after this save returns.
        self.saves.append(
            job.to_dict() | {"log": list(job.log), "tool_calls": list(job.tool_calls)}
        )


@pytest.fixture
def recording_store() -> RecordingStore:
    return RecordingStore()


async def test_successful_job_is_recorded(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        return "the final answer"

    stub_agent(impl)
    job = Job(task="do it")

    await execute_job(job, FakeAnthropic(), http_client, store)

    assert job.status is JobStatus.COMPLETED
    assert job.result == "the final answer"
    assert job.error is None


async def test_the_job_is_running_while_the_agent_works(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        return "ok"

    calls = stub_agent(impl)
    await execute_job(Job(task="t"), FakeAnthropic(), http_client, store)

    assert calls[0]["status_during_run"] is JobStatus.RUNNING


async def test_clients_are_passed_through_to_the_agent(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        return "ok"

    calls = stub_agent(impl)
    anthropic = FakeAnthropic()
    job = Job(task="t")

    await execute_job(job, anthropic, http_client, store)

    assert calls[0]["job"] is job
    assert calls[0]["anthropic"] is anthropic
    assert calls[0]["http"] is http_client


async def test_each_job_gets_its_own_workspace_directory(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        fs.run("write", "artifact.txt", "content")
        return "ok"

    calls = stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client, store)

    assert calls[0]["fs"].root == workspace_root / job.id
    assert (workspace_root / job.id / "artifact.txt").read_text() == "content"


async def test_two_jobs_do_not_share_a_workspace(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        fs.run("write", "mine.txt", job.task)
        return "ok"

    stub_agent(impl)
    a, b = Job(task="alpha"), Job(task="beta")

    await execute_job(a, FakeAnthropic(), http_client, store)
    await execute_job(b, FakeAnthropic(), http_client, store)

    assert (workspace_root / a.id / "mine.txt").read_text() == "alpha"
    assert (workspace_root / b.id / "mine.txt").read_text() == "beta"


async def test_the_workspace_is_created_even_if_the_agent_fails(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        raise RuntimeError("nope")

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client, store)

    assert (workspace_root / job.id).is_dir()


async def test_agent_failure_is_recorded_not_raised(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        raise RuntimeError("the model declined to complete this task (refusal)")

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client, store)  # must not raise

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
    workspace_root, stub_agent, http_client, store, exc, expected
):
    async def impl(job, fs):
        raise exc

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client, store)

    assert job.error == expected
    assert job.status is JobStatus.FAILED


async def test_partial_progress_survives_a_failure(
    workspace_root, stub_agent, http_client, store
):
    async def impl(job, fs):
        job.add_log("PLAN: step one")
        job.add_tool_call("filesystem", {"command": "list"}, ". is empty", False)
        raise RuntimeError("gave up")

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client, store)

    assert job.status is JobStatus.FAILED
    assert job.log == ["PLAN: step one"]
    assert len(job.tool_calls) == 1


@pytest.mark.parametrize("fails", [False, True])
async def test_updated_at_is_touched_either_way(
    workspace_root, stub_agent, http_client, store, fails
):
    async def impl(job, fs):
        if fails:
            raise RuntimeError("boom")
        return "ok"

    stub_agent(impl)
    job = Job(task="t")
    job.updated_at = "2000-01-01T00:00:00+00:00"

    await execute_job(job, FakeAnthropic(), http_client, store)

    assert job.updated_at > "2000-01-01T00:00:00+00:00"


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


async def test_the_job_is_saved_as_running_before_the_agent_starts(
    workspace_root, stub_agent, http_client, recording_store
):
    async def impl(job, fs):
        return "ok"

    stub_agent(impl)

    await execute_job(Job(task="t"), FakeAnthropic(), http_client, recording_store)

    assert recording_store.saves[0]["status"] == "running"


@pytest.mark.parametrize(
    ("impl_result", "expected"),
    [("done", "completed"), (None, "failed")],
)
async def test_the_final_state_is_saved(
    workspace_root, stub_agent, http_client, recording_store, impl_result, expected
):
    async def impl(job, fs):
        if impl_result is None:
            raise RuntimeError("boom")
        return impl_result

    stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client, recording_store)

    assert recording_store.saves[-1]["status"] == expected
    assert (await recording_store.get(job.id)).status.value == expected


async def test_the_agent_gets_a_checkpoint_callback_that_saves(
    workspace_root, stub_agent, http_client, recording_store
):
    async def impl(job, fs):
        return "ok"

    calls = stub_agent(impl)
    job = Job(task="t")

    await execute_job(job, FakeAnthropic(), http_client, recording_store)

    before = len(recording_store.saves)
    await calls[0]["on_progress"]()
    assert len(recording_store.saves) == before + 1


async def test_mid_run_progress_is_flushed_to_the_store(
    workspace_root, http_client, recording_store
):
    """The real loop: a tool-use turn must be persisted before the job ends."""
    anthropic = FakeAnthropic(
        make_message(
            [
                text_block("PLAN: list the workspace"),
                tool_use_block("filesystem", {"command": "list", "path": "."}),
            ],
            "tool_use",
        ),
        make_message([text_block("all done")], "end_turn"),
    )
    job = Job(task="t")

    await execute_job(job, anthropic, http_client, recording_store)

    # running -> after the tool-use iteration -> final. The middle save already
    # carries the plan and the tool call.
    mid = recording_store.saves[1]
    assert mid["status"] == "running"
    assert mid["log"] == ["PLAN: list the workspace"]
    assert len(mid["tool_calls"]) == 1


async def test_a_failing_store_does_not_propagate_out_of_the_runner(
    workspace_root, stub_agent, http_client
):
    class BrokenStore(InMemoryJobStore):
        async def save(self, job):
            raise RuntimeError("postgres is down")

    async def impl(job, fs):
        return "ok"

    stub_agent(impl)
    job = Job(task="t")

    # The first save raises inside the try block and is recorded as job failure;
    # the final save raises too and must be swallowed rather than kill the task.
    await execute_job(job, FakeAnthropic(), http_client, BrokenStore())

    assert job.status is JobStatus.FAILED


async def test_end_to_end_against_the_real_agent_loop(
    workspace_root, http_client, store
):
    """No `run_agent` stub: the real loop, driven by a fake Claude client."""
    anthropic = FakeAnthropic(
        make_message([text_block("PLAN: answer directly")], "end_turn")
    )
    job = Job(task="what is 2+2")

    await execute_job(job, anthropic, http_client, store)

    assert job.status is JobStatus.COMPLETED
    assert job.result == "PLAN: answer directly"
    assert job.log == ["PLAN: answer directly"]
    assert (await store.get(job.id)).result == "PLAN: answer directly"
