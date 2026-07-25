from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..models import User


class UserService:
    def __init__(self, engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._hasher = PasswordHasher()
        self._dummy_hash = self._hasher.hash("not-a-real-mobile-agent-console-password")

    def has_users(self) -> bool:
        with self._sessions() as session:
            return bool(session.scalar(select(func.count()).select_from(User)))

    def bootstrap_admin(self, username: str, password: str) -> bool:
        with self._sessions.begin() as session:
            if session.scalar(select(func.count()).select_from(User)):
                return False
            session.add(
                User(
                    username=username,
                    password_hash=self._hasher.hash(password),
                    role="admin",
                    active=True,
                    created_at=datetime.now(UTC),
                    updated_at=datetime.now(UTC),
                )
            )
        return True

    def authenticate(self, username: str, password: str) -> User | None:
        with self._sessions() as session:
            user = session.scalar(select(User).where(User.username == username))
            password_hash = user.password_hash if user else self._dummy_hash
            try:
                valid = self._hasher.verify(password_hash, password)
            except (VerificationError, InvalidHashError):
                valid = False
            if not user or not user.active or not valid:
                return None
            if self._hasher.check_needs_rehash(user.password_hash):
                user.password_hash = self._hasher.hash(password)
                user.updated_at = datetime.now(UTC)
                session.commit()
            return user
