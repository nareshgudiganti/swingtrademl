"""Which Telegram alerts the owner may switch off, quiet hours and the daily
digest (tracker ux3). Pure rules: no database, no network.

The one rule that matters most: only messages a call site tags with a
SWITCHABLE kind can ever be dropped or held. Everything else, including any
message with no kind or an unknown kind, is sent at once, as before. So a
safety alert can only become switchable by someone deliberately tagging it,
and a typo fails toward telling the owner.

Settings change only whether and when a message is sent. They are never read
by trading, sizing, stops, exits, limits or the brain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from html import escape
from typing import Literal
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

#: Telegram refuses messages over 4096 characters; the notifier cuts at 4000.
MAX_CHUNK = 3900
#: A held message is sent at the latest this long after it was held (outside quiet hours),
#: whatever the digest settings say: held, never lost.
MAX_HOLD = timedelta(hours=26)


@dataclass(frozen=True)
class AlertType:
    key: str
    label: str
    explain: str


TRADE_IDEAS = "trade_ideas"
PAPER_BUYS = "paper_buys"
HOLDING_WARNINGS = "holding_warnings"
DAILY_SUMMARY = "daily_summary"
WEEKLY_REPORT = "weekly_report"
APP_STATUS = "app_status"

SWITCHABLE: tuple[AlertType, ...] = (
    AlertType(
        TRADE_IDEAS,
        "New buy ideas",
        "A message when the bot or the brain finds a stock worth buying, or a brain idea is waiting for "
        "your OK. Turning it off only stops the phone message: the ideas still appear in the app and "
        "nothing about what is bought changes.",
    ),
    AlertType(
        PAPER_BUYS,
        "Practice buys",
        "A message when the bot buys a stock with pretend (paper) money. Buys with real money always "
        "message you.",
    ),
    AlertType(
        HOLDING_WARNINGS,
        "Score slipping on a stock you hold",
        "An early heads-up when the model's score for a stock you hold gets weaker. It is a warning, "
        "not a sell: the stop-loss keeps protecting the stock, and every sell message always reaches you.",
    ),
    AlertType(
        DAILY_SUMMARY,
        "End-of-day summary",
        "One message after the market closes with the day's profit or loss and what is held.",
    ),
    AlertType(
        WEEKLY_REPORT,
        "Weekly brain report",
        "Saturday's checklist on how the brain did this week. The same report is on the System page.",
    ),
    AlertType(
        APP_STATUS,
        "App restarted / Zerodha login worked",
        "A message when the app starts or stops (for example after an update) and when a Zerodha login "
        "succeeded. Login problems always message you.",
    ),
)
SWITCHABLE_KEYS: frozenset[str] = frozenset(t.key for t in SWITCHABLE)

#: Shown on the settings page as "always on", with the reason. Never consulted by `route`:
#: these messages are sent without a kind, so they always go straight out.
ALWAYS_ON: tuple[AlertType, ...] = (
    AlertType(
        "sells",
        "Sells and stop-losses",
        "When a stock you hold hits its stop-loss, target or time limit, is sold, or should be sold. "
        "You may need to act quickly, so this can't be switched off or delayed.",
    ),
    AlertType(
        "real_orders",
        "Real-money orders",
        "Every real buy or sell sent to your Zerodha account, any order Zerodha refused or cancelled, and "
        "an approved idea that could not be bought. Real money is involved.",
    ),
    AlertType(
        "risk_halts",
        "Safety stops on buying",
        "When a safety rule stops new buys, for example the account fell 15% from its best value. "
        "You need to know the bot has stopped buying.",
    ),
    AlertType(
        "login_problems",
        "Zerodha login problems",
        "When the bot is not logged in to Zerodha. Without it prices stop updating and stop-losses are "
        "not checked.",
    ),
    AlertType(
        "system_problems",
        "Something broke",
        "A job failed, market data is missing, the server disk is filling up, or errors are piling up. "
        "These need fixing before they cost money.",
    ),
)


@dataclass(frozen=True)
class AlertPrefs:
    disabled: frozenset[str] = field(default_factory=frozenset)
    quiet_enabled: bool = False
    quiet_start: time = time(22, 0)
    quiet_end: time = time(7, 0)
    digest_enabled: bool = False
    digest_time: time = time(18, 0)
    last_digest_on: date | None = None


Route = Literal["send", "drop", "hold"]


def parse_hhmm(value: object) -> time:
    """'07:05' -> time(7, 5). Anything else raises ValueError."""
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        raise ValueError(f"Time must look like 07:30, not {value!r}")
    hh, mm = value[:2], value[3:]
    if not (hh.isdigit() and mm.isdigit()) or int(hh) > 23 or int(mm) > 59:
        raise ValueError(f"Time must look like 07:30, not {value!r}")
    return time(int(hh), int(mm))


def hhmm(t: time) -> str:
    return f"{t.hour:02d}:{t.minute:02d}"


def _ist(now: datetime) -> datetime:
    return now.astimezone(IST)


def _in_window(t: time, start: time, end: time) -> bool:
    if start == end:
        return False
    if start < end:
        return start <= t < end
    return t >= start or t < end  # overnight, e.g. 22:00-07:00


def in_quiet_hours(prefs: AlertPrefs, now: datetime) -> bool:
    """Start minute is quiet, end minute is not. Times are IST."""
    if not prefs.quiet_enabled:
        return False
    return _in_window(_ist(now).time().replace(second=0, microsecond=0), prefs.quiet_start, prefs.quiet_end)


def route(kind: str | None, prefs: AlertPrefs | None, now: datetime) -> Route:
    """send now, drop (owner switched this type off) or hold (quiet hours / digest)."""
    if kind not in SWITCHABLE_KEYS or prefs is None:
        return "send"
    if kind in prefs.disabled:
        return "drop"
    if prefs.digest_enabled or in_quiet_hours(prefs, now):
        return "hold"
    return "send"


def due(prefs: AlertPrefs, now: datetime, oldest_held_at: datetime | None) -> bool:
    """Is it time to send what is held? Never during quiet hours. Without the digest, as soon as
    quiet hours end; with it, once a day at the digest time. Nothing waits longer than MAX_HOLD."""
    if oldest_held_at is None or in_quiet_hours(prefs, now):
        return False
    if not prefs.digest_enabled or now - oldest_held_at >= MAX_HOLD:
        return True
    local = _ist(now)
    if prefs.last_digest_on == local.date():
        return False
    return local.time() >= prefs.digest_time


def validate(prefs: AlertPrefs) -> None:
    """Refuse settings that could never work. Raises ValueError with a plain reason."""
    unknown = sorted(prefs.disabled - SWITCHABLE_KEYS)
    if unknown:
        raise ValueError(f"These alerts can't be switched off: {', '.join(unknown)}")
    if (
        prefs.digest_enabled
        and prefs.quiet_enabled
        and _in_window(prefs.digest_time, prefs.quiet_start, prefs.quiet_end)
    ):
        raise ValueError("Pick a digest time outside your quiet hours, or it would never be sent.")


def compose_digest(
    items: Sequence[tuple[int, datetime, str]], *, digest: bool
) -> list[tuple[str, list[int]]]:
    """Held messages -> one or more Telegram texts, each under MAX_CHUNK, with the ids each carries.
    Message texts are already Telegram HTML, so they are not escaped again."""
    if not items:
        return []
    n = len(items)
    title = "📬 <b>Your alert digest</b>" if digest else "🌙 <b>Held during your quiet hours</b>"
    header = f"{title} · {n} message{'s' if n != 1 else ''}"
    chunks: list[tuple[str, list[int]]] = []
    current, ids = header, []
    for item_id, at, text in items:
        piece = f"<i>{escape(_ist(at).strftime('%d %b, %H:%M'))}</i>\n{text}"
        if ids and len(current) + 2 + len(piece) > MAX_CHUNK:
            chunks.append((current, ids))
            current, ids = f"{title} (continued)", []
        current = f"{current}\n\n{piece}"
        ids.append(item_id)
    chunks.append((current, ids))
    return chunks
