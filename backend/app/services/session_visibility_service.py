from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..models import HiddenSession


class SessionVisibilityService:
    def __init__(self, engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def hidden_ids(self, live_session_ids: set[str]) -> set[str]:
        if not live_session_ids:
            return set()
        with self._sessions() as session:
            return set(
                session.scalars(
                    select(HiddenSession.session_id).where(
                        HiddenSession.session_id.in_(live_session_ids)
                    )
                )
            )

    def set_hidden(self, session_id: str, hidden: bool, actor: str) -> None:
        with self._sessions.begin() as session:
            item = session.get(HiddenSession, session_id)
            if hidden:
                if item is None:
                    session.add(
                        HiddenSession(
                            session_id=session_id,
                            hidden_by=actor,
                            hidden_at=datetime.now(UTC),
                        )
                    )
            elif item is not None:
                session.delete(item)
