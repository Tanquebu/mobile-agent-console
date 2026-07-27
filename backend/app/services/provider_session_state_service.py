import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

PermissionState = Literal[
    "restricted",
    "standard",
    "elevated",
    "bypass",
    "plan",
    "ask",
    "auto",
    "manual",
    "accept_edits",
    "dont_ask",
    "unknown",
]


@dataclass(frozen=True)
class ProviderSessionState:
    permission_state: PermissionState
    permission_detail: str
    context_used_percent: float | None


class ProviderSessionStateService:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def read(self) -> dict[str, ProviderSessionState]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        states: dict[str, ProviderSessionState] = {}
        if not isinstance(payload, dict) or not isinstance(payload.get("sessions"), list):
            return states
        for item in payload["sessions"]:
            if not isinstance(item, dict):
                continue
            session_id = item.get("session_id")
            state = item.get("permission_state")
            detail = item.get("permission_detail")
            context = item.get("context_used_percent")
            if (
                isinstance(session_id, str)
                and session_id.isdigit()
                and state
                in {
                    "restricted",
                    "standard",
                    "elevated",
                    "bypass",
                    "plan",
                    "ask",
                    "auto",
                    "manual",
                    "accept_edits",
                    "dont_ask",
                    "unknown",
                }
                and isinstance(detail, str)
            ):
                states[session_id] = ProviderSessionState(
                    state,
                    detail,
                    (
                        float(context)
                        if isinstance(context, (int, float)) and 0 <= context <= 100
                        else None
                    ),
                )
        return states
