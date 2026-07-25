import asyncio
import logging
import os
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
from fastapi.responses import FileResponse

from .config import Settings, get_settings
from .schemas import (
    Accepted,
    AttachmentView,
    ConfigView,
    ConfirmedAction,
    CreateSessionInput,
    CreateSnapshotInput,
    DirectoryEntryView,
    DirectoryView,
    FileView,
    KeyInput,
    LoginInput,
    LoginResult,
    OutputView,
    RenameSessionInput,
    RestoreItemView,
    RestoreResult,
    SessionList,
    SessionView,
    SnapshotList,
    SnapshotSessionView,
    SnapshotView,
    TextInput,
)
from .security import COOKIE_NAME, SessionSecurity
from .services.attachment_service import AttachmentError, AttachmentService
from .services.snapshot_service import (
    SnapshotError,
    SnapshotService,
    SnapshotSession,
)
from .services.tmux_service import SessionNotFound, TmuxError, TmuxGateway, TmuxService

logger = logging.getLogger("mobile_agent_console")

DIRECTORY_ENTRY_LIMIT = 2000
FILE_PREVIEW_MAX_BYTES = 256 * 1024
DOWNLOADABLE_EXTENSIONS = {
    ".bmp",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
SNAPSHOT_RESUME_COMMANDS = {
    "codex": "codex resume",
    "claude": "claude --resume",
}


def _tmux_mutation_error(exc: TmuxError, fallback: str) -> str:
    if "duplicate session" in str(exc).lower():
        return "Session name already exists"
    return fallback


def _resolve_within_allowed_roots(raw_path: str, roots: list[Path]) -> tuple[Path, Path]:
    directory = Path(raw_path).resolve()
    for root in roots:
        if directory == root or root in directory.parents:
            return directory, root
    raise HTTPException(400, "Directory is not allowed")


def _list_directory(directory: Path) -> tuple[list[DirectoryEntryView], bool]:
    with os.scandir(directory) as iterator:
        raw_entries = sorted(
            iterator, key=lambda item: (not item.is_dir(follow_symlinks=False), item.name.lower())
        )
    truncated = len(raw_entries) > DIRECTORY_ENTRY_LIMIT
    entries = []
    for item in raw_entries[:DIRECTORY_ENTRY_LIMIT]:
        info = item.stat(follow_symlinks=False)
        if item.is_dir(follow_symlinks=False):
            kind = "dir"
        elif item.is_file(follow_symlinks=False):
            kind = "file"
        else:
            kind = "other"
        # st_birthtime esiste solo su alcuni filesystem/piattaforme; senza,
        # usiamo il ctime (ultima modifica dei metadati) come approssimazione.
        created = getattr(info, "st_birthtime", None) or info.st_ctime
        entries.append(
            DirectoryEntryView(
                name=item.name,
                type=kind,
                size=info.st_size if kind == "file" else None,
                created_at=datetime.fromtimestamp(created, tz=UTC),
            )
        )
    return entries, truncated


def _read_text_file(file_path: Path) -> tuple[str, int, bool]:
    size = file_path.stat().st_size
    with file_path.open("rb") as handle:
        raw = handle.read(FILE_PREVIEW_MAX_BYTES + 1)
    truncated = len(raw) > FILE_PREVIEW_MAX_BYTES
    raw = raw[:FILE_PREVIEW_MAX_BYTES]
    if b"\x00" in raw:
        raise ValueError("Binary file, no preview available")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        # Il limite può cadere nel mezzo dell'ultimo carattere UTF-8. In quel
        # solo caso mostriamo la parte completa; errori precedenti indicano
        # invece contenuto non UTF-8.
        if not truncated or exc.end != len(raw):
            raise ValueError("Binary file, no preview available") from exc
        try:
            text = raw[: exc.start].decode("utf-8")
        except UnicodeDecodeError as nested_exc:
            raise ValueError("Binary file, no preview available") from nested_exc
    return text, size, truncated


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
    snapshots = SnapshotService(settings.snapshots_root)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if settings.tmux_mode == "host":
            socket_file = Path(settings.tmux_socket_file or "")
            if not socket_file.exists() or not stat.S_ISSOCK(socket_file.stat().st_mode):
                logger.warning("Host tmux socket %s is missing or not a socket", socket_file)
            error = await gateway.check_server()
            if error:
                logger.warning("Host tmux server unavailable: %s", error)
        cleanup_interval = min(3600, max(60, settings.attachment_ttl_seconds // 4))

        async def cleanup_attachments() -> None:
            while True:
                try:
                    removed = await asyncio.to_thread(
                        attachments.cleanup_expired,
                        settings.attachment_ttl_seconds,
                    )
                    if removed:
                        logger.info("Removed %d expired attachment files", removed)
                except Exception:
                    logger.exception("Unable to clean up expired attachments")
                await asyncio.sleep(cleanup_interval)

        cleanup_task = asyncio.create_task(cleanup_attachments())
        try:
            yield
        finally:
            cleanup_task.cancel()
            try:
                await cleanup_task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="Mobile Agent Console", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["DELETE", "GET", "POST"],
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
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        directory, _ = _resolve_within_allowed_roots(payload.directory, roots)
        try:
            await gateway.create_session(payload.name, str(directory), "bash")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except TmuxError as exc:
            detail = _tmux_mutation_error(exc, "Unable to create session")
            raise HTTPException(409, detail) from exc
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
        "/api/v1/snapshots",
        response_model=SnapshotList,
        dependencies=[Depends(security.require_session)],
    )
    async def list_snapshots() -> SnapshotList:
        items = await asyncio.to_thread(snapshots.list)
        return SnapshotList(
            snapshots=[
                SnapshotView(
                    id=item.id,
                    name=item.name,
                    created_at=item.created_at,
                    sessions=[
                        SnapshotSessionView(**session.__dict__)
                        for session in item.sessions
                    ],
                )
                for item in items
            ]
        )

    @app.post(
        "/api/v1/snapshots",
        response_model=SnapshotView,
        status_code=201,
        dependencies=[Depends(security.require_csrf)],
    )
    async def create_snapshot(payload: CreateSnapshotInput) -> SnapshotView:
        try:
            live_sessions = {item.id: item for item in await gateway.list_sessions()}
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        captured = []
        for selection in payload.sessions:
            live = live_sessions.get(selection.session_id)
            if live is None:
                raise HTTPException(404, f"Session {selection.session_id} not found")
            try:
                raw_directory = await gateway.pane_path(selection.session_id)
                directory, _ = _resolve_within_allowed_roots(raw_directory, roots)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except SessionNotFound as exc:
                raise HTTPException(404, "Session not found") from exc
            captured.append(
                SnapshotSession(
                    name=live.name,
                    directory=str(directory),
                    mode=selection.mode,
                    observed_command=live.current_command,
                )
            )
        try:
            item = await asyncio.to_thread(snapshots.create, payload.name, captured)
        except SnapshotError as exc:
            raise HTTPException(400, str(exc)) from exc
        return SnapshotView(
            id=item.id,
            name=item.name,
            created_at=item.created_at,
            sessions=[SnapshotSessionView(**session.__dict__) for session in item.sessions],
        )

    @app.post(
        "/api/v1/snapshots/{snapshot_id}/restore",
        response_model=RestoreResult,
        dependencies=[Depends(security.require_csrf)],
    )
    async def restore_snapshot(
        snapshot_id: str,
        payload: ConfirmedAction,
    ) -> RestoreResult:
        if not payload.confirmed:
            raise HTTPException(400, "Snapshot restore requires explicit confirmation")
        try:
            snapshot = await asyncio.to_thread(snapshots.get, snapshot_id)
        except SnapshotError as exc:
            raise HTTPException(404, str(exc)) from exc
        try:
            live_sessions = await gateway.list_sessions()
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        existing_names = {item.name for item in live_sessions}
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        results = []
        for saved in snapshot.sessions:
            if saved.name in existing_names:
                results.append(
                    RestoreItemView(
                        name=saved.name,
                        status="skipped",
                        detail="A session with this name already exists",
                    )
                )
                continue
            try:
                TmuxService.validate_session_id(saved.name)
                directory, _ = _resolve_within_allowed_roots(saved.directory, roots)
                await gateway.create_session(saved.name, str(directory), "bash")
                existing_names.add(saved.name)
                if saved.mode in SNAPSHOT_RESUME_COMMANDS:
                    created = next(
                        (item for item in await gateway.list_sessions() if item.name == saved.name),
                        None,
                    )
                    if created is None:
                        raise TmuxError("Created session is not visible")
                    await gateway.send_text(created.id, SNAPSHOT_RESUME_COMMANDS[saved.mode])
                    await gateway.send_key(created.id, "Enter")
                    status = "restored"
                    detail = f"Shell restored; {saved.mode} resume picker launched"
                elif saved.mode == "manual":
                    status = "manual"
                    detail = "Shell restored; command must be relaunched manually"
                else:
                    status = "restored"
                    detail = "Shell restored"
            except (ValueError, HTTPException):
                status = "error"
                detail = "Saved name or directory is no longer allowed"
            except TmuxError:
                status = "error"
                detail = "tmux could not restore this session"
            results.append(
                RestoreItemView(name=saved.name, status=status, detail=detail)
            )
        return RestoreResult(snapshot_id=snapshot.id, results=results)

    @app.delete(
        "/api/v1/snapshots/{snapshot_id}",
        status_code=204,
        dependencies=[Depends(security.require_csrf)],
    )
    async def delete_snapshot(
        snapshot_id: str,
        payload: ConfirmedAction,
    ) -> Response:
        if not payload.confirmed:
            raise HTTPException(400, "Snapshot deletion requires explicit confirmation")
        try:
            await asyncio.to_thread(snapshots.delete, snapshot_id)
        except SnapshotError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(status_code=204)

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

    @app.get(
        "/api/v1/sessions/{session_id}/directory",
        response_model=DirectoryView,
        dependencies=[Depends(security.require_session)],
    )
    async def session_directory(
        session_id: str, path: Annotated[str | None, Query(min_length=1, max_length=4096)] = None
    ) -> DirectoryView:
        if path is None:
            try:
                raw_path = await gateway.pane_path(session_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            except SessionNotFound as exc:
                raise HTTPException(404, "Session not found") from exc
        else:
            try:
                TmuxService.validate_target(session_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            raw_path = path
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        directory, root = _resolve_within_allowed_roots(raw_path, roots)
        try:
            entries, truncated = await asyncio.to_thread(_list_directory, directory)
        except OSError as exc:
            raise HTTPException(404, "Directory not found") from exc
        return DirectoryView(
            session_id=session_id,
            path=str(directory),
            root=str(root),
            parent=str(directory.parent) if directory != root else None,
            entries=entries,
            truncated=truncated,
        )

    @app.get(
        "/api/v1/sessions/{session_id}/file",
        response_model=FileView,
        dependencies=[Depends(security.require_session)],
    )
    async def session_file(
        session_id: str, path: Annotated[str, Query(min_length=1, max_length=4096)]
    ) -> FileView:
        try:
            TmuxService.validate_target(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        file_path, _ = _resolve_within_allowed_roots(path, roots)
        if not file_path.exists():
            raise HTTPException(404, "File not found")
        if not file_path.is_file():
            raise HTTPException(400, "Not a file")
        try:
            content, size, truncated = await asyncio.to_thread(_read_text_file, file_path)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except OSError as exc:
            raise HTTPException(404, "File not found") from exc
        return FileView(session_id=session_id, path=str(file_path), size=size, content=content, truncated=truncated)

    @app.get(
        "/api/v1/sessions/{session_id}/file/download",
        dependencies=[Depends(security.require_session)],
    )
    async def download_session_file(
        session_id: str,
        path: Annotated[str, Query(min_length=1, max_length=4096)],
    ) -> FileResponse:
        try:
            TmuxService.validate_target(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        file_path, _ = _resolve_within_allowed_roots(path, roots)
        if not file_path.exists():
            raise HTTPException(404, "File not found")
        if not file_path.is_file():
            raise HTTPException(400, "Not a file")
        if file_path.suffix.lower() not in DOWNLOADABLE_EXTENSIONS:
            raise HTTPException(400, "File type is not downloadable")
        return FileResponse(
            file_path,
            filename=file_path.name,
            content_disposition_type="attachment",
        )

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

    @app.delete(
        "/api/v1/sessions/{session_id}/attachments/{attachment_id}",
        status_code=204,
        dependencies=[Depends(security.require_csrf)],
    )
    async def delete_attachment(session_id: str, attachment_id: str) -> Response:
        try:
            attachments.delete(session_id, attachment_id)
        except AttachmentError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(status_code=204)

    @app.post(
        "/api/v1/sessions/{session_id}/keys",
        response_model=Accepted,
        status_code=202,
        dependencies=[Depends(security.require_csrf)],
    )
    async def send_key(session_id: str, payload: KeyInput) -> Accepted:
        if payload.key == "C-c" and not payload.confirmed:
            raise HTTPException(400, "Interrupt requires explicit confirmation")
        try:
            await gateway.send_key(session_id, payload.key)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Accepted()

    @app.delete(
        "/api/v1/sessions/{session_id}",
        status_code=204,
        dependencies=[Depends(security.require_csrf)],
    )
    async def terminate_session(session_id: str, payload: ConfirmedAction) -> Response:
        if not payload.confirmed:
            raise HTTPException(400, "Session termination requires explicit confirmation")
        try:
            await gateway.terminate_session(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Response(status_code=204)

    @app.post(
        "/api/v1/sessions/{session_id}/rename",
        response_model=Accepted,
        dependencies=[Depends(security.require_csrf)],
    )
    async def rename_session(session_id: str, payload: RenameSessionInput) -> Accepted:
        try:
            await gateway.rename_session(session_id, payload.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        except TmuxError as exc:
            detail = _tmux_mutation_error(exc, "Unable to rename session")
            raise HTTPException(409, detail) from exc
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
