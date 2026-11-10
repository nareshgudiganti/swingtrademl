"""Tidy-up and checks for a person's name and Indian mobile number.

Pure helpers, no database. The mobile number is stored UNVERIFIED (no SMS code):
it is a contact detail and the planned login key, nothing more.
"""

from __future__ import annotations

import re
import unicodedata

NAME_MIN = 2
NAME_MAX = 80

_MOBILE_SEPARATORS = re.compile(r"[\s\-().]")
_MOBILE_OK = re.compile(r"^[6-9]\d{9}$")


def normalise_mobile(raw: object) -> str:
    """Return the canonical 10-digit Indian mobile, or raise ValueError."""
    if not isinstance(raw, str):
        raise ValueError("Mobile number must be text")
    text = _MOBILE_SEPARATORS.sub("", raw)
    if text.startswith("+"):
        if not text.startswith("+91"):
            raise ValueError("Only Indian (+91) mobile numbers are supported")
        text = text[3:]
    elif text.startswith("0091"):
        text = text[4:]
    elif len(text) == 12 and text.startswith("91"):
        text = text[2:]
    elif len(text) == 11 and text.startswith("0"):
        text = text[1:]
    if not text.isascii() or not _MOBILE_OK.match(text):
        raise ValueError("Enter a 10-digit Indian mobile number starting with 6, 7, 8 or 9")
    if len(set(text)) == 1:
        raise ValueError("That mobile number is not valid")
    return text


def normalise_full_name(raw: object) -> str:
    """Trim, collapse spaces; 2-80 characters; no control characters; not digits only."""
    if not isinstance(raw, str):
        raise ValueError("Name must be text")
    if any(unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co") and not ch.isspace() for ch in raw):
        raise ValueError("Name contains characters that are not allowed")
    text = " ".join(raw.split())
    if len(text) < NAME_MIN:
        raise ValueError(f"Name must be at least {NAME_MIN} characters")
    if len(text) > NAME_MAX:
        raise ValueError(f"Name must be at most {NAME_MAX} characters")
    if all(ch.isdigit() or ch.isspace() for ch in text):
        raise ValueError("Name cannot be only numbers")
    return text
