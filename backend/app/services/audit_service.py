from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..models import AuditEvent


class AuditService:
    def __init__(self, engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def record(self, actor: str, action: str, target: str, outcome: int) -> AuditEvent:
        event = AuditEvent(
            actor=actor[:64],
            action=action[:160],
            target=target[:512],
            outcome=outcome,
            created_at=datetime.now(UTC),
        )
        with self._sessions.begin() as session:
            session.add(event)
        return event

    def list(self, limit: int = 200) -> list[AuditEvent]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(AuditEvent)
                    .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                    .limit(limit)
                )
            )
