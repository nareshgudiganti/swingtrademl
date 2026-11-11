"""Password rules, as a pure function (no database, no network).

Length is what matters: at least 15 characters, spaces and any symbols allowed, no
"must contain a symbol" rules. Also refuses a password that IS the person's email (or the
part before the "@"), and passwords on a short bundled list of very common ones. Containing
a name or email fragment is allowed. A breached-password check is a later, separate decision.
Not wired into signup yet.
"""

from __future__ import annotations

from collections.abc import Collection
from functools import lru_cache
from pathlib import Path

MIN_LENGTH = 15
MAX_LENGTH = 256
_COMMON_FILE = Path(__file__).with_name("common_passwords.txt")


@lru_cache(maxsize=1)
def load_common_passwords() -> frozenset[str]:
    try:
        lines = _COMMON_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return frozenset()
    return frozenset(s.strip().lower() for s in lines if s.strip() and not s.startswith("#"))


def check_password(
    password: str,
    *,
    email: str | None = None,
    name: str | None = None,
    common_passwords: Collection[str] | None = None,
) -> list[str]:
    """Return plain-English problems; an empty list means the password is acceptable."""
    if not isinstance(password, str) or not password:
        return ["Enter a password."]
    problems: list[str] = []
    if len(password) < MIN_LENGTH:
        problems.append(f"Use at least {MIN_LENGTH} characters. A few random words with spaces works well.")
    if len(password) > MAX_LENGTH:
        problems.append(f"Use at most {MAX_LENGTH} characters.")
    lowered = password.lower()
    common = load_common_passwords() if common_passwords is None else common_passwords
    if lowered in common or lowered.strip() in common:
        problems.append("That password is too common. Pick something only you would think of.")
    # Only an exact match is refused: the password may CONTAIN parts of the name or email (owner
    # decision 2026-11-10), but it may not BE the email or the part before the "@".
    if email:
        local = email.split("@", 1)[0].strip().lower()
        if lowered.strip() in {email.strip().lower(), local}:
            problems.append("Do not use your email as your password.")
    return problems
