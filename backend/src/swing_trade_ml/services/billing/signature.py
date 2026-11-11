"""Webhook signature: HMAC-SHA256 of the RAW body with the webhook secret, hex, constant-time compare."""

from __future__ import annotations

import hashlib
import hmac


def sign(raw_body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()


def verify(raw_body: bytes, signature: str | None, secret: str) -> bool:
    if not secret or not signature:
        return False
    return hmac.compare_digest(sign(raw_body, secret), signature.strip())
