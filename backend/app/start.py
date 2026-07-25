import uvicorn

from .config import get_settings
from .database import Database
from .services.user_service import UserService


def main() -> None:
    settings = get_settings()
    database = Database(settings.database_path)
    database.migrate()
    if settings.database_auth_enabled:
        users = UserService(database.engine)
        if not users.has_users():
            users.bootstrap_admin(settings.bootstrap_username, settings.resolved_login_password)
    database.dispose()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
    )


if __name__ == "__main__":
    main()
