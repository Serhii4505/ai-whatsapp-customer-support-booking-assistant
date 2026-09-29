"""Webhook challenge and HMAC signature verification."""

from __future__ import annotations

import hashlib
import hmac
import re

from app.whatsapp.errors import InvalidSignatureError


SIGNATURE_PATTERN = re.compile(r"^sha256=([0-9a-fA-F]{64})$")


def compute_signature(body: bytes, app_secret: str) -> str:
    """Return the signature format used by Meta's X-Hub-Signature-256 header."""

    digest = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(body: bytes, signature_header: str | None, app_secret: str) -> None:
    """Reject absent, malformed or mismatched signatures in constant time."""

    if not signature_header or not SIGNATURE_PATTERN.fullmatch(signature_header):
        raise InvalidSignatureError("missing or malformed webhook signature")
    expected = compute_signature(body, app_secret)
    if not hmac.compare_digest(signature_header.lower(), expected):
        raise InvalidSignatureError("webhook signature mismatch")


def verify_challenge(mode: str | None, supplied_token: str | None, expected_token: str) -> bool:
    """Validate Meta's webhook subscription challenge without leaking the token."""

    if mode != "subscribe" or supplied_token is None:
        return False
    return hmac.compare_digest(supplied_token, expected_token)

