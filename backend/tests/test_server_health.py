"""Server checks in the daily check: new kinds of error (qa9), disk, memory, database size (qa11)."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from swing_trade_ml.core import error_watch as ew
from swing_trade_ml.core.config import settings
from swing_trade_ml.db.models.brain import BrainDailyCheck
from swing_trade_ml.services import brain_daily_check as daily
from swing_trade_ml.services import server_health as sh
from test_error_watch import FakeRedis

DAY = date(2026, 10, 14)
NOW = datetime(2026, 10, 14, 10, 50, tzinfo=UTC)  # 16:20 IST
GB = 1024**3

# ------------------------------------------------------------------------------------------ disk --


@pytest.mark.parametrize(
    "used,ok,level",
    [(50, True, "ok"), (80, True, "ok"), (81, False, "warn"), (90, False, "warn"), (91, False, "fail")],
)
def test_disk_thresholds(used, ok, level):
    c = sh.check_disk(usage=(100 * GB, used * GB, (100 - used) * GB), path="/")
    assert (c["ok"], c["level"]) == (ok, level) and f"{used}% used" in c["detail"]


def test_disk_reads_the_real_disk_here():
    c = sh.check_disk()
    assert c["name"] == "Server disk" and "used" in c["detail"]


# ---------------------------------------------------------------------------------------- memory --


def test_memory_warns_below_ten_percent_available():
    assert sh.check_memory({"MemTotal": 1000, "MemAvailable": 99})["level"] == "warn"
    assert sh.check_memory({"MemTotal": 1000, "MemAvailable": 100})["ok"]


def test_memory_skipped_without_meminfo(tmp_path):
    assert sh.read_meminfo(tmp_path / "missing") is None
    assert sh.check_memory(None) is None


def test_meminfo_is_parsed(tmp_path):
    f = tmp_path / "meminfo"
    f.write_text(
        "MemTotal:        4000000 kB\nMemFree:  100 kB\nMemAvailable:   300000 kB\nHugePages_Total: 0\n"
    )
    info = sh.read_meminfo(f)
    assert info["MemTotal"] == 4000000 and info["MemAvailable"] == 300000
    assert sh.check_memory(info)["level"] == "warn"  # 7.5%


# ------------------------------------------------------------------------------- database size --


def test_database_size_is_info(db_session):
    c = sh.check_database_size(db_session)
    assert c["ok"] and c["level"] == "info" and "GB" in c["detail"]


# --------------------------------------------------------------------------- new kinds of error --


def test_new_vs_known_kinds():
    window = [DAY]
    counts = {
        DAY - timedelta(days=3): {"old": 4},
        DAY: {"old": 1, "fresh": 3},
    }
    assert sh.new_error_kinds(counts, window) == {"fresh": 3}
    assert sh.new_error_kinds({DAY: {}}, window) == {}


def test_window_covers_every_day_since_the_last_check(db_session):
    assert sh.error_window(db_session, DAY) == [DAY]  # no earlier check
    db_session.add(
        BrainDailyCheck(day=DAY - timedelta(days=5), status="ok", checks=[], run={}, intraday={}, trial={})
    )
    db_session.flush()
    assert sh.error_window(db_session, DAY) == [DAY - timedelta(days=i) for i in (4, 3, 2, 1, 0)]


@pytest.fixture()
def watch_on(monkeypatch):
    monkeypatch.setattr(settings, "ERROR_WATCH_ENABLED", True)


def test_a_new_kind_warns_and_reaches_the_message(db_session, watch_on):
    r = FakeRedis()
    for _ in range(3):
        ew.record_error("swing_trade_ml.brain: run.failed (ValueError)", NOW - timedelta(hours=1), client=r)
    ew.record_error("known.one", NOW - timedelta(days=4), client=r)
    ew.record_error("known.one", NOW - timedelta(hours=1), client=r)
    out = sh.check_errors(db_session, DAY, client=r)
    assert (
        out[0]["name"] == "Errors logged" and out[0]["level"] == "info" and "4 error(s)" in out[0]["detail"]
    )
    assert [c["detail"] for c in out[1:]] == ["swing_trade_ml.brain: run.failed (ValueError) (3 times)"]
    msg = daily.message_if_problem({"day": DAY.isoformat(), "status": "check", "checks": out})
    assert "New kind of error: swing_trade_ml.brain: run.failed (ValueError) (3 times)" in msg
    assert "known.one" not in msg


def test_unreadable_redis_is_a_warning_not_a_crash(db_session, watch_on):
    out = sh.check_errors(db_session, DAY, client=FakeRedis(fail=True))
    assert len(out) == 1 and out[0]["level"] == "warn" and "Redis" in out[0]["detail"]


def test_error_watch_off_skips_the_check(db_session, monkeypatch):
    monkeypatch.setattr(settings, "ERROR_WATCH_ENABLED", False)
    assert sh.check_errors(db_session, DAY) is None


def test_server_checks_land_in_the_daily_check(db_session, tmp_path, monkeypatch):
    real = sh.check_disk
    monkeypatch.setattr(sh, "check_disk", lambda: real(usage=(100 * GB, 95 * GB, 5 * GB), path="/"))
    monkeypatch.setattr(sh, "read_meminfo", lambda: {"MemTotal": 100, "MemAvailable": 50})
    r = daily.compute(db_session, NOW, backup_dir=str(tmp_path))
    names = {c["name"]: c for c in r["checks"]}
    assert names["Server disk"]["level"] == "fail" and names["Server memory"]["ok"]
    assert names["Database size"]["level"] == "info"
    assert r["status"] == "check" and "Server disk" in daily.message_if_problem(r)


def test_a_broken_server_part_never_hides_the_rest(db_session, monkeypatch):
    def boom():
        raise OSError("no disk")

    monkeypatch.setattr(sh, "check_disk", boom)
    out = {c["name"]: c for c in sh.checks(db_session, DAY)}
    assert out["Server disk"]["level"] == "warn" and "OSError" in out["Server disk"]["detail"]
    assert "Database size" in out
