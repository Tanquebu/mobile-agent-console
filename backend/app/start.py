import uvicorn

from .config import get_settings
from .database import Database


def main() -> None:
    settings = get_settings()
    database = Database(settings.database_path)
    database.migrate()
    database.dispose()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
