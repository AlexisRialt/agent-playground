"""A single agent job: its task, progress, and outcome."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from app.jobs.status import JobStatus
from app.jobs.timestamps import now_iso
from app.jobs.tool_call import ToolCall


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
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)

    def touch(self) -> None:
        self.updated_at = now_iso()

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
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
