"""Create persistent dashboard session visibility."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "hidden_sessions",
        sa.Column("session_id", sa.String(length=10), nullable=False),
        sa.Column("hidden_by", sa.String(length=64), nullable=False),
        sa.Column("hidden_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("session_id"),
    )


def downgrade() -> None:
    op.drop_table("hidden_sessions")
