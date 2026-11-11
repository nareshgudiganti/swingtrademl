"""Scoped machine keys: create, check, rotate, revoke.

Rules (settled with the owner, 2026-11-11):
- A key has ONE scope. Scopes only ever allow GET. No scope allows writes, the real
  Zerodha account, the owner's private areas or /admin. Adding a write route to a scope
  is a deliberate code change with a test, never configuration.
- Only the SHA-256 hash is stored. The key is shown once, when it is created.
- The old shared API_KEY keeps working until LEGACY_API_KEY_ENABLED is turned off.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from swing_trade_ml.db.models.service_keys import ServiceKey

KEY_PREFIX = "stk_"
SCOPES = ("read_status", "read_all")
#: Update last_used_at at most this often, so a busy checker does not write on every call.
LAST_USED_EVERY = timedelta(minutes=10)

#: GET routes (route templates, no API prefix) a read_status key may call: the health checks and
#: watch workflows. Everything else answers 403.
READ_STATUS_PATHS: frozenset[str] = frozenset(
    {
        "/status",
        "/market/session",
        "/risk/limits",
        "/brain/stage",
        "/brain/daily-checks/latest",
    }
)

#: Areas no service key may read, even with read_all (the owner's money and settings).
FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "/admin",
    "/auth",
    "/finance",
    "/mutual-funds",
    "/safety",
    "/notifications",
    "/brain/alerts",
    "/brain/approvals",
    "/me",
)


def scope_allows(scope: str, method: str, path: str) -> bool:
    if method not in ("GET", "HEAD"):
        return False
    if any(path == p or path.startswith(p + "/") for p in FORBIDDEN_PREFIXES):
        return False
    if scope == "read_all":
        return True
    if scope == "read_status":
        return path in READ_STATUS_PATHS
    return False


def hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ServiceCaller:
    id: int
    name: str
    scope: str


def create_key(
    db: Session,
    *,
    name: str,
    scope: str,
    created_by: str,
    expires_in_days: int | None = None,
    rotated_from_id: int | None = None,
) -> tuple[ServiceKey, str]:
    """Returns the row and the raw key. The raw key exists only in this return value."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope {scope!r}. Choose one of: {', '.join(SCOPES)}.")
    name = name.strip()
    if not name:
        raise ValueError("Give the key a name, e.g. uptime-watch.")
    raw = KEY_PREFIX + secrets.token_urlsafe(32)
    row = ServiceKey(
        name=name[:64],
        scope=scope,
        key_hash=hash_key(raw),
        prefix=raw[: len(KEY_PREFIX) + 4],
        created_by=created_by[:64],
        expires_at=_now() + timedelta(days=expires_in_days) if expires_in_days else None,
        rotated_from_id=rotated_from_id,
    )
    db.add(row)
    db.flush()
    return row, raw


def authenticate(db: Session, raw: str) -> ServiceCaller | None:
    """The caller for a valid key, else None. Revoked and expired keys never match."""
    if not raw.startswith(KEY_PREFIX):
        return None
    row = db.execute(select(ServiceKey).where(ServiceKey.key_hash == hash_key(raw))).scalar_one_or_none()
    if row is None or row.revoked_at is not None:
        return None
    now = _now()
    if row.expires_at is not None and row.expires_at <= now:
        return None
    if row.last_used_at is None or now - row.last_used_at >= LAST_USED_EVERY:
        db.execute(update(ServiceKey).where(ServiceKey.id == row.id).values(last_used_at=now))
        db.commit()
    return ServiceCaller(id=row.id, name=row.name, scope=row.scope)


def revoke(db: Session, key_id: int) -> ServiceKey | None:
    row = db.get(ServiceKey, key_id)
    if row is None:
        return None
    if row.revoked_at is None:
        row.revoked_at = _now()
    return row


def rotate(
    db: Session, key_id: int, *, created_by: str, overlap_hours: int = 24
) -> tuple[ServiceKey, str, ServiceKey] | None:
    """New key, same name and scope. The old one stops working after `overlap_hours`
    (0 = at once), so a workflow secret can be swapped without a gap."""
    old = db.get(ServiceKey, key_id)
    if old is None or old.revoked_at is not None:
        return None
    new, raw = create_key(db, name=old.name, scope=old.scope, created_by=created_by, rotated_from_id=old.id)
    if overlap_hours <= 0:
        old.revoked_at = _now()
    else:
        cutoff = _now() + timedelta(hours=overlap_hours)
        old.expires_at = cutoff if old.expires_at is None or old.expires_at > cutoff else old.expires_at
    return new, raw, old


def list_keys(db: Session) -> list[ServiceKey]:
    return list(db.execute(select(ServiceKey).order_by(ServiceKey.id.desc())).scalars())
