"""One recorded tool call made by the agent while working a job."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.jobs.timestamps import now_iso


@dataclass
class ToolCall:
    tool: str
    input: dict[str, Any]
    output: str
    is_error: bool
    at: str = field(default_factory=now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "input": self.input,
            "output": self.output,
            "is_error": self.is_error,
            "at": self.at,
        }
