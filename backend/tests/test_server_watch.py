"""Server watch (ops): memory samples, early warning, and a safe restart of a bloated process.

Housekeeping only: none of this touches orders, the brain, sizing, stops or limits.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from swing_trade_ml.services import server_watch as sw

IST = ZoneInfo("Asia/Kolkata")
GB = 1024**3

# Monday 26 Oct 2026, in and out of market hours (IST).
MARKET = datetime(2026, 10, 26, 11, 0, tzinfo=IST)
EVENING = datetime(2026, 10, 26, 22, 30, tzinfo=IST)
SUNDAY = datetime(2026, 10, 25, 12, 0, tzinfo=IST)


class FakeRedis:
    def __init__(self) -> None:
        self.lists: dict[str, list[str]] = {}
        self.keys: dict[str, str] = {}

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)

    def ltrim(self, key, start, stop):
        self.lists[key] = self.lists.get(key, [])[start : stop + 1]

    def lrange(self, key, start, stop):
        return self.lists.get(key, [])[start : stop + 1]

    def set(self, key, value, nx=False, ex=None):
        if nx and key in self.keys:
            return None
        self.keys[key] = value
        return True


class DownRedis:
    def __getattr__(self, name):
        def boom(*a, **k):
            raise ConnectionError("redis is down")

        return boom


def _sample(
    role="api", rss_mb=800, avail=2000, total=3900, uptime=7200, ts=None, swap_total=4096, swap_free=4000
):
    return {
        "ts": (ts or datetime(2026, 10, 26, 6, 0, tzinfo=UTC)).isoformat(),
        "role": role,
        "rss_mb": rss_mb,
        "mem_total_mb": total,
        "mem_available_mb": avail,
        "swap_total_mb": swap_total,
        "swap_free_mb": swap_free,
        "uptime_s": uptime,
    }


# --------------------------------------------------------------------------------- the figures --


def test_process_rss_reads_vmrss(tmp_path):
    f = tmp_path / "status"
    f.write_text("Name:\tpython\nVmRSS:\t  1048576 kB\nThreads:\t4\n")
    assert sw.process_rss(f) == 1048576 * 1024


def test_process_rss_is_none_without_proc(tmp_path):
    assert sw.process_rss(tmp_path / "missing") is None


def test_sample_converts_to_mb():
    s = sw.take_sample(
        "worker",
        now=datetime(2026, 10, 26, 6, 0, tzinfo=UTC),
        meminfo={
            "MemTotal": 4_000_000,
            "MemAvailable": 1_000_000,
            "SwapTotal": 4_194_304,
            "SwapFree": 4_000_000,
        },
        rss=512 * 1024**2,
        uptime=90.4,
    )
    assert s["role"] == "worker" and s["rss_mb"] == 512 and s["uptime_s"] == 90
    assert s["mem_total_mb"] == round(4_000_000 / 1024) and s["mem_available_mb"] == round(1_000_000 / 1024)
    assert s["swap_total_mb"] == 4096


def test_sample_without_proc_has_no_figures():
    s = sw.take_sample("api", meminfo={}, rss=None)
    assert s["rss_mb"] is None and s["mem_total_mb"] is None


# ------------------------------------------------------------------------------------- the store --


def test_store_and_read_newest_first_and_trimmed():
    fake = FakeRedis()
    for i in range(sw.MAX_SAMPLES + 5):
        assert sw.store_sample(_sample(rss_mb=i), lambda: fake)
    got = sw.read_samples(3, lambda: fake)
    assert [g["rss_mb"] for g in got] == [sw.MAX_SAMPLES + 4, sw.MAX_SAMPLES + 3, sw.MAX_SAMPLES + 2]
    assert len(fake.lists[sw.SAMPLES_KEY]) == sw.MAX_SAMPLES


def test_redis_down_never_raises():
    assert sw.store_sample(_sample(), DownRedis) is False
    assert sw.read_samples(5, DownRedis) == []


# ---------------------------------------------------------------------------------- the warning --


def test_no_warning_when_memory_is_fine_or_unknown():
    assert sw.low_memory_text(_sample(avail=1500)) is None
    assert sw.low_memory_text({"role": "api"}) is None


def test_warning_text_when_short_of_memory():
    text = sw.low_memory_text(_sample(avail=300))
    assert "Server memory is low" in text and "300 MB of 3900 MB" in text


def test_warning_says_when_there_is_no_swap():
    text = sw.low_memory_text(_sample(avail=300, swap_total=0, swap_free=0))
    assert "no swap" in text


# ---------------------------------------------------------------------------------- the restart --


@pytest.mark.parametrize("role", ["api", "worker"])
def test_small_process_is_left_alone(role):
    assert sw.restart_reason(role, 1 * GB, 99999, EVENING) is None


@pytest.mark.parametrize("role", ["api", "worker"])
def test_a_young_process_is_never_restarted(role):
    assert sw.restart_reason(role, int(2.1 * GB), sw.MIN_UPTIME_SECONDS - 1, EVENING) is None


def test_unknown_size_is_left_alone():
    assert sw.restart_reason("api", None, 99999, EVENING) is None


def test_api_restarts_when_big_even_in_market_hours():
    assert "memory high" in sw.restart_reason("api", int(1.75 * GB), 99999, MARKET)


def test_worker_waits_for_a_quiet_moment_when_only_high():
    big = int(1.75 * GB)
    assert sw.restart_reason("worker", big, 99999, MARKET) is None  # market hours
    assert sw.restart_reason("worker", big, 99999, EVENING, job_running=True) is None  # a job is running
    assert "memory high" in sw.restart_reason("worker", big, 99999, EVENING)
    assert "memory high" in sw.restart_reason("worker", big, 99999, SUNDAY)  # weekend is quiet


def test_critical_size_restarts_the_worker_at_once_even_in_market_hours():
    assert "memory critical" in sw.restart_reason("worker", int(2.0 * GB), 99999, MARKET, job_running=True)


# --------------------------------------------------------------------------------- run_watch --


def _watch(sample, *, role="api", now=EVENING, fake=None):
    fake = fake or FakeRedis()
    told: list[str] = []
    killed: list[str] = []
    out = sw.run_watch(
        role,
        now=now,
        sample=sample,
        notify=told.append,
        kill=killed.append,
        client_factory=lambda: fake,
    )
    return out, told, killed, fake


def test_healthy_sample_is_stored_and_nothing_else_happens():
    out, told, killed, fake = _watch(_sample())
    assert out["stored"] and not out["warned"] and out["restart"] is None
    assert told == [] and killed == []
    assert json.loads(fake.lists[sw.SAMPLES_KEY][0])["role"] == "api"


def test_low_memory_warns_once_per_cooldown():
    fake = FakeRedis()
    first, told1, _, _ = _watch(_sample(avail=200), fake=fake)
    second, told2, _, _ = _watch(_sample(avail=200), fake=fake)
    assert first["warned"] and len(told1) == 1
    assert not second["warned"] and told2 == []


def test_big_api_is_restarted_and_the_owner_is_told():
    out, told, killed, _ = _watch(_sample(rss_mb=1800), role="api", now=MARKET)
    assert out["restart"].startswith("memory high")
    assert len(killed) == 1 and any("Restarting the api" in t for t in told)


def test_big_worker_in_market_hours_is_not_restarted(monkeypatch):
    monkeypatch.setattr(sw, "_job_running", lambda: False)
    out, _, killed, _ = _watch(_sample(role="worker", rss_mb=1800), role="worker", now=MARKET)
    assert out["restart"] is None and killed == []


def test_big_worker_in_the_evening_is_restarted(monkeypatch):
    monkeypatch.setattr(sw, "_job_running", lambda: False)
    out, _, killed, _ = _watch(_sample(role="worker", rss_mb=1800), role="worker", now=EVENING)
    assert out["restart"] and len(killed) == 1


def test_big_worker_with_a_job_running_waits(monkeypatch):
    monkeypatch.setattr(sw, "_job_running", lambda: True)
    out, _, killed, _ = _watch(_sample(role="worker", rss_mb=1800), role="worker", now=EVENING)
    assert out["restart"] is None and killed == []


def test_a_failing_notifier_does_not_stop_the_restart():
    def boom(_):
        raise RuntimeError("telegram down")

    killed: list[str] = []
    out = sw.run_watch(
        "api",
        now=MARKET,
        sample=_sample(rss_mb=2000, avail=200),
        notify=boom,
        kill=killed.append,
        client_factory=FakeRedis,
    )
    assert out["restart"] and len(killed) == 1


def test_redis_down_still_warns_and_restarts():
    told: list[str] = []
    killed: list[str] = []
    out = sw.run_watch(
        "api",
        now=MARKET,
        sample=_sample(rss_mb=2000, avail=200),
        notify=told.append,
        kill=killed.append,
        client_factory=DownRedis,
    )
    assert out["stored"] is False and out["warned"] is True and len(killed) == 1


# ----------------------------------------------------------------------------------- summary --


def test_summary_reports_growth_since_the_last_restart():
    t0 = datetime(2026, 10, 26, 0, 0, tzinfo=UTC)
    rows = [  # oldest first; the process restarted once (uptime fell back)
        _sample(rss_mb=1500, uptime=40000, ts=t0),
        _sample(rss_mb=300, uptime=300, ts=t0 + timedelta(minutes=5)),
        _sample(rss_mb=400, uptime=3900, ts=t0 + timedelta(hours=1, minutes=5)),
        _sample(rss_mb=500, uptime=7500, ts=t0 + timedelta(hours=2, minutes=5)),
    ]
    out = sw.summarize(list(reversed(rows)))
    assert out["api"]["restarts_in_window"] == 1
    assert out["api"]["growth_mb_per_hour"] == pytest.approx(200 / (7200 / 3600))
    assert out["api"]["latest"]["rss_mb"] == 500


def test_summary_keeps_roles_apart_and_handles_a_single_sample():
    out = sw.summarize([_sample(role="worker"), _sample(role="api")])
    assert set(out) == {"api", "worker"} and out["api"]["growth_mb_per_hour"] is None


# ---------------------------------------------------------------------------------- endpoint --

URL = "/api/v1/admin/server-health"


@pytest.fixture
def _samples(monkeypatch):
    rows = [_sample(role="worker", rss_mb=900, uptime=7200), _sample(role="api", rss_mb=800, uptime=3600)]
    monkeypatch.setattr(sw, "read_samples", lambda limit=300, client_factory=None: rows[:limit])
    return rows


def test_api_key_reads_the_samples(client, _samples):
    r = client.get(URL, headers={"X-API-Key": "test-api-key"})
    assert r.status_code == 200
    body = r.json()
    assert body["samples_available"] is True and len(body["samples"]) == 2
    assert set(body["summary"]) == {"api", "worker"} and body["restart_above_mb"] > 1000


def test_no_credentials_is_refused(client, _samples):
    assert client.get(URL).status_code == 401


def test_empty_when_redis_has_nothing(client, monkeypatch):
    monkeypatch.setattr(sw, "read_samples", lambda limit=300, client_factory=None: [])
    body = client.get(URL, headers={"X-API-Key": "test-api-key"}).json()
    assert body["samples_available"] is False and body["summary"] == {}
