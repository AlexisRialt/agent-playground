"""A filesystem tool scoped to a single per-job workspace directory.

Every path the model supplies is resolved and confirmed to stay inside the
workspace root before any I/O happens, so the agent cannot read or write
outside its sandbox (no `..` traversal, absolute paths, or symlink escapes).
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log

# Anthropic tool definition. One tool, three commands — see CLAUDE spec: "the file system".
TOOL_DEFINITION = {
    "name": "filesystem",
    "description": (
        "Read, write, and list files in your private, sandboxed workspace directory. "
        "Use this to persist intermediate work, save findings, and produce output files. "
        "Paths are always relative to the workspace root; you cannot access files outside it.\n"
        "Commands:\n"
        "- list: list files/directories under `path` (use '.' for the workspace root).\n"
        "- read: return the text contents of the file at `path`.\n"
        "- write: create or overwrite the file at `path` with `content` (parent dirs are created)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["list", "read", "write"],
                "description": "The operation to perform.",
            },
            "path": {
                "type": "string",
                "description": "Path relative to the workspace root, e.g. 'notes.md' or 'data/out.json'.",
            },
            "content": {
                "type": "string",
                "description": "Text to write. Required for the 'write' command; ignored otherwise.",
            },
        },
        "required": ["command", "path"],
    },
}

# Refuse to read/return files larger than this to avoid blowing up the context window.
_MAX_READ_BYTES = 200_000


class Filesystem:
    """Bound to one workspace root; all operations are confined to it."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        log.debug("workspace ready: {}", self.root)

    def _resolve(self, rel_path: str) -> Path:
        target = (self.root / rel_path).resolve()
        if target != self.root and self.root not in target.parents:
            log.warning("blocked sandbox escape: {!r} (root={})", rel_path, self.root)
            raise ValueError(f"path '{rel_path}' escapes the workspace sandbox")
        return target

    def run(self, command: str, path: str = ".", content: str | None = None) -> str:
        """Dispatch a command. Returns a human/model-readable string result.

        Raises ValueError / OSError on bad input; the caller turns those into an
        is_error tool result so the agent can recover.
        """
        log.debug("fs {} {!r} (root={})", command, path, self.root)
        if command == "list":
            return self._list(path)
        if command == "read":
            return self._read(path)
        if command == "write":
            if content is None:
                raise ValueError("the 'write' command requires 'content'")
            return self._write(path, content)
        raise ValueError(f"unknown command '{command}'")

    def _list(self, path: str) -> str:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(f"'{path}' does not exist")
        if target.is_file():
            return f"{path} (file, {target.stat().st_size} bytes)"
        entries = sorted(target.iterdir())
        if not entries:
            return f"{path} is empty"
        lines = []
        for entry in entries:
            rel = entry.relative_to(self.root)
            if entry.is_dir():
                lines.append(f"{rel}/")
            else:
                lines.append(f"{rel} ({entry.stat().st_size} bytes)")
        return "\n".join(lines)

    def _read(self, path: str) -> str:
        target = self._resolve(path)
        if not target.is_file():
            raise FileNotFoundError(f"'{path}' is not a file")
        size = target.stat().st_size
        if size > _MAX_READ_BYTES:
            raise ValueError(
                f"'{path}' is {size} bytes, exceeding the {_MAX_READ_BYTES}-byte read limit"
            )
        return target.read_text(encoding="utf-8", errors="replace")

    def _write(self, path: str, content: str) -> str:
        target = self._resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        log.info("fs wrote {} chars -> {}", len(content), target)
        return f"wrote {len(content)} characters to {path}"
