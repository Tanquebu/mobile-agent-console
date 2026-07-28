import json
import logging
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02
from py_vapid.utils import b64urlencode
from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from ..models import PushSubscription

logger = logging.getLogger("mobile_agent_console")


class PushService:
    def __init__(self, engine, vapid_key_path: str, contact_email: str) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        key_path = Path(vapid_key_path)
        key_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        is_new = not key_path.is_file()
        self._vapid = Vapid02.from_file(vapid_key_path)
        if is_new:
            os.chmod(vapid_key_path, 0o600)
        self._contact_email = contact_email

    @property
    def public_key(self) -> str:
        raw = self._vapid.public_key.public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )
        return b64urlencode(raw)

    def subscribe(self, endpoint: str, p256dh: str, auth: str) -> None:
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
            if existing is None:
                session.add(PushSubscription(endpoint=endpoint, p256dh=p256dh, auth=auth))
            else:
                existing.p256dh = p256dh
                existing.auth = auth

    def unsubscribe(self, endpoint: str) -> None:
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(PushSubscription).where(PushSubscription.endpoint == endpoint)
            )
            if existing is not None:
                session.delete(existing)

    def notify(self, title: str, body: str, tag: str) -> None:
        with self._sessions() as session:
            subscriptions = list(session.scalars(select(PushSubscription)))
        if not subscriptions:
            return
        # Nessun contenuto di output/prompt nel payload, per coerenza con le
        # notifiche locali (docs/security.md).
        payload = json.dumps({"title": title, "body": body, "tag": tag})
        stale_ids: list[int] = []
        for subscription in subscriptions:
            subscription_info = {
                "endpoint": subscription.endpoint,
                "keys": {"p256dh": subscription.p256dh, "auth": subscription.auth},
            }
            try:
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=self._vapid,
                    vapid_claims={"sub": f"mailto:{self._contact_email}"},
                )
            except WebPushException as exc:
                status = getattr(exc.response, "status_code", None)
                if status in (404, 410):
                    stale_ids.append(subscription.id)
                else:
                    logger.warning("Web push delivery failed: %s", exc)
        if stale_ids:
            with self._sessions.begin() as session:
                session.query(PushSubscription).filter(
                    PushSubscription.id.in_(stale_ids)
                ).delete(synchronize_session=False)
