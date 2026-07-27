"""Add content hash to attachments for per-session deduplication."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("attachments", sa.Column("content_hash", sa.String(length=64), nullable=True))
    op.create_index(
        op.f("ix_attachments_content_hash"), "attachments", ["content_hash"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_attachments_content_hash"), table_name="attachments")
    op.drop_column("attachments", "content_hash")
