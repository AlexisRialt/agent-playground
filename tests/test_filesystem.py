"""The sandboxed filesystem tool.

The security-relevant half of this file is `test_sandbox_escapes` — every way a
model could name a path outside its workspace must raise before any I/O runs.
"""

from __future__ import annotations

import pytest

from app.tools import filesystem
from app.tools.filesystem import TOOL_DEFINITION, Filesystem

# --------------------------------------------------------------------------
# Tool definition
# --------------------------------------------------------------------------


def test_tool_definition_shape():
    assert TOOL_DEFINITION["name"] == "filesystem"
    assert TOOL_DEFINITION["description"]
    schema = TOOL_DEFINITION["input_schema"]
    assert schema["type"] == "object"
    assert schema["required"] == ["command", "path"]
    assert set(schema["properties"]) == {"command", "path", "content"}


def test_tool_definition_advertises_exactly_the_implemented_commands():
    assert TOOL_DEFINITION["input_schema"]["properties"]["command"]["enum"] == [
        "list",
        "read",
        "write",
    ]


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------


def test_root_is_created_on_construction(tmp_path):
    root = tmp_path / "deep" / "nested" / "ws"
    assert not root.exists()
    assert Filesystem(root).root.is_dir()


def test_root_is_resolved_to_an_absolute_path(tmp_path):
    fs = Filesystem(tmp_path / "a" / ".." / "ws")
    assert fs.root == (tmp_path / "ws").resolve()
    assert fs.root.is_absolute()


def test_construction_is_idempotent_over_an_existing_root(tmp_path):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "keep.txt").write_text("kept")
    fs = Filesystem(tmp_path / "ws")
    assert fs.run("read", "keep.txt") == "kept"


def test_two_workspaces_are_isolated(tmp_path):
    a = Filesystem(tmp_path / "a")
    b = Filesystem(tmp_path / "b")
    a.run("write", "note.txt", "from a")
    assert b.run("list", ".") == ". is empty"
    with pytest.raises(FileNotFoundError):
        b.run("read", "note.txt")


# --------------------------------------------------------------------------
# write
# --------------------------------------------------------------------------


def test_write_creates_a_file_and_reports_the_character_count(fs):
    assert fs.run("write", "notes.md", "hello") == "wrote 5 characters to notes.md"
    assert (fs.root / "notes.md").read_text() == "hello"


def test_write_creates_missing_parent_directories(fs):
    fs.run("write", "data/nested/out.json", '{"ok": true}')
    assert (fs.root / "data" / "nested" / "out.json").read_text() == '{"ok": true}'


def test_write_overwrites_an_existing_file(fs):
    fs.run("write", "f.txt", "first")
    fs.run("write", "f.txt", "second")
    assert (fs.root / "f.txt").read_text() == "second"


def test_write_round_trips_unicode(fs):
    payload = "héllo — 世界 🌍"
    fs.run("write", "u.txt", payload)
    assert fs.run("read", "u.txt") == payload


def test_write_accepts_empty_content(fs):
    assert fs.run("write", "empty.txt", "") == "wrote 0 characters to empty.txt"
    assert fs.run("read", "empty.txt") == ""


def test_write_without_content_is_rejected(fs):
    with pytest.raises(ValueError, match="requires 'content'"):
        fs.run("write", "f.txt")
    assert not (fs.root / "f.txt").exists()


def test_write_counts_characters_not_bytes(fs):
    """The message the model sees should match the string it sent."""
    assert fs.run("write", "u.txt", "é" * 4) == "wrote 4 characters to u.txt"


# --------------------------------------------------------------------------
# read
# --------------------------------------------------------------------------


def test_read_returns_file_contents(fs):
    (fs.root / "a.txt").write_text("contents")
    assert fs.run("read", "a.txt") == "contents"


def test_read_missing_file(fs):
    with pytest.raises(FileNotFoundError, match="is not a file"):
        fs.run("read", "nope.txt")


def test_read_a_directory_is_rejected(fs):
    (fs.root / "sub").mkdir()
    with pytest.raises(FileNotFoundError, match="is not a file"):
        fs.run("read", "sub")


def test_read_enforces_the_size_limit(fs, monkeypatch):
    monkeypatch.setattr(filesystem, "_MAX_READ_BYTES", 10)
    fs.run("write", "big.txt", "x" * 11)
    with pytest.raises(ValueError, match="exceeding the 10-byte read limit"):
        fs.run("read", "big.txt")


