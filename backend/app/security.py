import base64
import hashlib
import hmac
import secrets
import time

from fastapi import Cookie, Header, HTTPException, status

from .config import Settings

COOKIE_NAME = "mac_session"


class SessionSecurity:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.secret = settings.resolved_session_secret.encode()

    def authenticate_password(self, password: str) -> bool:
        return secrets.compare_digest(password, self.settings.resolved_login_password)

    def issue_session(self, subject: str = "legacy") -> tuple[str, str]:
        payload = f"v2.{int(time.time())}.{subject}.{secrets.token_urlsafe(24)}"
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
        cookie = f"{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
        return cookie, self.csrf_for(cookie)

    def validate_session(self, cookie: str | None) -> str:
        if not cookie:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
        try:
            parts = cookie.split(".")
            if len(parts) == 5 and parts[0] == "v2":
                _, issued, subject, nonce, supplied = parts
                if not subject:
                    raise ValueError
                payload = f"v2.{issued}.{subject}.{nonce}"
            elif len(parts) == 3:
                issued, nonce, supplied = parts
                payload = f"{issued}.{nonce}"
            else:
                raise ValueError
            expected = base64.urlsafe_b64encode(
                hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
            ).decode().rstrip("=")
            valid_age = 0 <= time.time() - int(issued) <= self.settings.session_ttl_seconds
        except (ValueError, TypeError):
            valid_age = False
            expected = ""
            supplied = "invalid"
        if not valid_age or not secrets.compare_digest(supplied, expected):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid session")
        return cookie

    def subject_for(self, cookie: str) -> str | None:
        self.validate_session(cookie)
        parts = cookie.split(".")
        return parts[2] if len(parts) == 5 and parts[0] == "v2" else None

    def csrf_for(self, cookie: str) -> str:
        return hmac.new(self.secret, f"csrf:{cookie}".encode(), hashlib.sha256).hexdigest()

    def require_session(self, mac_session: str | None = Cookie(default=None)) -> str:
        return self.validate_session(mac_session)

    def require_csrf(
        self,
        mac_session: str | None = Cookie(default=None),
        csrf: str | None = Header(default=None, alias="X-CSRF-Token"),
    ) -> str:
        cookie = self.validate_session(mac_session)
        if not csrf or not secrets.compare_digest(csrf, self.csrf_for(cookie)):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Invalid CSRF token")
        return cookie
