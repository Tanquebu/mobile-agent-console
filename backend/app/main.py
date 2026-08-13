import asyncio
import hashlib
import logging
import os
import re
import stat
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from .config import Settings, get_settings
from .database import Database
from .schemas import (
    Accepted,
    AgentStatusList,
    AgentStatusView,
    ArchiveDraftView,
    ArchivedSessionView,
    ArchiveList,
    ArchiveSessionInput,
    ArtifactDirectoryView,
    ArtifactView,
    AttachmentView,
    AuditEventView,
    AuditList,
    BackupList,
    BackupView,
    ClaudeHistoryMessageView,
    ClaudeHistoryView,
    ConfigView,
    ConfirmedAction,
    CreateSessionInput,
    CreateSnapshotInput,
    CreateUserInput,
    DirectoryEntryView,
    DirectoryView,
    FileView,
    KeyInput,
    LoginInput,
    LoginResult,
    OutputView,
    PaneList,
    PaneTargetInput,
    PaneView,
    PushPublicKeyView,
    PushSubscriptionInput,
    PushUnsubscribeInput,
    RenameSessionInput,
    ResizePaneInput,
    RestoreItemView,
    RestoreResult,
    SessionList,
    SessionView,
    SessionVisibilityInput,
    SnapshotList,
    SnapshotSessionView,
    SnapshotView,
    TextInput,
    UploadResultView,
    UserList,
    UserStatusInput,
    UserView,
)
from .security import COOKIE_NAME, SessionSecurity
from .services.agent_status_service import AgentStatusService
from .services.archive_service import ArchiveService
from .services.artifact_service import (
    ARCHIVE_SUMMARY_NAME,
    ArtifactError,
    ArtifactService,
    sniff_media_type,
)
from .services.attachment_service import AttachmentError, AttachmentService
from .services.audit_service import AuditService
from .services.backup_service import BackupError, BackupService
from .services.claude_history_service import ClaudeHistoryService
from .services.host_observability_contract import HostObservabilitySnapshot
from .services.host_observability_service import (
    HostObservabilityInvalidResponse,
    HostObservabilityService,
    HostObservabilityTimeout,
    HostObservabilityUnavailable,
)
from .services.host_observability_socket_client import HostObservabilitySocketClient
from .services.orchestrator_state_service import OrchestratorState, OrchestratorStateService
from .services.output_delta import line_delta
from .services.provider_session_state_service import ProviderSessionStateService
from .services.push_service import PushService
from .services.rate_limit import FixedWindowRateLimiter
from .services.rate_limit_fresh_client import (
    RateLimitFreshClient,
    RateLimitFreshResponseError,
    RateLimitFreshResult,
    RateLimitFreshTimeout,
    RateLimitFreshUnavailable,
)
from .services.rate_limit_history_service import RateLimitHistory, RateLimitHistoryService
from .services.rate_limit_status_service import RateLimitStatus, RateLimitStatusService
from .services.session_timeline_service import (
    SessionTimelineInvalidResponse,
    SessionTimelineService,
    SessionTimelineTimeout,
    SessionTimelineUnavailable,
    SessionTimelineWindow,
)
from .services.session_timeline_socket_client import SessionTimelineSocketClient
from .services.session_usage_service import SessionUsageReport, SessionUsageService
from .services.session_visibility_service import SessionVisibilityService
from .services.snapshot_service import (
    SnapshotError,
    SnapshotService,
    SnapshotSession,
)
from .services.tmux_service import SessionNotFound, TmuxError, TmuxGateway, TmuxService
from .services.user_service import UserService

logger = logging.getLogger("mobile_agent_console")


def _optional_feature_flags(settings: Settings) -> dict[str, bool]:
    """Stato acceso/spento delle funzioni opzionali, come fatto enunciato.

    Nessun confronto con un'attesa: un'installazione con tutte le funzioni
    spente è uno stato valido, non un errore (BH-03). Mai includere token o
    percorsi qui, solo nomi di funzione e stato booleano.
    """
    return {
        "host_observability_enabled": settings.host_observability_enabled,
        "session_usage_enabled": settings.session_usage_enabled,
        "session_timeline_enabled": settings.session_timeline_enabled,
        "rate_limit_fresh_enabled": settings.rate_limit_fresh_enabled,
        "claude_history_enabled": settings.claude_history_enabled,
        "database_auth_enabled": settings.database_auth_enabled,
    }


