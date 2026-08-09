"""Job records: `Job`, `JobStatus`, `ToolCall`, `JobStore`, `now_iso`."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

from app.jobs import Job, JobStatus, JobStore, ToolCall
from app.jobs.timestamps import now_iso

# A timestamp that is unambiguously older than anything `now_iso()` produces.
# Tests backdate `updated_at` to it rather than mocking the clock, so ISO string
# comparisons stay strict without depending on wall-clock resolution.
OLD = "2000-01-01T00:00:00+00:00"


# --------------------------------------------------------------------------
# now_iso
# --------------------------------------------------------------------------


def test_now_iso_is_parseable_utc():
    parsed = datetime.fromisoformat(now_iso())
    assert parsed.tzinfo is not None
    assert parsed.utcoffset() == UTC.utcoffset(None)


def test_now_iso_is_newer_than_the_backdated_sentinel():
    assert now_iso() > OLD


def test_now_iso_is_non_decreasing():
    assert now_iso() <= now_iso()


# --------------------------------------------------------------------------
# JobStatus
# --------------------------------------------------------------------------


def test_job_status_values():
    assert {s.value for s in JobStatus} == {
        "pending",
        "running",
        "completed",
        "failed",
    }


def test_job_status_is_a_str_enum():
    assert JobStatus.RUNNING == "running"
    assert isinstance(JobStatus.RUNNING, str)
    assert json.dumps({"status": JobStatus.FAILED.value}) == '{"status": "failed"}'


# --------------------------------------------------------------------------
# ToolCall
# --------------------------------------------------------------------------


def test_tool_call_to_dict_round_trips_every_field():
    call = ToolCall(
        tool="filesystem",
        input={"command": "read", "path": "a.txt"},
        output="hello",
        is_error=False,
        at="2026-01-01T00:00:00+00:00",
    )
    assert call.to_dict() == {
        "tool": "filesystem",
        "input": {"command": "read", "path": "a.txt"},
        "output": "hello",
        "is_error": False,
        "at": "2026-01-01T00:00:00+00:00",
    }


def test_tool_call_timestamps_itself():
    call = ToolCall(
        tool="google_search", input={"query": "x"}, output="", is_error=True
    )
    assert datetime.fromisoformat(call.at).tzinfo is not None


# --------------------------------------------------------------------------
# Job
# --------------------------------------------------------------------------


def test_job_defaults():
    job = Job(task="do the thing")
    assert job.task == "do the thing"
    assert job.status is JobStatus.PENDING
    assert job.log == []
    assert job.tool_calls == []
    assert job.result is None
    assert job.error is None
    assert job.created_at <= job.updated_at
    assert job.created_at > OLD


def test_job_id_is_a_fresh_uuid_hex():
    job = Job(task="t")
    assert re.fullmatch(r"[0-9a-f]{32}", job.id)
    assert job.id != Job(task="t").id


def test_job_id_can_be_supplied():
    assert Job(task="t", id="fixed-id").id == "fixed-id"


def test_touch_advances_updated_at_only():
    job = Job(task="t")
    created = job.created_at
    job.updated_at = OLD
    job.touch()
    assert job.created_at == created
    assert job.updated_at > OLD


def test_add_log_appends_and_touches():
    job = Job(task="t")
    job.updated_at = OLD
    job.add_log("step one")
    job.add_log("step two")
    assert job.log == ["step one", "step two"]
    assert job.updated_at > OLD


@pytest.mark.parametrize("blank", ["", "   ", "\n", "\t \n"])
def test_add_log_ignores_blank_text(blank):
    job = Job(task="t")
    job.updated_at = OLD
    job.add_log(blank)
    assert job.log == []
    assert job.updated_at == OLD


def test_add_log_preserves_surrounding_whitespace_of_real_text():
    job = Job(task="t")
    job.add_log("  padded  ")
    assert job.log == ["  padded  "]


def test_add_tool_call_records_a_tool_call():
    job = Job(task="t")
    job.updated_at = OLD
    job.add_tool_call("filesystem", {"command": "list"}, "a.txt", False)

    assert len(job.tool_calls) == 1
    call = job.tool_calls[0]
    assert isinstance(call, ToolCall)
    assert call.tool == "filesystem"
    assert call.input == {"command": "list"}
    assert call.output == "a.txt"
    assert call.is_error is False
    assert job.updated_at > OLD


def test_add_tool_call_keeps_call_order():
    job = Job(task="t")
    job.add_tool_call("google_search", {"query": "a"}, "r1", False)
    job.add_tool_call("filesystem", {"command": "write"}, "boom", True)
    assert [c.tool for c in job.tool_calls] == ["google_search", "filesystem"]
    assert [c.is_error for c in job.tool_calls] == [False, True]


def test_to_dict_exposes_the_full_api_shape():
    job = Job(task="t")
    job.add_log("plan")
    job.add_tool_call("filesystem", {"command": "list"}, "empty", False)
    job.result = "all done"
    job.status = JobStatus.COMPLETED

    payload = job.to_dict()

    assert set(payload) == {
        "id",
        "status",
        "task",
        "log",
        "tool_calls",
        "result",
        "error",
        "created_at",
        "updated_at",
    }
    assert payload["status"] == "completed"  # the value, not the enum
    assert payload["log"] == ["plan"]
    assert payload["result"] == "all done"
    assert payload["error"] is None
    assert payload["tool_calls"] == [job.tool_calls[0].to_dict()]


def test_to_dict_is_json_serialisable():
    job = Job(task="t")
    job.add_tool_call("google_search", {"query": "x", "num_results": 3}, "res", False)
    job.error = "RuntimeError: nope"
    job.status = JobStatus.FAILED
    assert json.loads(json.dumps(job.to_dict()))["error"] == "RuntimeError: nope"


def test_to_dict_snapshots_tool_calls_as_plain_dicts():
    job = Job(task="t")
    job.add_tool_call("filesystem", {"command": "read"}, "out", False)
    assert all(isinstance(tc, dict) for tc in job.to_dict()["tool_calls"])


# --------------------------------------------------------------------------
# JobStore
# --------------------------------------------------------------------------


def test_store_create_returns_a_pending_job_and_keeps_it():
    store = JobStore()
    job = store.create("write a haiku")
    assert job.task == "write a haiku"
    assert job.status is JobStatus.PENDING
    assert store.get(job.id) is job


def test_store_get_unknown_id_returns_none():
    assert JobStore().get("nope") is None


def test_store_starts_empty():
    assert JobStore().list() == []


def test_store_list_preserves_insertion_order():
    store = JobStore()
    jobs = [store.create(f"task {i}") for i in range(3)]
    assert store.list() == jobs


def test_store_list_returns_a_copy():
    store = JobStore()
    store.create("a")
    listing = store.list()
    listing.clear()
    assert len(store.list()) == 1


def test_stores_do_not_share_state():
    a, b = JobStore(), JobStore()
    job = a.create("only in a")
    assert b.get(job.id) is None
    assert b.list() == []


def test_store_holds_live_references():
    """Mutations made by the background runner are visible to later polls."""
    store = JobStore()
    job = store.create("t")
    job.status = JobStatus.COMPLETED
    job.result = "done"
    assert store.get(job.id).result == "done"
