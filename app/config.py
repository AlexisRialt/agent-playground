"""Runtime configuration, sourced from environment variables.

`ANTHROPIC_API_KEY` is read by the Anthropic SDK directly (see .envrc). Everything
here is agent/server tuning with sensible defaults so the app runs out of the box.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    model: str
    # max tool-use round-trips before the loop gives up
    max_iterations: int
    # per-response output cap (16k stays under the non-streaming timeout)
    max_tokens: int
    effort: str  # low | medium | high | xhigh | max
    workspace_root: Path  # each job gets an isolated workspace/<job_id> sandbox
    serper_api_key: str | None  # SerpAPI key; absent -> google_search returns a stub
    log_level: str  # DEBUG surfaces the agent's thinking and full tool payloads

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            model=os.getenv("AGENT_MODEL", "claude-opus-4-8"),
            max_iterations=int(os.getenv("AGENT_MAX_ITERATIONS", "20")),
            max_tokens=int(os.getenv("AGENT_MAX_TOKENS", "16000")),
            effort=os.getenv("AGENT_EFFORT", "high"),
            workspace_root=Path(os.getenv("AGENT_WORKSPACE", "workspace")).resolve(),
            serper_api_key=os.getenv("SERPER_API_KEY"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )


settings = Settings.from_env()
