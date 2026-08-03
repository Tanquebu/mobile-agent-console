import uvicorn

from .config import get_settings
from .database import Database
from .logging_config import build_log_config
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
        # Senza questo, uvicorn configura solo i propri logger
        # (`uvicorn`/`uvicorn.error`/`uvicorn.access`): il logger applicativo
        # `mobile_agent_console` usato in app/main.py resterebbe a WARNING
        # senza alcun handler, scartando ogni `logger.info(...)` in modo
        # silenzioso (TEST-BH-03/IMP-BH-03-R1).
        log_config=build_log_config(),
    )


if __name__ == "__main__":
    main()