DIRECTORY_ENTRY_LIMIT = 2000
FILE_PREVIEW_MAX_BYTES = 256 * 1024
DOWNLOADABLE_EXTENSIONS = {
    ".bmp",
    ".doc",
    ".docx",
    ".gif",
    ".jpeg",
    ".jpg",
    ".m4a",
    ".mp3",
    ".pdf",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
# Tipi che il browser puo' rendere *dentro* la pagina. Deliberatamente stretta e
# definita per media type dedotto dal contenuto, non per estensione: servire
# text/html o image/svg+xml inline dalla stessa origine sarebbe XSS memorizzato,
# perche' il browser di directory legge da tutta la radice consentita.
INLINE_PREVIEW_MEDIA_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "audio/mp4",
    "video/mp4",
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


def create_app(
    settings: Settings | None = None,
    tmux: TmuxGateway | None = None,
    host_observability_client: HostObservabilitySocketClient | None = None,
    rate_limit_fresh_client: RateLimitFreshClient | None = None,
    session_timeline_client: SessionTimelineSocketClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    gateway = tmux or TmuxService(
        settings.tmux_socket,
        socket_path=settings.tmux_socket_path,
        socket_file=settings.tmux_socket_file if settings.tmux_mode == "host" else None,
        external_server=settings.tmux_mode == "host",
        reserved_host_session=(
            settings.tmux_host_keepalive_session if settings.tmux_mode == "host" else None
        ),
    )
    security = SessionSecurity(settings)
    snapshots = SnapshotService(settings.snapshots_root)
    backups = BackupService(
        settings.backups_root,
        settings.database_path,
        settings.snapshots_root,
        settings.backup_retention,
    )
    rate_limiter = FixedWindowRateLimiter()
    provider_rate_limits = RateLimitStatusService(settings.provider_rate_limits_path)
    provider_rate_limits_history = RateLimitHistoryService(
        settings.provider_rate_limits_history_path
    )
    session_usage = SessionUsageService(settings.session_usage_path)
    session_timeline = SessionTimelineService(
        session_timeline_client
        or SessionTimelineSocketClient(
            settings.session_timeline_socket_file,
            timeout_seconds=settings.session_timeline_socket_timeout_seconds,
            max_response_bytes=settings.session_timeline_max_response_bytes,
        )
    )
    rate_limit_fresh = rate_limit_fresh_client or RateLimitFreshClient(
        settings.rate_limit_fresh_socket_file,
        timeout_seconds=settings.rate_limit_fresh_timeout_seconds,
        max_response_bytes=settings.rate_limit_fresh_max_response_bytes,
    )
    host_observability = HostObservabilityService(
        host_observability_client
        or HostObservabilitySocketClient(
            settings.host_observability_socket_file,
            timeout_seconds=settings.host_observability_socket_timeout_seconds,
            max_response_bytes=settings.host_observability_max_response_bytes,
        )
    )
    provider_session_states = ProviderSessionStateService(
        settings.provider_session_states_path
    )
    orchestrator_state = OrchestratorStateService(settings.orchestrator_state_path)
    claude_history = ClaudeHistoryService(
        settings.claude_history_path,
        settings.claude_history_max_age_seconds,
    )
    agent_statuses = AgentStatusService(settings.agent_active_window_seconds)
    database = Database(settings.database_path) if settings.database_auth_enabled else None
    users = UserService(database.engine) if database else None
    archives = ArchiveService(database.engine) if database else None
    session_visibility = SessionVisibilityService(database.engine) if database else None
    audit = AuditService(database.engine) if database else None
    attachments = (
        AttachmentService(
            database.engine,
            settings.attachments_root,
            settings.resolved_attachments_prompt_root,
            settings.max_attachment_bytes,
            settings.max_attachment_bytes_per_session,
        )
        if database
        else None
    )
    artifacts = ArtifactService(
        settings.artifacts_root,
        settings.resolved_artifacts_prompt_root,
        settings.max_artifact_bytes,
    )
    push = (
        PushService(database.engine, settings.push_vapid_key_path, settings.push_contact_email)
        if database
        else None
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Lo stato effettivo va dichiarato, non dedotto (BH-03): un'enunciazione
        # di fatto, mai un confronto con un'attesa né un livello di allarme.
        flags = _optional_feature_flags(settings)
        logger.info(
            "Funzioni opzionali: %s",
            ", ".join(f"{name}={'on' if enabled else 'off'}" for name, enabled in flags.items()),
        )
        if settings.tmux_mode == "host":
            socket_file = Path(settings.tmux_socket_file or "")
            if not socket_file.exists() or not stat.S_ISSOCK(socket_file.stat().st_mode):
                logger.warning("Host tmux socket %s is missing or not a socket", socket_file)
            error = await gateway.check_server()
            if error:
                logger.warning("Host tmux server unavailable: %s", error)
        cleanup_interval = min(3600, max(60, settings.attachment_ttl_seconds // 4))

        async def cleanup_attachments() -> None:
            if attachments is None:
                return
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

        async def poll_agent_attention_for_push() -> None:
            if push is None:
                return
            previous_states: dict[str, str] = {}
            while True:
                try:
                    sessions = await gateway.list_sessions()
                    agent_sessions = [
                        item
                        for item in sessions
                        if agent_statuses.provider_for(item.current_command) is not None
                    ]
                    contents = await asyncio.gather(
                        *(gateway.capture_output(item.id, 80) for item in agent_sessions),
                        return_exceptions=True,
                    )
                    current_states: dict[str, str] = {}
                    for item, content in zip(agent_sessions, contents, strict=True):
                        if isinstance(content, BaseException):
                            continue
                        status = agent_statuses.classify(item.id, item.current_command, content)
                        if status is None:
                            continue
                        current_states[item.id] = status.state
                        previous_state = previous_states.get(item.id)
                        if (
                            previous_state is not None
                            and previous_state != status.state
                            and status.state in {"waiting_input", "waiting_authorization"}
                        ):
                            verb = (
                                "un'autorizzazione"
                                if status.state == "waiting_authorization"
                                else "un feedback"
                            )
                            await asyncio.to_thread(
                                push.notify,
                                "Mobile Agent Console",
                                f"“{item.name}” attende {verb}",
                                f"session-{item.id}",
                            )
                    previous_states = current_states
                except Exception:
                    logger.exception("Unable to poll agent statuses for push notifications")
                await asyncio.sleep(settings.push_poll_interval_seconds)

        cleanup_task = asyncio.create_task(cleanup_attachments())
        push_poll_task = asyncio.create_task(poll_agent_attention_for_push())
        try:
            yield
        finally:
            cleanup_task.cancel()
            push_poll_task.cancel()
            for task in (cleanup_task, push_poll_task):
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            if database:
                database.dispose()

    app = FastAPI(title="Mobile Agent Console", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["DELETE", "GET", "POST"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
    )

    def active_user(cookie: str) -> object | None:
        if not users:
            return None
        subject = security.subject_for(cookie) or settings.bootstrap_username
        user = users.get(subject)
        if not user or not user.active:
            raise HTTPException(401, "Invalid session")
        return user

    def require_active_session(
        mac_session: str | None = Cookie(default=None),
    ) -> str:
        cookie = security.validate_session(mac_session)
        active_user(cookie)
        return cookie

    def require_active_csrf(
        mac_session: str | None = Cookie(default=None),
        csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> str:
        cookie = security.require_csrf(mac_session, csrf)
        active_user(cookie)
        return cookie

    def require_operator(
        cookie: str = Depends(require_active_csrf),
    ) -> str:
        user = active_user(cookie)
        if user is not None and user.role not in {"admin", "operator"}:
            raise HTTPException(403, "Operator role required")
        return cookie

    def require_admin(
        cookie: str = Depends(require_active_csrf),
    ) -> str:
        user = active_user(cookie)
        if user is not None and user.role != "admin":
            raise HTTPException(403, "Admin role required")
        return cookie

    def require_admin_session(
        cookie: str = Depends(require_active_session),
    ) -> str:
        user = active_user(cookie)
        if user is not None and user.role != "admin":
            raise HTTPException(403, "Admin role required")
        return cookie

    def client_key(request: Request) -> str:
        cookie = request.cookies.get(COOKIE_NAME)
        if cookie:
            return "session:" + hashlib.sha256(cookie.encode()).hexdigest()
        return "ip:" + (request.client.host if request.client else "unknown")

    def attachment_service() -> AttachmentService:
        if not attachments:
            raise HTTPException(503, "Attachments require the metadata database")
        return attachments

    def push_service() -> PushService:
        if not push:
            raise HTTPException(503, "Web Push requires the metadata database")
        return push

    async def _cleanup_session_files(session_id: str) -> None:
        # Best-effort: terminare/archiviare la sessione non deve fallire per un
        # problema di pulizia di allegati/artefatti, che gli allegati restano
        # comunque soggetti al TTL.
        if attachments is not None:
            try:
                await asyncio.to_thread(attachments.delete_all_for_session, session_id)
            except Exception:
                logger.exception("Unable to clean up attachments for session %s", session_id)
        try:
            await asyncio.to_thread(artifacts.delete_all_for_session, session_id)
        except Exception:
            logger.exception("Unable to clean up artifacts for session %s", session_id)

    async def _prepare_artifacts_folder(session_name: str) -> None:
        # Best-effort: la creazione della sessione non deve fallire se non è
        # possibile predisporre la cartella di consegna. L'istruzione viene
        # inviata solo su azione esplicita, per non disturbare l'onboarding dei CLI.
        try:
            items = await gateway.list_sessions()
            created = next((item for item in items if item.name == session_name), None)
            if created is None:
                return
            await asyncio.to_thread(artifacts.ensure_session_dir, created.id)
        except Exception:
            logger.exception("Unable to prepare artifacts folder for session %s", session_name)

    def archive_service() -> ArchiveService:
        if not archives:
            raise HTTPException(503, "Archive requires the metadata database")
        return archives

    def session_visibility_service() -> SessionVisibilityService:
        if not session_visibility:
            raise HTTPException(503, "Session visibility requires the metadata database")
        return session_visibility

    def session_profile(command: str) -> str:
        lowered = command.lower()
        if "codex" in lowered:
            return "codex"
        if "claude" in lowered:
            return "claude"
        if "agy" in lowered or "antigravity" in lowered:
            return "antigravity"
        # `pane_current_command` == "opencode", senza wrapper che ne mascheri
        # il nome — verificato nello spike host TUI (IMP-OC-00).
        if "opencode" in lowered:
            return "opencode"
        return "shell"

    def audit_actor(request: Request) -> str:
        cookie = request.cookies.get(COOKIE_NAME)
        if not cookie:
            return "anonymous"
        try:
            return security.subject_for(cookie) or settings.bootstrap_username
        except HTTPException:
            return "anonymous"

    async def record_audit(
        actor: str,
        action: str,
        target: str,
        outcome: int,
    ) -> None:
        if not audit:
            return
        try:
            await asyncio.to_thread(audit.record, actor, action, target, outcome)
        except Exception:
            logger.exception("Unable to persist audit event")

    @app.middleware("http")
    async def limit_mutations(request: Request, call_next):
        if request.method in {"POST", "DELETE"} and request.url.path != "/api/v1/auth/login":
            retry_after = rate_limiter.check(
                f"mutation:{client_key(request)}",
                settings.mutation_rate_limit,
                settings.mutation_rate_window_seconds,
            )
            if retry_after is not None:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                    headers={"Retry-After": str(retry_after)},
                )
        return await call_next(request)

    @app.middleware("http")
    async def audit_mutations(request: Request, call_next):
        response = await call_next(request)
        if request.method in {"POST", "DELETE"} and request.url.path != "/api/v1/auth/login":
            route = request.scope.get("route")
            route_path = getattr(route, "path", request.url.path)
            if not route_path.endswith(("/input", "/keys", "/resize")):
                await record_audit(
                    audit_actor(request),
                    f"{request.method} {route_path}",
                    request.url.path,
                    response.status_code,
                )
        return response

    @app.get("/health")
    async def health() -> dict[str, str]:
        result = {"status": "ok"}
        if settings.tmux_mode == "host":
            error = await gateway.check_server()
            result["tmux"] = error or "ok"
        return result

    @app.post("/api/v1/auth/login", response_model=LoginResult)
    async def login(payload: LoginInput, request: Request, response: Response) -> LoginResult:
        retry_after = rate_limiter.check(
            f"login:{client_key(request)}",
            settings.login_rate_limit,
            settings.login_rate_window_seconds,
        )
        if retry_after is not None:
            await record_audit(payload.username, "LOGIN", "/api/v1/auth/login", 429)
            raise HTTPException(
                429,
                "Too many login attempts",
                headers={"Retry-After": str(retry_after)},
            )
        if users:
            user = await asyncio.to_thread(users.authenticate, payload.username, payload.password)
            authenticated = user is not None
        else:
            authenticated = security.authenticate_password(payload.password)
        if not authenticated:
            await record_audit(payload.username, "LOGIN", "/api/v1/auth/login", 401)
            raise HTTPException(401, "Invalid credentials")
        cookie, csrf = security.issue_session(payload.username if users else "legacy")
        response.set_cookie(
            COOKIE_NAME,
            cookie,
            httponly=True,
            secure=settings.cookie_secure,
            samesite="strict",
            max_age=settings.session_ttl_seconds,
            path="/",
        )
        await record_audit(payload.username, "LOGIN", "/api/v1/auth/login", 200)
        return LoginResult(
            csrf_token=csrf,
            username=user.username if users and user else "legacy",
            role=user.role if users and user else "admin",
        )

    @app.post(
        "/api/v1/auth/logout",
        status_code=204,
        dependencies=[Depends(require_active_csrf)],
    )
    async def logout(response: Response) -> None:
        response.delete_cookie(COOKIE_NAME, path="/")

    @app.get("/api/v1/auth/session", response_model=LoginResult)
    async def current_session(
        cookie: str = Depends(require_active_session),
    ) -> LoginResult:
        user = active_user(cookie)
        return LoginResult(
            csrf_token=security.csrf_for(cookie),
            username=user.username if user else "legacy",
            role=user.role if user else "admin",
        )

    @app.get(
        "/api/v1/users",
        response_model=UserList,
        dependencies=[Depends(require_admin_session)],
    )
    async def list_users() -> UserList:
        if not users:
            return UserList(users=[])
        items = await asyncio.to_thread(users.list)
        return UserList(
            users=[
                UserView(
                    username=item.username,
                    role=item.role,
                    active=item.active,
                    created_at=item.created_at,
                )
                for item in items
            ]
        )

    @app.get(
        "/api/v1/audit",
        response_model=AuditList,
        dependencies=[Depends(require_admin_session)],
    )
    async def list_audit(limit: int = Query(default=200, ge=1, le=500)) -> AuditList:
        if not audit:
            return AuditList(events=[])
        items = await asyncio.to_thread(audit.list, limit)
        return AuditList(
            events=[
                AuditEventView.model_validate(item, from_attributes=True)
                for item in items
            ]
        )

    @app.get(
        "/api/v1/backups",
        response_model=BackupList,
        dependencies=[Depends(require_admin_session)],
    )
    async def list_backups() -> BackupList:
        items = await asyncio.to_thread(backups.list)
        return BackupList(
            backups=[BackupView(**item.__dict__) for item in items]
        )

    @app.post(
        "/api/v1/backups",
        response_model=BackupView,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    async def create_backup() -> BackupView:
        if not database:
            raise HTTPException(503, "Backup requires the metadata database")
        try:
            item = await asyncio.to_thread(backups.create)
        except BackupError as exc:
            raise HTTPException(500, str(exc)) from exc
        return BackupView(**item.__dict__)

    @app.get(
        "/api/v1/backups/{backup_id}/download",
        dependencies=[Depends(require_admin_session)],
    )
    async def download_backup(backup_id: str) -> FileResponse:
        try:
            path = await asyncio.to_thread(backups.archive_path, backup_id)
        except BackupError as exc:
            status_code = 404 if str(exc) == "Backup not found" else 409
            raise HTTPException(status_code, str(exc)) from exc
        return FileResponse(
            path,
            media_type="application/zip",
            filename=f"mobile-agent-console-{backup_id}.zip",
        )

    @app.delete(
        "/api/v1/backups/{backup_id}",
        status_code=204,
        dependencies=[Depends(require_admin)],
    )
    async def delete_backup(backup_id: str, payload: ConfirmedAction) -> None:
        if not payload.confirmed:
            raise HTTPException(400, "Backup deletion requires explicit confirmation")
        try:
            await asyncio.to_thread(backups.delete, backup_id)
        except BackupError as exc:
            raise HTTPException(404, str(exc)) from exc

    @app.post(
        "/api/v1/users",
        response_model=UserView,
        status_code=201,
        dependencies=[Depends(require_admin)],
    )
    async def create_user(payload: CreateUserInput) -> UserView:
        if not users:
            raise HTTPException(409, "Database authentication is disabled")
        try:
            item = await asyncio.to_thread(
                users.create, payload.username, payload.password, payload.role
            )
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return UserView(
            username=item.username,
            role=item.role,
            active=item.active,
            created_at=item.created_at,
        )

    @app.post(
        "/api/v1/users/{username}/status",
        response_model=UserView,
        dependencies=[Depends(require_admin)],
    )
    async def set_user_status(username: str, payload: UserStatusInput) -> UserView:
        if not users:
            raise HTTPException(409, "Database authentication is disabled")
        try:
            item = await asyncio.to_thread(users.set_active, username, payload.active)
        except ValueError as exc:
            status_code = 404 if str(exc) == "User not found" else 409
            raise HTTPException(status_code, str(exc)) from exc
        return UserView(
            username=item.username,
            role=item.role,
            active=item.active,
            created_at=item.created_at,
        )

    @app.get(
        "/api/v1/config",
        response_model=ConfigView,
    )
    async def client_config(
        cookie: str = Depends(require_active_session),
    ) -> ConfigView:
        # L'endpoint Host è admin-only: non suggerire la futura UI agli altri ruoli.
        # In modalità legacy l'unico utente autenticato equivale all'admin.
        user = active_user(cookie)
        return ConfigView(
            allowed_roots=settings.allowed_roots,
            workspace_presets=settings.workspace_presets,
            max_upload_bytes=settings.max_upload_bytes,
            upload_allowed_extensions=settings.upload_allowed_extensions,
            claude_history_enabled=settings.claude_history_enabled,
            host_observability_enabled=settings.host_observability_enabled
            and (user is None or user.role == "admin"),
            rate_limit_fresh_enabled=settings.rate_limit_fresh_enabled
            and (user is None or user.role == "admin"),
            session_usage_enabled=settings.session_usage_enabled,
            session_timeline_enabled=settings.session_timeline_enabled
            and (user is None or user.role == "admin"),
            optional_features=(
                _optional_feature_flags(settings)
                if user is None or user.role == "admin"
                else None
            ),
        )

    @app.get(
        "/api/v1/host-observability",
        response_model=HostObservabilitySnapshot,
    )
    async def get_host_observability(
        request: Request,
        _cookie: str = Depends(require_admin_session),
    ) -> HostObservabilitySnapshot | JSONResponse:
        if not settings.host_observability_enabled:
            raise HTTPException(404, "Not Found")
        retry_after = rate_limiter.check(
            f"host-observability:{client_key(request)}",
            settings.host_observability_rate_limit,
            settings.host_observability_rate_window_seconds,
        )
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "host_observability_rate_limited",
                    "detail": "Too many host observability requests",
                },
                headers={"Retry-After": str(retry_after)},
            )
        try:
            return await host_observability.read()
        except HostObservabilityTimeout:
            return JSONResponse(
                status_code=504,
                content={
                    "code": "host_observability_timeout",
                    "detail": "Host observability collector timed out",
                },
            )
        except HostObservabilityUnavailable:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "host_observability_unavailable",
                    "detail": "Host observability collector unavailable",
                },
            )
        except HostObservabilityInvalidResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "host_observability_invalid_response",
                    "detail": "Host observability collector returned an invalid response",
                },
            )

    @app.get(
        "/api/v1/provider-rate-limits",
        response_model=RateLimitStatus | None,
        dependencies=[Depends(require_active_session)],
    )
    async def get_provider_rate_limits() -> RateLimitStatus | None:
        return await asyncio.to_thread(provider_rate_limits.read)

    @app.get(
        "/api/v1/provider-rate-limits/history",
        response_model=RateLimitHistory,
        dependencies=[Depends(require_active_session)],
    )
    async def get_provider_rate_limits_history(
        hours: int = Query(default=24, ge=1, le=settings.rate_limit_history_max_hours),
        limit: int = Query(default=500, ge=1, le=5000),
    ) -> RateLimitHistory:
        return await asyncio.to_thread(provider_rate_limits_history.read, hours, limit)

    @app.get(
        "/api/v1/session-usage",
        response_model=SessionUsageReport,
        dependencies=[Depends(require_active_session)],
    )
    async def get_session_usage(
        hours: int = Query(default=6, ge=1, le=settings.session_usage_max_hours),
        limit: int = Query(default=50, ge=1, le=settings.session_usage_max_limit),
    ) -> SessionUsageReport:
        if not settings.session_usage_enabled:
            raise HTTPException(404, "Not Found")
        return await asyncio.to_thread(session_usage.read, hours, limit)

    @app.get(
        "/api/v1/session-usage/timeline",
        response_model=SessionTimelineWindow,
    )
    async def get_session_timeline(
        request: Request,
        # Tutti e tre obbligatori nello stile `Annotated` senza default: con
        # `Annotated[...] = ...` il sentinella `Ellipsis` finisce nel corpo
        # dell'errore di validazione, `jsonable_encoder` non sa serializzarlo e
        # solleva dentro l'handler di `RequestValidationError`, che degrada a
        # un 500 grezzo. Il parametro assente diventava così l'unico ingresso
        # non tipizzato dell'endpoint (osservato il 03/08/2026 da SA-TEST).
        session_uuid: Annotated[str, Query(pattern=r"^[A-Za-z0-9_-]{1,64}$")],
        provider: Annotated[str, Query(pattern=r"^(claude|codex)$")],
        bucket_start: Annotated[datetime, Query()],
        _cookie: str = Depends(require_admin_session),
    ) -> SessionTimelineWindow | JSONResponse:
        # Drill-down "fase C" (BH-04): admin-only e nascosto ai non-admin come
        # host-observability, mai un pane tmux richiesto (la sessione può
        # essere headless/conclusa). Il percorso del transcript non compare
        # mai in nessuna delle risposte sotto (ADR 010, "il boundary non si
        # allarga").
        if not settings.session_timeline_enabled:
            raise HTTPException(404, "Not Found")
        retry_after = rate_limiter.check(
            f"session-timeline:{client_key(request)}",
            settings.session_timeline_rate_limit,
            settings.session_timeline_rate_window_seconds,
        )
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "session_timeline_rate_limited",
                    "detail": "Too many session timeline requests",
                },
                headers={"Retry-After": str(retry_after)},
            )
        try:
            return await session_timeline.read(provider, session_uuid, bucket_start)
        except SessionTimelineTimeout:
            return JSONResponse(
                status_code=504,
                content={
                    "code": "session_timeline_timeout",
                    "detail": "Session timeline collector timed out",
                },
            )
        except SessionTimelineUnavailable:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "session_timeline_unavailable",
                    "detail": "Session timeline collector unavailable",
                },
            )
        except SessionTimelineInvalidResponse:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "session_timeline_invalid_response",
                    "detail": "Session timeline collector returned an invalid response",
                },
            )

    @app.post(
        "/api/v1/provider-rate-limits/refresh",
        response_model=RateLimitFreshResult,
        dependencies=[Depends(require_admin)],
    )
    async def refresh_provider_rate_limits(
        request: Request,
    ) -> RateLimitFreshResult | JSONResponse:
        if not settings.rate_limit_fresh_enabled:
            raise HTTPException(404, "Not Found")
        retry_after = rate_limiter.check(
            f"rate-limit-fresh:{client_key(request)}",
            settings.rate_limit_fresh_rate_limit,
            settings.rate_limit_fresh_rate_window_seconds,
        )
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={
                    "code": "rate_limit_fresh_rate_limited",
                    "detail": "Too many rate limit refresh requests",
                },
                headers={"Retry-After": str(retry_after)},
            )
        try:
            return await rate_limit_fresh.fetch_fresh()
        except RateLimitFreshTimeout:
            return JSONResponse(
                status_code=504,
                content={
                    "code": "rate_limit_fresh_timeout",
                    "detail": "Rate limit collector timed out",
                },
            )
        except RateLimitFreshUnavailable:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "rate_limit_fresh_unavailable",
                    "detail": "Rate limit collector unavailable",
                },
            )
        except RateLimitFreshResponseError:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "rate_limit_fresh_invalid_response",
                    "detail": "Rate limit collector returned an invalid response",
                },
            )

    @app.get(
        "/api/v1/orchestrator-state",
        response_model=OrchestratorState | None,
        dependencies=[Depends(require_active_session)],
    )
    async def get_orchestrator_state() -> OrchestratorState | None:
        return await asyncio.to_thread(orchestrator_state.read)

    @app.post(
        "/api/v1/sessions",
        response_model=Accepted,
        status_code=201,
        dependencies=[Depends(require_operator)],
    )
    async def create_session(payload: CreateSessionInput) -> Accepted:
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        directory, _ = _resolve_within_allowed_roots(payload.directory, roots)
        try:
            await gateway.create_session(payload.name, str(directory), payload.profile)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except TmuxError as exc:
            detail = _tmux_mutation_error(exc, "Unable to create session")
            raise HTTPException(409, detail) from exc
        await _prepare_artifacts_folder(payload.name)
        return Accepted()

    @app.get(
        "/api/v1/sessions",
        response_model=SessionList,
        dependencies=[Depends(require_active_session)],
    )
    async def sessions() -> SessionList:
        try:
            items = await gateway.list_sessions()
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        hidden_ids = (
            await asyncio.to_thread(session_visibility.hidden_ids, {item.id for item in items})
            if session_visibility
            else set()
        )
        return SessionList(
            sessions=[SessionView(**item.__dict__, hidden=item.id in hidden_ids) for item in items]
        )

    @app.post(
        "/api/v1/sessions/{session_id}/visibility",
        response_model=Accepted,
    )
    async def set_session_visibility(
        session_id: str, payload: SessionVisibilityInput, cookie: str = Depends(require_operator)
    ) -> Accepted:
        try:
            live = next(
                (item for item in await gateway.list_sessions() if item.id == session_id), None
            )
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        if live is None:
            raise HTTPException(404, "Session not found")
        user = active_user(cookie)
        await asyncio.to_thread(
            session_visibility_service().set_hidden,
            session_id,
            payload.hidden,
            user.username if user is not None else "legacy",
        )
        return Accepted()

    @app.get(
        "/api/v1/sessions/{session_id}/claude-history",
        response_model=ClaudeHistoryView,
        dependencies=[Depends(require_active_session)],
    )
    async def get_claude_history(session_id: str) -> ClaudeHistoryView:
        if not settings.claude_history_enabled:
            raise HTTPException(404, "Claude history is disabled")
        if not session_id.isdigit() or len(session_id) > 10:
            raise HTTPException(404, "Claude history not available")
        try:
            live = next(
                (item for item in await gateway.list_sessions() if item.id == session_id),
                None,
            )
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        if live is None or "claude" not in live.current_command.lower():
            raise HTTPException(404, "Claude history not available")
        history = await asyncio.to_thread(claude_history.read, session_id)
        if history is None:
            raise HTTPException(404, "Claude history not available")
        return ClaudeHistoryView(
            session_id=session_id,
            collected_at=history.collected_at,
            source_updated_at=history.source_updated_at,
            truncated=history.truncated,
            messages=[
                ClaudeHistoryMessageView(**message.__dict__)
                for message in history.messages
            ],
        )

    @app.get(
        "/api/v1/agent-statuses",
        response_model=AgentStatusList,
        dependencies=[Depends(require_active_session)],
    )
    async def list_agent_statuses() -> AgentStatusList:
        try:
            sessions = await gateway.list_sessions()
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        agent_sessions = [
            item
            for item in sessions
            if agent_statuses.provider_for(item.current_command) is not None
        ]
        contents = await asyncio.gather(
            *(gateway.capture_output(item.id, 80) for item in agent_sessions),
            return_exceptions=True,
        )
        structured_permissions = await asyncio.to_thread(provider_session_states.read)
        views = []
        for item, content in zip(agent_sessions, contents, strict=True):
            if isinstance(content, BaseException):
                provider = agent_statuses.provider_for(item.current_command)
                if provider is not None:
                    views.append(
                        AgentStatusView(
                            session_id=item.id,
                            provider=provider,
                            state="unknown",
                            detail="Output non disponibile",
                            permission_state="unknown",
                            permission_detail="Livello permessi non rilevato",
                            context_used_percent=None,
                        )
                    )
                continue
            status = agent_statuses.classify(item.id, item.current_command, content)
            if status is not None:
                permission = structured_permissions.get(item.id)
                views.append(
                    AgentStatusView(
                        session_id=item.id,
                        provider=status.provider,
                        state=status.state,
                        detail=status.detail,
                        permission_state=(
                            permission.permission_state
                            if permission is not None
                            else status.permission_state
                        ),
                        permission_detail=(
                            permission.permission_detail
                            if permission is not None
                            else status.permission_detail
                        ),
                        context_used_percent=(
                            permission.context_used_percent
                            if permission is not None
                            else None
                        ),
                        summary=status.summary,
                    )
                )
        agent_statuses.forget_missing({item.id for item in sessions})
        return AgentStatusList(statuses=views)

    @app.get(
        "/api/v1/snapshots",
        response_model=SnapshotList,
        dependencies=[Depends(require_active_session)],
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

    @app.get(
        "/api/v1/archives",
        response_model=ArchiveList,
        dependencies=[Depends(require_active_session)],
    )
    async def list_archives() -> ArchiveList:
        items = await asyncio.to_thread(archive_service().list)
        return ArchiveList(
            archives=[
                ArchivedSessionView.model_validate(item, from_attributes=True)
                for item in items
            ]
        )

    @app.post(
        "/api/v1/sessions/{session_id}/archive",
        response_model=ArchivedSessionView,
        status_code=201,
    )
    async def archive_session(
        session_id: str,
        payload: ArchiveSessionInput,
        cookie: str = Depends(require_operator),
    ) -> ArchivedSessionView:
        if not payload.confirmed:
            raise HTTPException(400, "Archiving requires explicit confirmation")
        try:
            live = next(
                (item for item in await gateway.list_sessions() if item.id == session_id),
                None,
            )
            if not live:
                raise SessionNotFound(session_id)
            directory = await gateway.pane_path(session_id)
        except (ValueError, SessionNotFound) as exc:
            raise HTTPException(404, "Session not found") from exc
        service = archive_service()
        user = active_user(cookie)
        item = await asyncio.to_thread(
            service.create,
            live.name,
            directory,
            session_profile(live.current_command),
            user.username if user is not None else "legacy",
            payload.agent_session_name,
            payload.summary,
        )
        try:
            await gateway.terminate_session(session_id)
        except (ValueError, SessionNotFound, TmuxError) as exc:
            await asyncio.to_thread(service.delete, item.id)
            raise HTTPException(409, "Unable to archive session") from exc
        await _cleanup_session_files(session_id)
        return ArchivedSessionView.model_validate(item, from_attributes=True)

    @app.get(
        "/api/v1/sessions/{session_id}/archive-draft",
        response_model=ArchiveDraftView,
        dependencies=[Depends(require_active_session)],
    )
    async def get_archive_draft(session_id: str) -> ArchiveDraftView:
        try:
            TmuxService.validate_target(session_id)
            live = next(
                (item for item in await gateway.list_sessions() if item.id == session_id),
                None,
            )
        except ValueError as exc:
            raise HTTPException(404, "Session not found") from exc
        except TmuxError as exc:
            raise HTTPException(503, "tmux unavailable") from exc
        if live is None:
            raise HTTPException(404, "Session not found")
        summary = await asyncio.to_thread(artifacts.read_archive_summary, session_id)
        return ArchiveDraftView(summary=summary)

    @app.post(
        "/api/v1/archives/{archive_id}/restore",
        response_model=Accepted,
        status_code=201,
        dependencies=[Depends(require_operator)],
    )
    async def restore_archive(archive_id: str, payload: ConfirmedAction) -> Accepted:
        if not payload.confirmed:
            raise HTTPException(400, "Archive restore requires explicit confirmation")
        service = archive_service()
        item = await asyncio.to_thread(service.get, archive_id)
        if not item:
            raise HTTPException(404, "Archive not found")
        roots = [Path(root).resolve() for root in settings.allowed_roots]
        directory, _ = _resolve_within_allowed_roots(item.directory, roots)
        try:
            await gateway.create_session(
                item.name,
                str(directory),
                item.profile,
                resume=True,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except TmuxError as exc:
            detail = _tmux_mutation_error(exc, "Unable to restore archive")
            raise HTTPException(409, detail) from exc
        await asyncio.to_thread(service.delete, archive_id)
        return Accepted()

    @app.delete(
        "/api/v1/archives/{archive_id}",
        status_code=204,
        dependencies=[Depends(require_operator)],
    )
    async def delete_archive(archive_id: str, payload: ConfirmedAction) -> Response:
        if not payload.confirmed:
            raise HTTPException(400, "Archive deletion requires explicit confirmation")
        deleted = await asyncio.to_thread(archive_service().delete, archive_id)
        if not deleted:
            raise HTTPException(404, "Archive not found")
        return Response(status_code=204)

    @app.post(
        "/api/v1/snapshots",
        response_model=SnapshotView,
        status_code=201,
        dependencies=[Depends(require_operator)],
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
        dependencies=[Depends(require_operator)],
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
                profile = (
                    saved.mode if saved.mode in {"antigravity", "opencode"} else "shell"
                )
                await gateway.create_session(saved.name, str(directory), profile)
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
                elif saved.mode == "antigravity":
                    status = "restored"
                    detail = "Antigravity launched; its history is managed by its CLI"
                elif saved.mode == "opencode":
                    status = "restored"
                    # Nessun `--continue`: lo store delle conversazioni e'
                    # globale per utente e potrebbe agganciare quella
                    # sbagliata (IMP-OC-00). L'aggancio alla conversazione
                    # giusta e' materia di OC-02 (selettore nativo).
                    detail = "OpenCode launched; resume the conversation from its own /sessions picker"
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
        dependencies=[Depends(require_operator)],
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
        "/api/v1/sessions/{session_id}/panes",
        response_model=PaneList,
        dependencies=[Depends(require_active_session)],
    )
    async def panes(session_id: str) -> PaneList:
        try:
            items = await gateway.list_panes(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return PaneList(panes=[PaneView(**vars(item)) for item in items])

    @app.post(
        "/api/v1/sessions/{session_id}/panes/split",
        response_model=PaneView,
        status_code=201,
        dependencies=[Depends(require_operator)],
    )
    async def split_pane(
        session_id: str,
        pane_id: Annotated[str | None, Query(pattern=r"^\d{1,10}$")] = None,
        direction: Annotated[str, Query(pattern=r"^(horizontal|vertical)$")] = "horizontal",
    ) -> PaneView:
        try:
            item = await gateway.split_pane(session_id, pane_id, direction)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Pane not found in session") from exc
        except TmuxError as exc:
            raise HTTPException(409, "Unable to split pane") from exc
        return PaneView(**vars(item))

    @app.post(
        "/api/v1/sessions/{session_id}/panes/{pane_id}/resize",
        response_model=Accepted,
        dependencies=[Depends(require_operator)],
    )
    async def resize_pane(
        session_id: str, pane_id: str, payload: ResizePaneInput
    ) -> Accepted:
        try:
            await gateway.resize_pane(session_id, pane_id, payload.columns, payload.rows)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Pane not found in session") from exc
        return Accepted()

    @app.delete(
        "/api/v1/sessions/{session_id}/panes/{pane_id}",
        status_code=204,
        dependencies=[Depends(require_operator)],
    )
    async def kill_pane(
        session_id: str, pane_id: str, payload: ConfirmedAction
    ) -> Response:
        if not payload.confirmed:
            raise HTTPException(400, "Closing a pane requires explicit confirmation")
        try:
            panes = await gateway.list_panes(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        if not any(pane.id == pane_id for pane in panes):
            raise HTTPException(404, "Pane not found in session")
        if len(panes) < 2:
            raise HTTPException(400, "Terminate the session instead of closing its last pane")
        try:
            await gateway.kill_pane(session_id, pane_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Pane not found in session") from exc
        return Response(status_code=204)

    @app.get(
        "/api/v1/sessions/{session_id}/output",
        response_model=OutputView,
        dependencies=[Depends(require_active_session)],
    )
    async def output(
        session_id: str,
        lines: Annotated[int, Query(ge=1, le=2000)] = 500,
        pane_id: Annotated[str | None, Query(pattern=r"^\d{1,10}$")] = None,
    ) -> OutputView:
        try:
            content = await gateway.capture_output(session_id, lines, pane_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return OutputView(session_id=session_id, content=content, captured_at=datetime.now(UTC))

    @app.get(
        "/api/v1/sessions/{session_id}/directory",
        response_model=DirectoryView,
        dependencies=[Depends(require_active_session)],
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
        dependencies=[Depends(require_active_session)],
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
        dependencies=[Depends(require_active_session)],
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

    @app.get(
        "/api/v1/sessions/{session_id}/file/preview",
        dependencies=[Depends(require_active_session)],
    )
    async def preview_session_file(
        session_id: str,
        path: Annotated[str, Query(min_length=1, max_length=4096)],
    ) -> FileResponse:
        """Serve immagini, video e audio *dentro* la pagina, come gli artefatti.

        L'anteprima testuale (`/file`) rifiuta qualunque file con un byte nullo, quindi
        un mp4 nel browser di directory finiva in "Binary file, no preview available"
        anche se lo stesso file, fra gli artefatti, si guardava senza problemi.
        """
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
        media_type = await asyncio.to_thread(sniff_media_type, file_path)
        if media_type not in INLINE_PREVIEW_MEDIA_TYPES:
            raise HTTPException(400, "File type has no inline preview")
        return FileResponse(
            file_path,
            # Senza `filename` Starlette non emette affatto Content-Disposition, e
            # `content_disposition_type` da solo non ha effetto. Il nome serve anche
            # al "salva con nome" del browser.
            filename=file_path.name,
            media_type=media_type,
            content_disposition_type="inline",
            # Il tipo e' dedotto dai byte, non dall'estensione: impedire al browser di
            # indovinarne un altro e' l'altra meta' della difesa.
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.post(
        "/api/v1/sessions/{session_id}/directory/upload",
        response_model=UploadResultView,
        status_code=201,
        dependencies=[Depends(require_operator)],
    )
    async def upload_directory_file(
        session_id: str,
        request: Request,
        filename: Annotated[str, Query(min_length=1, max_length=255)],
        path: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    ) -> UploadResultView:
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
        directory, _ = _resolve_within_allowed_roots(raw_path, roots)

        if not directory.exists() or not directory.is_dir():
            raise HTTPException(404, "Directory not found")

        safe_name = Path(filename).name
        if (
            not safe_name
            or safe_name in {".", ".."}
            or "/" in filename
            or "\\" in filename
            or "\x00" in filename
        ):
            raise HTTPException(400, "Invalid filename")

        target_file = (directory / safe_name).resolve()
        if target_file.parent != directory:
            raise HTTPException(400, "Invalid file destination")

        ext = target_file.suffix.lower()
        if ext not in settings.upload_allowed_extensions:
            raise HTTPException(400, f"File extension '{ext}' is not allowed")

        stem = safe_name[: -len(ext)] if ext else safe_name
        if not stem or not re.match(r"^[\w]+$", stem):
            raise HTTPException(
                400, "Filename must contain only letters, numbers, and underscores"
            )

        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > settings.max_upload_bytes:
            raise HTTPException(
                400, f"File exceeds maximum upload size of {settings.max_upload_bytes} bytes"
            )

        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > settings.max_upload_bytes:
                raise HTTPException(
                    400, f"File exceeds maximum upload size of {settings.max_upload_bytes} bytes"
                )

        def _write_file() -> None:
            target_file.write_bytes(content)

        try:
            await asyncio.to_thread(_write_file)
        except OSError as exc:
            raise HTTPException(500, f"Failed to save file: {exc}") from exc

        return UploadResultView(
            session_id=session_id,
            path=str(target_file),
            name=safe_name,
            size=len(content),
        )

    @app.post(
        "/api/v1/sessions/{session_id}/attachments",
        response_model=AttachmentView,
        status_code=201,
        dependencies=[Depends(require_operator)],
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
            attachment = await asyncio.to_thread(
                attachment_service().create,
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
        dependencies=[Depends(require_operator)],
    )
    async def send_input(session_id: str, payload: TextInput) -> Accepted:
        try:
            suffix = ""
            if payload.attachment_ids:
                suffix = await asyncio.to_thread(
                    attachment_service().prompt_suffix, session_id, payload.attachment_ids
                )
            text = payload.text + suffix
            if len(text) > 65536:
                raise AttachmentError("Prompt with attachment references is too large")
            await gateway.send_text(session_id, text, payload.pane_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Accepted()

    @app.post(
        "/api/v1/sessions/{session_id}/artifact-prompt",
        response_model=Accepted,
        status_code=202,
        dependencies=[Depends(require_operator)],
    )
    async def send_artifact_prompt(session_id: str, payload: PaneTargetInput) -> Accepted:
        try:
            # Valida prima del filesystem: l'id della route non può diventare
            # un segmento di path controllato dal client.
            TmuxService.validate_target(session_id)
            await asyncio.to_thread(artifacts.ensure_session_dir, session_id)
            hint = (
                "Quando hai un file da consegnare nella console mobile, "
                f"salvalo in: {artifacts.prompt_path(session_id)}"
            )
            await gateway.send_text(session_id, hint, payload.pane_id)
            await gateway.send_key(session_id, "Enter", payload.pane_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Accepted()

    @app.post(
        "/api/v1/sessions/{session_id}/archive-summary-prompt",
        response_model=Accepted,
        status_code=202,
        dependencies=[Depends(require_operator)],
    )
    async def send_archive_summary_prompt(
        session_id: str, payload: PaneTargetInput
    ) -> Accepted:
        try:
            TmuxService.validate_target(session_id)
            await asyncio.to_thread(artifacts.ensure_session_dir, session_id)
            summary_path = f"{artifacts.prompt_path(session_id)}/{ARCHIVE_SUMMARY_NAME}"
            hint = (
                "Prepara un breve riepilogo della conversazione corrente, utile per "
                "riconoscerla e riprenderla in futuro. Scrivi solo il riepilogo, senza "
                "segreti, credenziali o trascrizioni estese, nel file UTF-8: "
                f"{summary_path}. Mantienilo indicativamente tra 400 e 800 caratteri."
            )
            await gateway.send_text(session_id, hint, payload.pane_id)
            await gateway.send_key(session_id, "Enter", payload.pane_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Accepted()

    @app.get(
        "/api/v1/sessions/{session_id}/attachments/{attachment_id}/preview",
        dependencies=[Depends(require_active_session)],
    )
    async def attachment_preview(session_id: str, attachment_id: str) -> FileResponse:
        try:
            thumb_path = await asyncio.to_thread(
                attachment_service().preview_path, session_id, attachment_id
            )
        except AttachmentError as exc:
            raise HTTPException(404, str(exc)) from exc
        return FileResponse(thumb_path, media_type="image/jpeg")

    @app.delete(
        "/api/v1/sessions/{session_id}/attachments/{attachment_id}",
        status_code=204,
        dependencies=[Depends(require_operator)],
    )
    async def delete_attachment(session_id: str, attachment_id: str) -> Response:
        try:
            await asyncio.to_thread(attachment_service().delete, session_id, attachment_id)
        except AttachmentError as exc:
            raise HTTPException(404, str(exc)) from exc
        return Response(status_code=204)

    @app.get(
        "/api/v1/sessions/{session_id}/artifact-directory",
        response_model=ArtifactDirectoryView,
        dependencies=[Depends(require_active_session)],
    )
    async def get_artifact_directory(session_id: str) -> ArtifactDirectoryView:
        try:
            TmuxService.validate_target(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return ArtifactDirectoryView(path=artifacts.prompt_path(session_id))

    @app.get(
        "/api/v1/sessions/{session_id}/artifacts",
        response_model=list[ArtifactView],
        dependencies=[Depends(require_active_session)],
    )
    async def list_artifacts(session_id: str) -> list[ArtifactView]:
        try:
            TmuxService.validate_target(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        items = await asyncio.to_thread(artifacts.list, session_id)
        return [ArtifactView(**item.__dict__) for item in items]

    @app.get(
        "/api/v1/sessions/{session_id}/artifacts/{name:path}",
        dependencies=[Depends(require_active_session)],
    )
    async def download_artifact(session_id: str, name: str) -> FileResponse:
        try:
            TmuxService.validate_target(session_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            artifact = await asyncio.to_thread(artifacts.get, session_id, name)
        except ArtifactError as exc:
            raise HTTPException(404, str(exc)) from exc
        file_path = artifacts.storage_root / session_id / artifact.name
        return FileResponse(
            file_path,
            media_type=artifact.media_type,
            filename=artifact.name,
            content_disposition_type="attachment",
        )

    @app.get(
        "/api/v1/push/public-key",
        response_model=PushPublicKeyView,
        dependencies=[Depends(require_active_session)],
    )
    async def push_public_key() -> PushPublicKeyView:
        return PushPublicKeyView(public_key=push_service().public_key)

    @app.post(
        "/api/v1/push/subscriptions",
        status_code=204,
        dependencies=[Depends(require_active_csrf)],
    )
    async def create_push_subscription(payload: PushSubscriptionInput) -> Response:
        await asyncio.to_thread(
            push_service().subscribe,
            payload.endpoint,
            payload.keys.p256dh,
            payload.keys.auth,
        )
        return Response(status_code=204)

    @app.delete(
        "/api/v1/push/subscriptions",
        status_code=204,
        dependencies=[Depends(require_active_csrf)],
    )
    async def delete_push_subscription(payload: PushUnsubscribeInput) -> Response:
        await asyncio.to_thread(push_service().unsubscribe, payload.endpoint)
        return Response(status_code=204)

    @app.post(
        "/api/v1/sessions/{session_id}/keys",
        response_model=Accepted,
        status_code=202,
        dependencies=[Depends(require_operator)],
    )
    async def send_key(session_id: str, payload: KeyInput) -> Accepted:
        if payload.key == "C-c" and not payload.confirmed:
            raise HTTPException(400, "Interrupt requires explicit confirmation")
        try:
            await gateway.send_key(session_id, payload.key, payload.pane_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except SessionNotFound as exc:
            raise HTTPException(404, "Session not found") from exc
        return Accepted()

    @app.delete(
        "/api/v1/sessions/{session_id}",
        status_code=204,
        dependencies=[Depends(require_operator)],
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
        except TmuxError as exc:
            raise HTTPException(409, str(exc)) from exc
        await _cleanup_session_files(session_id)
        return Response(status_code=204)

    @app.post(
        "/api/v1/sessions/{session_id}/rename",
        response_model=Accepted,
        dependencies=[Depends(require_operator)],
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
    async def stream(
        websocket: WebSocket,
        session_id: str,
        pane_id: str | None = None,
        ansi: bool = False,
        lines: Annotated[int, Query(ge=100, le=2000)] = 500,
    ) -> None:
        cookie = websocket.cookies.get(COOKIE_NAME)
        try:
            security.validate_session(cookie)
            if cookie:
                active_user(cookie)
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
                    content = await gateway.capture_output(session_id, lines, pane_id, ansi=ansi)
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
                    if previous is None:
                        message = {
                            "type": "snapshot",
                            "session_id": session_id,
                            "sequence_id": sequence,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "content": content,
                        }
                    else:
                        delta = line_delta(previous, content)
                        message = {
                            "type": "delta",
                            "session_id": session_id,
                            "base_sequence_id": sequence - 1,
                            "sequence_id": sequence,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "start": delta.start,
                            "delete_count": delta.delete_count,
                            "lines": delta.lines,
                        }
                    previous = content
                    await websocket.send_json(message)
                else:
                    idle_cycles += 1
                await asyncio.sleep(0.5 if idle_cycles < 10 else 1.0 if idle_cycles < 30 else 2.0)
        except (WebSocketDisconnect, RuntimeError):
            # Starlette/uvicorn possono esporre la chiusura del transport come
            # RuntimeError se avviene mentre è in corso un send_json.
            return

    return app


app = create_app()
