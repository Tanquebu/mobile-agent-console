from datetime import UTC, datetime

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from ..models import User

ROLES = {"admin", "operator", "viewer"}


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

    def get(self, username: str) -> User | None:
        with self._sessions() as session:
            return session.scalar(select(User).where(User.username == username))

    def list(self) -> list[User]:
        with self._sessions() as session:
            return list(session.scalars(select(User).order_by(User.username)))

    def create(self, username: str, password: str, role: str) -> User:
        if role not in ROLES:
            raise ValueError("Invalid role")
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            if session.scalar(select(User).where(User.username == username)):
                raise ValueError("Username already exists")
            user = User(
                username=username,
                password_hash=self._hasher.hash(password),
                role=role,
                active=True,
                created_at=now,
                updated_at=now,
            )
            session.add(user)
        return user

    def set_active(self, username: str, active: bool) -> User:
        with self._sessions.begin() as session:
            user = session.scalar(select(User).where(User.username == username))
            if not user:
                raise ValueError("User not found")
            if not active and user.role == "admin" and user.active:
                active_admins = session.scalar(
                    select(func.count()).select_from(User).where(
                        User.role == "admin", User.active.is_(True)
                    )
                )
                if active_admins == 1:
                    raise ValueError("Cannot disable the last active admin")
            user.active = active
            user.updated_at = datetime.now(UTC)
        return user
