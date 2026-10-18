"""Error watch (qa9): ERROR log lines are counted by a stable kind in Redis, never by message, and a
Redis that is down never breaks logging."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

import structlog

from swing_trade_ml.core import error_watch as ew


class FakeRedis:
    """Just enough of redis-py: pipelines of hincrby / expire / hgetall."""

    def __init__(self, fail: bool = False):
        self.data: dict[str, dict[str, int]] = {}
        self.ttl: dict[str, int] = {}
        self.fail = fail
        self.calls = 0

    def pipeline(self, transaction=False):
        return _Pipe(self)


class _Pipe:
    def __init__(self, r):
        self.r, self.ops = r, []

    def hincrby(self, key, field, n):
        self.ops.append(("hincrby", key, field, n))

    def expire(self, key, seconds):
        self.ops.append(("expire", key, seconds))

    def hgetall(self, key):
        self.ops.append(("hgetall", key))

    def execute(self):
        self.r.calls += 1
        if self.r.fail:
            raise ConnectionError("redis down")
        out = []
        for op in self.ops:
            if op[0] == "hincrby":
                h = self.r.data.setdefault(op[1], {})
                h[op[2]] = h.get(op[2], 0) + op[3]
                out.append(h[op[2]])
            elif op[0] == "expire":
                self.r.ttl[op[1]] = op[2]
                out.append(True)
            else:
                out.append({k.encode(): str(v).encode() for k, v in self.r.data.get(op[1], {}).items()})
        return out


# -------------------------------------------------------------------------------- normalising --


def test_numbers_never_split_a_kind_and_messages_never_enter_it():
    a = ew.error_kind("swing_trade_ml.brain", "run 123 failed", "ValueError", {"error": "secret abc"})
    b = ew.error_kind("swing_trade_ml.brain", "run 98 failed", "ValueError", {"error": "other text"})
    assert a == b == "swing_trade_ml.brain: run # failed (ValueError)"
    assert "secret" not in a


def test_job_name_splits_job_failures():
    k = ew.error_kind("swing_trade_ml.workers.jobs", "job.failed", None, {"job": "brain_learn", "error": "x"})
    assert k == "swing_trade_ml.workers.jobs: job.failed job=brain_learn"


def test_stdlib_kind_is_logger_and_exception_only():
    assert ew.error_kind("apscheduler.executors.default", None, "KeyError") == (
        "apscheduler.executors.default (KeyError)"
    )
    assert ew.error_kind(None) == "unknown"


def test_kind_is_bounded():
    assert len(ew.error_kind("x" * 500, "y" * 500, "Z" * 500, {"job": "j" * 500})) <= ew.KIND_MAX


def test_error_day_ends_at_the_daily_check_time():
    # 16:19 IST -> today's check; 16:20 IST and later -> tomorrow's.
    assert ew.error_day(datetime(2026, 10, 14, 10, 49, tzinfo=UTC)) == date(2026, 10, 14)
    assert ew.error_day(datetime(2026, 10, 14, 10, 50, tzinfo=UTC)) == date(2026, 10, 15)
    assert ew.error_day(datetime(2026, 10, 13, 20, 0, tzinfo=UTC)) == date(2026, 10, 14)  # 01:30 IST


# ---------------------------------------------------------------------------------- recording --


def test_record_counts_per_day_with_expiry():
    r = FakeRedis()
    now = datetime(2026, 10, 14, 5, 0, tzinfo=UTC)
    assert ew.record_error("k1", now, client=r)
    assert ew.record_error("k1", now, client=r)
    key = ew.day_key(date(2026, 10, 14))
    assert r.data[key] == {"k1": 2} and r.ttl[key] == ew.KEEP_DAYS * 86400
    counts = ew.counts_for([date(2026, 10, 14), date(2026, 10, 13)], client=r)
    assert counts == {date(2026, 10, 14): {"k1": 2}, date(2026, 10, 13): {}}


def test_redis_down_is_swallowed_and_rests(monkeypatch):
    c = ew._Counter()
    down = FakeRedis(fail=True)
    monkeypatch.setattr(c, "_redis", lambda: down)
    assert c.record("k") is False  # no exception
    assert c.record("k") is False and down.calls == 1  # resting: Redis not asked again


def test_handler_never_raises_when_redis_is_down(monkeypatch):
    monkeypatch.setattr(ew, "record_error", lambda kind: (_ for _ in ()).throw(ConnectionError()))
    logger = logging.getLogger("errwatch.test.down")
    logger.propagate = False
    h = ew.ErrorWatchHandler()
    logger.addHandler(h)
    try:
        logger.error("boom")  # must not raise
    finally:
        logger.removeHandler(h)


def test_handler_counts_errors_only_and_reads_no_message(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(ew, "record_error", lambda kind: seen.append(kind))
    logger = logging.getLogger("errwatch.test.plain")
    logger.propagate = False
    logger.setLevel(logging.DEBUG)
    h = ew.ErrorWatchHandler()
    logger.addHandler(h)
    try:
        logger.warning("not counted")
        try:
            raise KeyError("token=abc123")
        except KeyError:
            logger.exception("secret %s", "abc123")
    finally:
        logger.removeHandler(h)
    assert seen == ["errwatch.test.plain (KeyError)"]


def test_structlog_error_reaches_the_handler_with_its_kind(monkeypatch):
    seen: list[str] = []
    monkeypatch.setattr(ew, "record_error", lambda kind: seen.append(kind))
    lines: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record):
            lines.append(record.getMessage())

    std = logging.getLogger("errwatch.test.structlog")
    std.propagate = False
    std.setLevel(logging.INFO)
    for h in (ew.ErrorWatchHandler(), Keep()):
        std.addHandler(h)
    log = structlog.wrap_logger(
        std,
        processors=[
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            ew.tag_error_kind,
            structlog.processors.format_exc_info,
            ew.with_error_kind(structlog.processors.JSONRenderer()),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    log.info("all.good", n=1)
    log.error("job.failed", job="brain_learn", error="password=hunter2")
    try:
        raise ValueError("x")
    except ValueError:
        log.exception("brain.run.failed", run_id="r-17")
    assert seen == [
        "errwatch.test.structlog: job.failed job=brain_learn",
        "errwatch.test.structlog: brain.run.failed (ValueError)",
    ]
    assert len(lines) == 3 and all("_error_kind" not in line for line in lines)


def test_install_adds_one_handler_only():
    root = logging.getLogger("errwatch.test.install")
    ew.install(root)
    ew.install(root)
    assert sum(isinstance(h, ew.ErrorWatchHandler) for h in root.handlers) == 1
    root.handlers.clear()
