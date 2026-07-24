import asyncio
import logging
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings, get_settings
from .schemas import (
    Accepted,
    AttachmentView,
    ConfigView,
    CreateSessionInput,
    KeyInput,
    LoginInput,
    LoginResult,
    OutputView,
    SessionList,
    SessionView,
    TextInput,
)
from .security import COOKIE_NAME, SessionSecurity
from .services.attachment_service import AttachmentError, AttachmentService
from .services.tmux_service import SessionNotFound, TmuxError, TmuxGateway, TmuxService

logger = logging.getLogger("mobile_agent_console")


def create_app(settings: Settings | None = None, tmux: TmuxGateway | None = None) -> FastAPI:
    settings = settings or get_settings()
    gateway = tmux or TmuxService(
        settings.tmux_socket,
        socket_path=settings.tmux_socket_path,
        socket_file=settings.tmux_socket_file if settings.tmux_mode == "host" else None,
        external_server=settings.tmux_mode == "host",
    )
    security = SessionSecurity(settings)
    attachments = AttachmentService(
        settings.attachments_root,
        settings.resolved_attachments_prompt_root,
        settings.max_attachment_bytes,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.tmux_mode == "host":
            socket_file = Path(settings.tmux_socket_file or "")
            if not socket_file.exists() or not stat.S_ISSOCK(socket_file.stat().st_mode):
                logger.warning("Host tmux socket %s is missing or not a socket", socket_file)
            error = await gateway.check_server()
            if error:
                logger.warning("Host tmux server unavailable: %s", error)
        yield

    app = FastAPI(title="Mobile Agent Console", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        result = {"status": "ok"}
        if settings.tmux_mode == "host":
            error = await gateway.check_server()
            result["tmux"] = error or "ok"
        return result

    @app.post("/api/v1/auth/login", response_model=LoginResult)
    async def login(payload: LoginInput, response: Response) -> LoginResult:
        if not security.authenticate_password(payload.password):
            raise HTTPException(401, "Invalid credentials")
        cookie, csrf = security.issue_session()
        response.set_cookie(
            COOKIE_NAME,
            cookie,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=settings.session_ttl_seconds,
            path="/",
        )
        return LoginResult(csrf_token=csrf)

    @app.post(
        "/api/v1/auth/logout",
        status_code=204,
        dependencies=[Depends(security.require_csrf)],
    )
    async def logout(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/")

    @app.get("/api/v1/auth/session", response_model=LoginResult)
    async def current_session(
        cookie: str = Depends(security.require_session),
    ) -> LoginResult:
        return LoginResult(csrf_token=security.csrf_for(cookie))

    @app.get(
        "/api/v1/config",
        response_model=ConfigView,
        dependencies=[Depends(security.require_session)],
    )
    async def client_config() -> ConfigView:
        return ConfigView(
            allowed_roots=settings.allowed_roots,
            workspace_presets=settings.workspace_presets,
        )

    @app.post(
        "/api/v1/sessions",
        response_model=Accepted,
        status_code=201,
        dependencies=[Depends(security.require_csrf)],
    )
    async def create_session(payload: CreateSessionInput) -> Accepted:
        directory = Path(payload.directory).resolve()
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        if not any(directory == root or root in directory.parents for root in roots):
            raise HTTPException(400, "Directory is not allowed")
        try:
            await gateway.create_session(payload.name, str(directory), "bash")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except TmuxError as exc:
            raise HTTPException(409, "Unable to create session") from exc
        return Accepted()

    @app.get(
        "/api/v1/sessions",
        response_model=SessionList,
        dependencies=[Depends(security.require_session)],
    )
    async def sessions() -> SessionList:
        try:
            items = await gateway.list_sessions()
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        return SessionList(sessions=[SessionView(**item.__dict__) for item in items])

    @app.get(
        "/api/v1/sessions/{session_id}/output",
        response_model=OutputView,
        dependencies=[Depends(security.require_session)],
    )
    async def output(
        session_id: str, lines: Annotated[int, Query(ge=1, le=2000)] = 500
    ) -> OutputView:
        try:
            content = await gateway.capture_output(session_id, lines)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return OutputView(session_id=session_id, content=content, captured_at=datetime.now(UTC))

    @app.post(
        "/api/v1/sessions/{session_id}/attachments",
        response_model=AttachmentView,
        status_code=201,
        dependencies=[Depends(security.require_csrf)],
    )
    async def upload_attachment(
        session_id: str,
        request: Request,
        filename: Annotated[str, Query(min_length=1, max_length=255)],
    ) -> AttachmentView:
        try:
            await gateway.capture_output(session_id, 1)
            content_length = request.headers.get("content-length")
            if content_length and int(content_length) > settings.max_attachment_bytes:
                raise AttachmentError("Attachment is too large")
            content = bytearray()
            async for chunk in request.stream():
                content.extend(chunk)
                if len(content) > settings.max_attachment_bytes:
                    raise AttachmentError("Attachment is too large")
            attachment = attachments.create(
                session_id,
                filename,
                request.headers.get("content-type", "application/octet-stream"),
                bytes(content),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return AttachmentView(
            id=attachment.id,
            name=attachment.name,
            media_type=attachment.media_type,
            size=attachment.size,
            path=attachment.path,
        )

    @app.post(
        "/api/v1/sessions/{session_id}/input",
        response_model=Accepted,
        status_code=202,
        dependencies=[Depends(security.require_csrf)],
    )
    async def send_input(session_id: str, payload: TextInput) -> Accepted:
        try:
            text = payload.text + attachments.prompt_suffix(session_id, payload.attachment_ids)
            if len(text) > 65536:
                raise AttachmentError("Prompt with attachment references is too large")
            await gateway.send_text(session_id, text)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Accepted()

    @app.post(
        "/api/v1/sessions/{session_id}/keys",
        response_model=Accepted,
        status_code=202,
        dependencies=[Depends(security.require_csrf)],
    )
    async def send_key(session_id: str, payload: KeyInput) -> Accepted:
        try:
            await gateway.send_key(session_id, payload.key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Accepted()

    @app.websocket("/api/v1/ws/sessions/{session_id}")
    async def stream(websocket: WebSocket, session_id: str) -> None:
        cookie = websocket.cookies.get(COOKIE_NAME)
        try:
            security.validate_session(cookie)
        except HTTPException:
            cookie = None
        origin = websocket.headers.get("origin", "")
        host = websocket.headers.get("host", "")
        same_origin = origin in {f"http://{host}", f"https://{host}"}
        if not cookie or (origin not in settings.cors_origins and not same_origin):
            await websocket.close(code=4401)
            return
        await websocket.accept()
        sequence = 0
        previous: str | None = None
        idle_cycles = 0
        try:
            while True:
                try:
                    content = await gateway.capture_output(session_id, 500)
                except (SessionNotFound, ValueError):
                    sequence += 1
                    await websocket.send_json(
                        {
                            "type": "session_closed",
                            "session_id": session_id,
                            "sequence_id": sequence,
                            "timestamp": datetime.now(UTC).isoformat(),
                        }
                    )
                    return
                if content != previous:
                    sequence += 1
                    idle_cycles = 0
                    previous = content
                    await websocket.send_json(
                        {
                            "type": "snapshot",
                            "session_id": session_id,
                            "sequence_id": sequence,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "content": content,
                        }
                    )
                else:
                    idle_cycles += 1
                await asyncio.sleep(0.5 if idle_cycles < 10 else 1.0 if idle_cycles < 30 else 2.0)
        except WebSocketDisconnect:
            return

    return app


app = create_app()
