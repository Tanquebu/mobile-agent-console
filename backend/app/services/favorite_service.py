from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..models import Favorite


class FavoriteService:
    def __init__(self, engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def list_for_user(self, username: str) -> list[Favorite]:
        with self._sessions() as session:
            return list(
                session.scalars(
                    select(Favorite)
                    .where(Favorite.added_by == username)
                    .order_by(Favorite.added_at.desc())
                )
            )

    def create(self, path: str, label: str | None, added_by: str) -> Favorite:
        with self._sessions.begin() as session:
            existing = session.scalars(
                select(Favorite).where(
                    Favorite.path == path, Favorite.added_by == added_by
                )
            ).first()
            if existing is not None:
                return existing
            item = Favorite(
                id=uuid4().hex,
                path=path,
                label=label,
                added_by=added_by,
                added_at=datetime.now(UTC),
            )
            session.add(item)
        return item

    def delete(self, favorite_id: str, added_by: str) -> bool:
        with self._sessions.begin() as session:
            item = session.get(Favorite, favorite_id)
            if not item or item.added_by != added_by:
                return False
            session.delete(item)
        return True
