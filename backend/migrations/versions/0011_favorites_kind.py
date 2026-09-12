"""Add kind column to favorites (file vs dir)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("favorites") as batch_op:
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.String(length=8),
                nullable=False,
                server_default="file",
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("favorites") as batch_op:
        batch_op.drop_column("kind")
