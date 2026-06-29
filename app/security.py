"""Signed ack/resolve links so Google Chat / email buttons can act without
a login. Token = HMAC(secret, "<incident_id>:<action>")."""
from __future__ import annotations

import hashlib
import hmac

from .config import get_settings


def make_token(incident_id: int, action: str) -> str:
    secret = get_settings().secret.encode()
    msg = f"{incident_id}:{action}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()[:32]


def verify_token(incident_id: int, action: str, token: str) -> bool:
    return hmac.compare_digest(make_token(incident_id, action), token or "")


def action_url(incident_id: int, action: str) -> str:
    base = get_settings().base_url
    token = make_token(incident_id, action)
    return f"{base}/incidents/{incident_id}/{action}?token={token}"
