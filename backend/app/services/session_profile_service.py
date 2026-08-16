import json
import threading
from pathlib import Path

PROFILES = {
    "shell",
    "codex",
    "claude",
    "antigravity",
    "antigravity_yolo",
    "opencode",
    "opencode_yolo",
}


class SessionProfileError(ValueError):
    pass


class SessionProfileService:
    """Mappa persistente `session_id tmux -> profilo di avvio`.

    Il backend è stateless e ricreato durante il deploy: il profilo di
    avvio (in particolare le varianti yolo, che non si possono dedurre dal
    `pane_current_command`) deve sopravvivere ai riavvii su disco. Il file
    vive nella directory di stato della console, come gli altri snapshot
    JSON; le entry orfane (sessione terminata fuori da MAC) sono filtrate
    dal chiamante e pulite su terminazione/archiviazione esplicita.
    """

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.Lock()

    def read(self) -> dict[str, str]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        profiles: dict[str, str] = {}
        for session_id, profile in payload.items():
            if (
                isinstance(session_id, str)
                and session_id.isdigit()
                and isinstance(profile, str)
                and profile in PROFILES
            ):
                profiles[session_id] = profile
        return profiles

    def set(self, session_id: str, profile: str) -> None:
        if not session_id.isdigit():
            raise SessionProfileError("Invalid session id")
        if profile not in PROFILES:
            raise SessionProfileError("Unsupported profile")
        with self._lock:
            profiles = self.read()
            profiles[session_id] = profile
            self._write(profiles)

    def remove(self, session_id: str) -> None:
        with self._lock:
            profiles = self.read()
            if session_id not in profiles:
                return
            del profiles[session_id]
            self._write(profiles)

    def _write(self, profiles: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary_path = self.path.with_suffix(".json.part")
        temporary_path.write_text(
            json.dumps(profiles, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary_path.chmod(0o600)
        temporary_path.replace(self.path)
