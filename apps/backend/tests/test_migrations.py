"""Structural checks on the Alembic revision history.

The initial revision uses Postgres-only `JSONB` columns, so it can't run
against the SQLite engine the rest of the suite uses — this doesn't execute
`alembic upgrade head`, it just checks the revision files are well-formed and
form a single linear history (see `alembic upgrade head --sql` for a manual
DDL sanity check against a real Postgres instance).
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parent.parent


def _script_directory() -> ScriptDirectory:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def test_revision_history_is_linear():
    heads = _script_directory().get_heads()
    assert len(heads) == 1


def test_every_revision_defines_upgrade_and_downgrade():
    script_dir = _script_directory()
    revisions = list(script_dir.walk_revisions())
    assert revisions, "expected at least one migration"
    for revision in revisions:
        module = revision.module
        assert callable(module.upgrade)
        assert callable(module.downgrade)