def test_read_allows_a_file_exactly_at_the_limit(fs, monkeypatch):
    monkeypatch.setattr(filesystem, "_MAX_READ_BYTES", 10)
    fs.run("write", "edge.txt", "x" * 10)
    assert fs.run("read", "edge.txt") == "x" * 10


def test_read_replaces_undecodable_bytes_instead_of_raising(fs):
    (fs.root / "bin.dat").write_bytes(b"ok\xff\xfebytes")
    out = fs.run("read", "bin.dat")
    assert out.startswith("ok")
    assert "�" in out


# --------------------------------------------------------------------------
# list
# --------------------------------------------------------------------------


def test_list_empty_workspace(fs):
    assert fs.run("list", ".") == ". is empty"


def test_list_defaults_to_the_workspace_root(fs):
    assert fs.run("list") == ". is empty"


def test_list_shows_files_with_sizes_and_directories_with_a_slash(fs):
    fs.run("write", "b.txt", "abc")
    (fs.root / "a_dir").mkdir()
    assert fs.run("list", ".") == "a_dir/\nb.txt (3 bytes)"


def test_list_is_sorted(fs):
    for name in ("c.txt", "a.txt", "b.txt"):
        fs.run("write", name, "x")
    assert [line.split(" ")[0] for line in fs.run("list", ".").splitlines()] == [
        "a.txt",
        "b.txt",
        "c.txt",
    ]


def test_list_paths_are_relative_to_the_workspace_root(fs):
    fs.run("write", "data/out.json", "{}")
    assert fs.run("list", "data") == "data/out.json (2 bytes)"


def test_list_does_not_recurse(fs):
    fs.run("write", "data/nested/deep.txt", "x")
    assert fs.run("list", ".") == "data/"


def test_list_on_a_file_describes_that_file(fs):
    fs.run("write", "solo.txt", "12345")
    assert fs.run("list", "solo.txt") == "solo.txt (file, 5 bytes)"


def test_list_missing_path(fs):
    with pytest.raises(FileNotFoundError, match="does not exist"):
        fs.run("list", "ghost")


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


@pytest.mark.parametrize("command", ["delete", "LIST", "exec", "", "rm -rf"])
def test_unknown_commands_are_rejected(fs, command):
    with pytest.raises(ValueError, match="unknown command"):
        fs.run(command, ".")


def test_content_is_ignored_for_non_write_commands(fs):
    fs.run("write", "a.txt", "kept")
    assert fs.run("read", "a.txt", "ignored") == "kept"


# --------------------------------------------------------------------------
# Sandbox containment
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "escape",
    [
        "..",
        "../secret.txt",
        "../../etc/passwd",
        "a/../../outside.txt",
        "/etc/passwd",
        "/tmp/absolute.txt",
        "./../sibling/file",
    ],
)
@pytest.mark.parametrize("command", ["list", "read", "write"])
def test_sandbox_escapes_are_blocked(fs, escape, command):
    with pytest.raises(ValueError, match="escapes the workspace sandbox"):
        fs.run(command, escape, "payload")


def test_escape_is_blocked_before_any_write_happens(tmp_path, fs):
    victim = tmp_path / "victim.txt"
    victim.write_text("original")
    with pytest.raises(ValueError, match="escapes the workspace sandbox"):
        fs.run("write", "../victim.txt", "overwritten")
    assert victim.read_text() == "original"


def test_symlink_out_of_the_sandbox_is_blocked(tmp_path, fs):
    secret = tmp_path / "secret.txt"
    secret.write_text("classified")
    (fs.root / "link.txt").symlink_to(secret)
    with pytest.raises(ValueError, match="escapes the workspace sandbox"):
        fs.run("read", "link.txt")


def test_symlinked_directory_out_of_the_sandbox_is_blocked(tmp_path, fs):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "f.txt").write_text("nope")
    (fs.root / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes the workspace sandbox"):
        fs.run("list", "escape")


def test_symlink_inside_the_sandbox_is_allowed(fs):
    fs.run("write", "real.txt", "inside")
    (fs.root / "alias.txt").symlink_to(fs.root / "real.txt")
    assert fs.run("read", "alias.txt") == "inside"


def test_traversal_that_lands_back_inside_is_allowed(fs):
    fs.run("write", "dir/f.txt", "ok")
    assert fs.run("read", "dir/../dir/f.txt") == "ok"


def test_deeply_nested_paths_are_allowed(fs):
    fs.run("write", "a/b/c/d/e.txt", "deep")
    assert fs.run("read", "a/b/c/d/e.txt") == "deep"
