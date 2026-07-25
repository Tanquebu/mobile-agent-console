import os
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, path: str) -> None:
        self.path = Path(path).resolve()
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path}",
            connect_args={"check_same_thread": False},
        )

    def migrate(self, alembic_ini: str = "/app/alembic.ini") -> None:
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = Config(alembic_ini)
        config.set_main_option("sqlalchemy.url", f"sqlite:///{self.path}")
        command.upgrade(config, "head")
        os.chmod(self.path.parent, 0o700)
        os.chmod(self.path, 0o600)

    def check(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self.engine.dispose()
