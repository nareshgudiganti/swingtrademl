"""Alert settings (tracker ux3): the pure rules. No database, no network,
and never a real Telegram message."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.notifications import alert_policy as policy
from swing_trade_ml.notifications.alert_policy import AlertPrefs

IST = ZoneInfo("Asia/Kolkata")


def ist(h: int, m: int = 0, day: int = 20) -> datetime:
    return datetime(2026, 10, day, h, m, tzinfo=IST)


# ------------------------------------------------------------ catalogue --


def test_every_switchable_type_has_plain_words():
    for t in policy.SWITCHABLE:
        assert t.label and t.explain
    for t in policy.ALWAYS_ON:
        assert t.label and t.explain


def test_safety_types_are_never_switchable():
    keys = {t.key for t in policy.SWITCHABLE}
    assert keys.isdisjoint({t.key for t in policy.ALWAYS_ON})
    # Nothing that sells, moves real money, stops buying or reports a breakage can be switched off.
    for word in ("sell", "exit", "stop", "real", "login_problem", "error", "halt", "fail"):
        assert not any(word in k for k in keys), word


# --------------------------------------------------------------- route --


@pytest.mark.parametrize("kind", [t.key for t in policy.SWITCHABLE])
def test_each_informational_type_respects_on_off(kind):
    on = AlertPrefs()
    off = AlertPrefs(disabled=frozenset({kind}))
    assert policy.route(kind, on, ist(12)) == "send"
    assert policy.route(kind, off, ist(12)) == "drop"
    # Turning one type off leaves the others alone.
    for other in policy.SWITCHABLE_KEYS - {kind}:
        assert policy.route(other, off, ist(12)) == "send"


@pytest.mark.parametrize("kind", [None, "sells", "real_orders", "risk_halts", "anything-unknown"])
def test_safety_and_untagged_alerts_always_send(kind):
    everything_off = AlertPrefs(
        disabled=frozenset(
            policy.SWITCHABLE_KEYS | {"sells", "real_orders", "risk_halts", "anything-unknown"}
        ),
        quiet_enabled=True,
        quiet_start=time(0, 0),
        quiet_end=time(23, 59),
        digest_enabled=True,
    )
    assert policy.route(kind, everything_off, ist(3)) == "send"


def test_no_settings_means_send():
    assert policy.route("trade_ideas", None, ist(3)) == "send"


def test_quiet_hours_hold_informational_alerts():
    prefs = AlertPrefs(quiet_enabled=True, quiet_start=time(22), quiet_end=time(7))
    assert policy.route("trade_ideas", prefs, ist(23)) == "hold"
    assert policy.route("trade_ideas", prefs, ist(12)) == "send"
    # Switched off beats quiet hours: nothing is held for a type the owner does not want.
    off = AlertPrefs(
        disabled=frozenset({"trade_ideas"}), quiet_enabled=True, quiet_start=time(22), quiet_end=time(7)
    )
    assert policy.route("trade_ideas", off, ist(23)) == "drop"


def test_digest_holds_informational_alerts_any_time():
    prefs = AlertPrefs(digest_enabled=True)
    assert policy.route("daily_summary", prefs, ist(12)) == "hold"


# --------------------------------------------------------- quiet hours --


@pytest.mark.parametrize(
    ("h", "m", "quiet"),
    [
        (21, 59, False),
        (22, 0, True),  # the start minute is quiet
        (23, 30, True),
        (0, 0, True),
        (6, 59, True),
        (7, 0, False),  # the end minute is not
        (12, 0, False),
    ],
)
def test_overnight_window_in_ist(h, m, quiet):
    prefs = AlertPrefs(quiet_enabled=True, quiet_start=time(22), quiet_end=time(7))
    assert policy.in_quiet_hours(prefs, ist(h, m)) is quiet


@pytest.mark.parametrize(("h", "quiet"), [(12, False), (13, True), (14, True), (15, False)])
def test_same_day_window(h, quiet):
    prefs = AlertPrefs(quiet_enabled=True, quiet_start=time(13), quiet_end=time(15))
    assert policy.in_quiet_hours(prefs, ist(h)) is quiet


def test_quiet_hours_use_ist_not_utc():
    prefs = AlertPrefs(quiet_enabled=True, quiet_start=time(22), quiet_end=time(7))
    # 17:00 UTC is 22:30 IST: quiet. 02:00 UTC is 07:30 IST: not quiet.
    assert policy.in_quiet_hours(prefs, datetime(2026, 10, 20, 17, 0, tzinfo=UTC)) is True
    assert policy.in_quiet_hours(prefs, datetime(2026, 10, 20, 2, 0, tzinfo=UTC)) is False


def test_quiet_hours_switched_off_or_empty_window_is_never_quiet():
    assert (
        policy.in_quiet_hours(
            AlertPrefs(quiet_enabled=False, quiet_start=time(0), quiet_end=time(23, 59)), ist(3)
        )
        is False
    )
    assert (
        policy.in_quiet_hours(AlertPrefs(quiet_enabled=True, quiet_start=time(9), quiet_end=time(9)), ist(9))
        is False
    )


# ----------------------------------------------------------------- flush --


def test_flush_after_quiet_hours_end():
    prefs = AlertPrefs(quiet_enabled=True, quiet_start=time(22), quiet_end=time(7))
    held_at = ist(23, day=19)
    assert policy.due(prefs, ist(6, 55), held_at) is False
    assert policy.due(prefs, ist(7, 0), held_at) is True


def test_nothing_held_nothing_due():
    assert policy.due(AlertPrefs(), ist(12), None) is False


def test_digest_goes_once_a_day_at_its_time():
    prefs = AlertPrefs(digest_enabled=True, digest_time=time(18))
    held_at = ist(10)
    assert policy.due(prefs, ist(17, 55), held_at) is False
    assert policy.due(prefs, ist(18, 0), held_at) is True
    sent_today = AlertPrefs(digest_enabled=True, digest_time=time(18), last_digest_on=date(2026, 10, 20))
    assert policy.due(sent_today, ist(19), ist(18, 30)) is False
    # The next day's digest picks up what came after.
    assert policy.due(sent_today, ist(18, day=21), ist(18, 30)) is True


def test_digest_waits_for_quiet_hours_to_end():
    prefs = AlertPrefs(
        digest_enabled=True,
        digest_time=time(18),
        quiet_enabled=True,
        quiet_start=time(17),
        quiet_end=time(19),
    )
    assert policy.due(prefs, ist(18, 30), ist(10)) is False
    assert policy.due(prefs, ist(19), ist(10)) is True


def test_a_held_message_is_never_stuck_more_than_a_day():
    prefs = AlertPrefs(digest_enabled=True, digest_time=time(18), last_digest_on=date(2026, 10, 20))
    assert policy.due(prefs, ist(12, day=21), ist(10, day=20)) is True


def test_digest_time_inside_quiet_hours_is_refused():
    with pytest.raises(ValueError, match="quiet hours"):
        policy.validate(
            AlertPrefs(
                quiet_enabled=True,
                quiet_start=time(22),
                quiet_end=time(7),
                digest_enabled=True,
                digest_time=time(23),
            )
        )
    policy.validate(
        AlertPrefs(
            quiet_enabled=True,
            quiet_start=time(22),
            quiet_end=time(7),
            digest_enabled=True,
            digest_time=time(18),
        )
    )


def test_unknown_alert_type_is_refused_on_save():
    with pytest.raises(ValueError, match="sells"):
        policy.validate(AlertPrefs(disabled=frozenset({"sells"})))


@pytest.mark.parametrize("bad", ["25:00", "7", "07:60", "", "ab:cd", None])
def test_bad_times_are_refused(bad):
    with pytest.raises(ValueError):
        policy.parse_hhmm(bad)


def test_parse_hhmm():
    assert policy.parse_hhmm("07:05") == time(7, 5)


# ---------------------------------------------------------------- digest --


def test_digest_text_collects_every_message_once():
    items = [(1, ist(9), "first"), (2, ist(10), "second"), (3, ist(11), "third")]
    chunks = policy.compose_digest(items, digest=True)
    assert len(chunks) == 1
    text, ids = chunks[0]
    assert ids == [1, 2, 3]
    assert text.count("first") == 1 and text.count("second") == 1 and text.count("third") == 1
    assert "3 messages" in text


def test_long_digest_splits_under_the_telegram_limit_without_losing_any():
    items = [(i, ist(9) + timedelta(minutes=i), "x" * 900) for i in range(10)]
    chunks = policy.compose_digest(items, digest=False)
    assert len(chunks) > 1
    assert all(len(text) <= policy.MAX_CHUNK for text, _ in chunks)
    assert [i for _, ids in chunks for i in ids] == list(range(10))
