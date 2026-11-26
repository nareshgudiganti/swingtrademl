"""#259: the shared HTTP helper, the adapter convention, and the no-call-without-a-timeout scan."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

import swing_trade_ml
from swing_trade_ml.core import adapters, http_client
from swing_trade_ml.core.http_client import HttpError

SRC = Path(swing_trade_ml.__file__).parent


def _transport(script):
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        nxt = script.pop(0) if script else 200
        if isinstance(nxt, Exception):
            raise nxt
        return httpx.Response(nxt, text="body")

    return httpx.MockTransport(handler), calls


def _get(script, **kw):
    transport, calls = _transport(script)
    slept: list[float] = []
    kw.setdefault("sleep", slept.append)
    try:
        return http_client.get("https://x.test/a", transport=transport, **kw), calls, slept
    except HttpError as exc:
        exc.calls, exc.slept = calls, slept  # type: ignore[attr-defined]
        raise


def test_success_first_try():
    resp, calls, slept = _get([200])
    assert resp.status_code == 200 and len(calls) == 1 and slept == []


def test_retries_twice_with_backoff_then_succeeds():
    resp, calls, slept = _get([httpx.ConnectError("x"), 503, 200])
    assert resp.status_code == 200 and len(calls) == 3
    assert len(slept) == 2 and slept[1] > slept[0]


def test_gives_up_after_two_retries_and_classifies():
    with pytest.raises(HttpError) as ei:
        _get([httpx.ReadTimeout("t")] * 3)
    assert ei.value.kind == "timeout" and ei.value.retryable and len(ei.value.calls) == 3


@pytest.mark.parametrize(
    ("status", "kind", "retryable"),
    [(500, "server", True), (429, "rate_limited", True), (404, "not_found", False), (403, "client", False)],
)
def test_status_classification(status, kind, retryable):
    with pytest.raises(HttpError) as ei:
        _get([status] * 3)
    assert ei.value.kind == kind and ei.value.retryable is retryable
    assert len(ei.value.calls) == (3 if retryable else 1)


def test_network_error_classified():
    with pytest.raises(HttpError) as ei:
        _get([httpx.ConnectError("x")] * 3)
    assert ei.value.kind == "network"


def test_allowed_status_returned_not_raised():
    resp, calls, _ = _get([404], ok_statuses=(404,))
    assert resp.status_code == 404 and len(calls) == 1


def test_error_text_does_not_carry_url_query():
    transport, _ = _transport([httpx.ConnectError("x")] * 3)
    with pytest.raises(HttpError) as ei:
        http_client.get("https://x.test/a?token=SECRET", transport=transport, sleep=lambda s: None)
    assert "SECRET" not in str(ei.value)


def test_always_sends_a_timeout():
    seen = {}

    class Spy(httpx.BaseTransport):
        def handle_request(self, request):
            seen.update(request.extensions.get("timeout", {}))
            return httpx.Response(200)

    http_client.get("https://x.test/", transport=Spy())
    assert seen.get("read") and seen.get("connect")


async def test_async_variant_retries():
    transport, calls = _transport([503, 200])
    slept: list[float] = []

    async def sleep(s):
        slept.append(s)

    resp = await http_client.aget("https://x.test/a", transport=transport, sleep=sleep)
    assert resp.status_code == 200 and len(calls) == 2 and len(slept) == 1


# ------------------------------------------------------------------ adapters
def test_fake_adapter_carries_fetched_at_and_health():
    now = datetime(2026, 11, 26, tzinfo=UTC)
    fake = adapters.FakeAdapter("demo", value=[1], clock=lambda: now)
    got = fake.fetch()
    assert got.ok and got.value == [1] and got.fetched_at == now
    assert fake.health().ok and isinstance(fake, adapters.Adapter)


def test_failure_gives_stale_result_with_last_good_value():
    t = [datetime(2026, 11, 26, 9, tzinfo=UTC)]
    fake = adapters.FakeAdapter("demo-stale", value="v1", clock=lambda: t[0])
    first = adapters.fetch_with_stale(fake)
    fake.fail_with = HttpError("timeout", "demo timed out")
    t[0] += timedelta(hours=2)
    second = adapters.fetch_with_stale(fake)
    assert not second.ok and second.stale and second.value == "v1"
    assert second.fetched_at == first.fetched_at  # the age of the data, not of the failure
    assert "timed out" in second.error
    assert not fake.health().ok


def test_failure_with_no_last_good_value_is_empty_not_raised():
    fake = adapters.FakeAdapter("demo-nolast", value=1, fail_with=HttpError("network", "down"))
    got = adapters.fetch_with_stale(fake)
    assert got.value is None and got.stale and got.fetched_at is None


def test_one_failing_provider_does_not_affect_another():
    bad = adapters.FakeAdapter("bad", value=1, fail_with=HttpError("server", "500"))
    good = adapters.FakeAdapter("good", value=2)
    assert adapters.fetch_with_stale(bad).stale
    assert adapters.fetch_with_stale(good).ok


def test_switched_off_module_is_not_fetched():
    class Off:
        def enabled(self, module_id, *, fresh=False):
            return False

    fake = adapters.FakeAdapter("demo", value=1, module_id="mutual_funds")
    got = adapters.fetch_with_stale(fake, switches=Off())
    assert got.disabled and fake.calls == 0


def test_real_registry_switch_is_honoured_and_unknown_module_is_on():
    fake = adapters.FakeAdapter("demo", value=1, module_id="no.such.module")
    assert adapters.fetch_with_stale(fake).ok


# ---------------------------------------------------- migrated callers
@pytest.fixture
def wire(monkeypatch):
    def _install(script):
        transport, calls = _transport(script)
        monkeypatch.setattr(http_client, "_TRANSPORT", transport)
        monkeypatch.setattr(http_client, "_sleep", lambda s: None)
        return calls

    return _install


def test_market_feeds_fetch_keeps_404_as_none(wire):
    from swing_trade_ml.services import market_feeds

    wire([404])
    assert market_feeds.fetch("https://nse.test/x") is None


def test_market_feeds_fetch_retries_then_raises(wire):
    from swing_trade_ml.services import market_feeds

    calls = wire([503] * 3)
    with pytest.raises(HttpError):
        market_feeds.fetch("https://nse.test/x")
    assert len(calls) == 3


def test_market_feeds_fetch_recovers_after_a_blip(wire):
    from swing_trade_ml.services import market_feeds

    wire([httpx.ConnectError("x"), 200])
    assert market_feeds.fetch("https://nse.test/x") == b"body"


def test_company_filings_fetch_retries_then_raises(wire):
    from swing_trade_ml.services import company_filings

    calls = wire([503] * 3)
    with pytest.raises(HttpError):
        company_filings.fetch_nse("KEI")
    assert len(calls) == 3


def test_amfi_download_failure_raises_http_error(wire):
    from swing_trade_ml.services.finance import mutual_funds

    calls = wire([500] * 3)
    with pytest.raises(HttpError):
        mutual_funds.sync_nav_snapshot(None)  # type: ignore[arg-type]
    assert len(calls) == 3


# ------------------------------------------------------------ the timeout scan
#: file -> reason. These callers are not migrated in this PR; the scan still needs them named.
SCAN_ALLOW: dict[str, str] = {
    "notifications/telegram.py": "already passes a timeout; migrate after #556 merges",
    "brokers/kite.py": "owner-gated (order placement); not migrated",
    "services/billing/razorpay.py": "owner-gated (billing); not migrated",
    "api/v1/endpoints/auth.py": "owner-gated (auth); not migrated",
    "services/email/senders.py": "already passes a timeout; not in #259's list",
    "services/execution.py": "only classifies requests exceptions; makes no call",
    "core/http_client.py": "the helper itself: always passes a timeout",
}

_METHODS = {"get", "post", "put", "patch", "delete", "head", "request", "stream", "Client", "AsyncClient"}


def calls_without_timeout(source: str) -> list[int]:
    """Line numbers of requests/httpx calls and urlopen calls that pass no `timeout=`."""
    lines = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        base, attr = node.func.value, node.func.attr
        hit = (isinstance(base, ast.Name) and base.id in {"requests", "httpx"} and attr in _METHODS) or (
            attr == "urlopen"
        )
        if hit and not any(k.arg == "timeout" or k.arg is None for k in node.keywords):
            lines.append(node.lineno)
    return lines


def test_scan_catches_a_missing_timeout():
    assert calls_without_timeout("import httpx\nhttpx.get('u')\n") == [2]
    assert calls_without_timeout("import requests\nrequests.post('u', json={})\n") == [2]
    assert calls_without_timeout("import httpx\nhttpx.Client(headers={})\n") == [2]
    assert calls_without_timeout("import urllib.request\nurllib.request.urlopen('u')\n") == [2]
    assert calls_without_timeout("import httpx\nhttpx.get('u', timeout=5)\n") == []


def test_no_outbound_http_call_in_src_lacks_a_timeout():
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        rel = path.relative_to(SRC).as_posix()
        if rel in SCAN_ALLOW:
            continue
        offenders += [f"{rel}:{n}" for n in calls_without_timeout(path.read_text(encoding="utf-8"))]
    assert not offenders, f"outbound HTTP call without a timeout: {offenders}"


def test_migrated_callers_use_the_helper():
    for rel in (
        "services/market_feeds.py",
        "services/company_filings.py",
        "services/finance/mutual_funds.py",
    ):
        text = (SRC / rel).read_text(encoding="utf-8")
        assert "http_client" in text and "httpx.get(" not in text and "httpx.Client(" not in text, rel
