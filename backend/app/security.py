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

    def issue_session(self) -> tuple[str, str]:
        payload = f"{int(time.time())}.{secrets.token_urlsafe(24)}"
        signature = hmac.new(self.secret, payload.encode(), hashlib.sha256).digest()
        cookie = f"{payload}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"
        return cookie, self.csrf_for(cookie)

    def validate_session(self, cookie: str | None) -> str:
        if not cookie:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
        try:
            issued, nonce, supplied = cookie.split(".", 2)
            payload = f"{issued}.{nonce}"
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
