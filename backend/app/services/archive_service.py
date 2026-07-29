from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..models import ArchivedSession

PROFILES = {"shell", "codex", "claude", "antigravity"}


class ArchiveService:
    def __init__(self, engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def list(self) -> list[ArchivedSession]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(ArchivedSession).order_by(ArchivedSession.archived_at.desc())
                )
            )

    def get(self, archive_id: str) -> ArchivedSession | None:
        with self._sessions() as session:
            return session.get(ArchivedSession, archive_id)

    def create(
        self, name: str, directory: str, profile: str, archived_by: str
    ) -> ArchivedSession:
        if profile not in PROFILES:
            raise ValueError("Unsupported profile")
        item = ArchivedSession(
            id=str(uuid4()),
            name=name,
            directory=directory,
            profile=profile,
            archived_by=archived_by,
            archived_at=datetime.now(UTC),
        )
        with self._sessions.begin() as session:
            session.add(item)
        return item

    def delete(self, archive_id: str) -> bool:
        with self._sessions.begin() as session:
            item = session.get(ArchivedSession, archive_id)
            if not item:
                return False
            session.delete(item)
        return True
