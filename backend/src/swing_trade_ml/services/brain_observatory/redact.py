"""Remove secrets from stored free text before the Observatory shows it (spec 3.4, R9).

Only values under FREE_TEXT_KEYS are touched, however deeply nested under one. Ids, symbols, words,
numbers, timestamps and pagination cursors are typed fields and pass through unchanged. Text is never
parsed for meaning, only redacted.
"""

from __future__ import annotations

import os
import re
from urllib.parse import urlsplit

from swing_trade_ml.core.config import settings

FREE_TEXT_KEYS = frozenset(
    {
        "error",
        "reason",
        "reasons",
        "evidence_text",
        "downgrade_reason",
        "overrule_reason",
        "banner_headline",
        "headline",
        "text",
        "detail",
        "issues",
        "note",
        "title",
        "evidence",
        "decided_note",
        "drift_note",
        "drift_lines",
        "message",
        "failure_messages",
        "conflicts",
        "problems",
        "why",
    }
)
SECRET_SETTINGS = (
    "KITE_API_KEY",
    "KITE_API_SECRET",
    "KITE_PASSWORD",
    "KITE_TOTP_SECRET",
    "KITE_USER_ID",
    "API_KEY",
    "JWT_SECRET_KEY",
    "GOOGLE_CLIENT_SECRET",
    "POSTGRES_PASSWORD",
    "DATABASE_URL",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
)
MASK = "[redacted]"
_RUN_ID = re.compile(r"^(nightly|intraday|why)-\d{8}T\d{6}-[0-9a-f]{6}$")
_URL_CRED = re.compile(r"(\b[a-zA-Z][a-zA-Z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+")
_KV = re.compile(r"(?i)\b(access_token|api[_-]?key|secret|password|token)(\s*[=:]\s*)([^\s,;'\"]+)")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_LONG = re.compile(r"[A-Za-z0-9+/_\-]{32,}={0,2}")


def _secret_values() -> list[str]:
    values: set[str] = set()
    for name in SECRET_SETTINGS:
        for raw in (getattr(settings, name, None), os.environ.get(name)):
            if raw is None:
                continue
            value = raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)
            if len(value) >= 4:
                values.add(value)
            if name == "DATABASE_URL" and value:
                password = urlsplit(value).password
                if password and len(password) >= 4:
                    values.add(password)
    return sorted(values, key=len, reverse=True)


_PATH_PART = re.compile(r"[a-z0-9_\-]{0,31}")


def _is_path(token: str) -> bool:
    """A file path such as /app/src/swing_trade_ml/brain: two or more slashes, every part short and
    lower case. Random keys mix upper and lower case, so they are still masked."""
    parts = token.split("/")
    return len(parts) >= 3 and any(parts) and all(_PATH_PART.fullmatch(p) for p in parts)


def _long(match: re.Match) -> str:
    token = match.group(0)
    return token if _RUN_ID.match(token) or _is_path(token) else MASK


def redact_text(s: str) -> str:
    out = s
    for value in _secret_values():
        out = out.replace(value, MASK)
    out = _URL_CRED.sub(lambda m: f"{m.group(1)}{MASK}@", out)
    out = _JWT.sub(MASK, out)
    out = _KV.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", out)
    out = _EMAIL.sub(MASK, out)
    return _LONG.sub(_long, out)


def _walk(value, path: str, free: bool, changed: list[str]):
    if isinstance(value, dict):
        return {
            k: _walk(v, f"{path}.{k}" if path else k, free or k in FREE_TEXT_KEYS, changed)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_walk(v, f"{path}[{i}]", free, changed) for i, v in enumerate(value)]
    if free and isinstance(value, str):
        cleaned = redact_text(value)
        if cleaned != value:
            changed.append(path)
        return cleaned
    return value


def redact_response(payload: dict) -> dict:
    """A copy of `payload` with every free-text value redacted, plus `redacted_fields`: the paths changed."""
    changed: list[str] = []
    out = _walk(payload, "", False, changed)
    out["redacted_fields"] = changed
    return out
