"""create jobs table

Revision ID: 555105324e29
Revises:
Create Date: 2026-08-23 12:21:36.546340

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "555105324e29"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "jobs",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column(
            "log", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column(
            "tool_calls",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
        sa.Column("result", sa.Text()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("jobs_created_at_idx", "jobs", ["created_at"])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("jobs_created_at_idx", table_name="jobs")
    op.drop_table("jobs")
