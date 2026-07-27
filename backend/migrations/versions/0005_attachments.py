"""Create persistent attachment metadata."""

import json
import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("media_type", sa.String(length=100), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("path", sa.String(length=4096), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_attachments_session_id"), "attachments", ["session_id"], unique=False
    )
    op.create_index(
        op.f("ix_attachments_created_at"), "attachments", ["created_at"], unique=False
    )
    _backfill_from_json_sidecars()


def _backfill_from_json_sidecars() -> None:
    # Prima di questa migrazione i metadati vivevano in un .json accanto al
    # file: recuperarli nella tabella evita di invalidare allegati caricati
    # poco prima del deploy (TTL tipico ~24h, non vanno persi silenziosamente).
    root = Path(os.environ.get("MAC_ATTACHMENTS_ROOT", "/workspace/.agent-attachments"))
    if not root.is_dir():
        return
    table = sa.table(
        "attachments",
        sa.column("id"),
        sa.column("session_id"),
        sa.column("name"),
        sa.column("media_type"),
        sa.column("size"),
        sa.column("path"),
        sa.column("created_at"),
    )
    bind = op.get_bind()
    rows = []
    sidecars = []
    for metadata_path in root.glob("*/*.json"):
        try:
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            rows.append(
                {
                    "id": data["id"],
                    "session_id": data["session_id"],
                    "name": data["name"],
                    "media_type": data["media_type"],
                    "size": data["size"],
                    "path": data["path"],
                    "created_at": datetime.fromtimestamp(metadata_path.stat().st_mtime, UTC),
                }
            )
            sidecars.append(metadata_path)
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
    if rows:
        bind.execute(sa.insert(table), rows)
    for metadata_path in sidecars:
        metadata_path.unlink(missing_ok=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_attachments_created_at"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_session_id"), table_name="attachments")
    op.drop_table("attachments")
