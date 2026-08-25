"""Create per-user favorite file paths."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("added_by", sa.String(length=64), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_favorites_added_by", "favorites", ["added_by"])


def downgrade() -> None:
    op.drop_index("ix_favorites_added_by", table_name="favorites")
    op.drop_table("favorites")
