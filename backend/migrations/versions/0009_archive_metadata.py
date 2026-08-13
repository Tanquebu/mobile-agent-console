"""Add descriptive metadata to archived sessions."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "archived_sessions",
        sa.Column("agent_session_name", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "archived_sessions",
        sa.Column("summary", sa.String(length=2000), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("archived_sessions", "summary")
    op.drop_column("archived_sessions", "agent_session_name")
