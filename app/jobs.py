"""In-memory job store and record types.

This is a single-process playground store — jobs live in a dict and are lost on
restart. Swap in Redis/a database if you need durability or multiple workers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class ToolCall:
    tool: str
    input: dict[str, Any]
    output: str
    is_error: bool
    at: str = field(default_factory=_now)


@dataclass
class Job:
    task: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    status: JobStatus = JobStatus.PENDING
    # Assistant narration/thinking summaries captured as the agent works.
    log: list[str] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(self) -> None:
        self.updated_at = _now()

    def add_log(self, text: str) -> None:
        if text.strip():
            self.log.append(text)
            self.touch()

    def add_tool_call(
        self, tool: str, tool_input: dict, output: str, is_error: bool
    ) -> None:
        self.tool_calls.append(
            ToolCall(tool=tool, input=tool_input, output=output, is_error=is_error)
        )
        self.touch()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "status": self.status.value,
            "task": self.task,
            "log": self.log,
            "tool_calls": [
                {
                    "tool": tc.tool,
                    "input": tc.input,
                    "output": tc.output,
                    "is_error": tc.is_error,
                    "at": tc.at,
                }
                for tc in self.tool_calls
            ],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def create(self, task: str) -> Job:
        job = Job(task=task)
        self._jobs[job.id] = job
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list(self) -> list[Job]:
        return list(self._jobs.values())
