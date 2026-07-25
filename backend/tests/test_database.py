from pathlib import Path

from sqlalchemy import inspect

from app.database import Database


def test_database_migrates_to_head_and_is_reentrant(tmp_path: Path) -> None:
    database_path = tmp_path / "private" / "app.db"
    database = Database(str(database_path))
    database.migrate("/app/alembic.ini")
    database.migrate("/app/alembic.ini")
    database.check()

    assert database_path.is_file()
    assert database_path.stat().st_mode & 0o777 == 0o600
    assert database_path.parent.stat().st_mode & 0o777 == 0o700
    tables = set(inspect(database.engine).get_table_names())
    assert tables == {"alembic_version", "app_metadata"}
    database.dispose()
