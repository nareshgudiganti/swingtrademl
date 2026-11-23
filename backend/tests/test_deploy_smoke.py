"""infra/deploy/smoke.py (tracker qa2): the after-deploy smoke test's logic, with no network."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import ClassVar

_PATH = Path(__file__).resolve().parents[2] / "infra" / "deploy" / "smoke.py"
_spec = importlib.util.spec_from_file_location("deploy_smoke", _PATH)
smoke = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = smoke  # dataclasses look the module up while it loads
_spec.loader.exec_module(smoke)

BASE = "https://example.test"
PAGE = smoke.Response(200, "text/html; charset=utf-8", b'<html><div id="root"></div></html>')
STATUS_PAPER = json.dumps({"trading_mode": "paper", "live_trading_enabled": False}).encode()


def ready_body(ready=True, database=True, scheduler=True) -> bytes:
    """What /api/v1/ready answers (schemas.ReadinessResponse)."""
    return json.dumps(
        {
            "ready": ready,
            "database": database,
            "broker_authenticated": False,
            "scheduler_running": scheduler,
            "trading_mode": "paper",
            "live_trading_enabled": False,
        }
    ).encode()


def _ok_site(**overrides):
    """A fake site: path -> Response; overrides replace single paths (a list = one answer per call)."""
    answers = {
        "/api/v1/health": smoke.Response(200, "application/json", b"{}"),
        "/api/v1/ready": smoke.Response(200, "application/json", ready_body()),
        "/api/v1/status": smoke.Response(200, "application/json", STATUS_PAPER),
        "/api/v1/brain/stage": smoke.Response(200, "application/json", b"{}"),
        "/api/v1/risk/limits": smoke.Response(200, "application/json", b"{}"),
        "/": PAGE,
        "/trademind": PAGE,
    }
    answers.update(overrides)
    calls: list[tuple[str, str | None]] = []

    def get(url, key):
        path = url[len(BASE) :] or "/"
        calls.append((path, key))
        answer = answers[path]
        return answer.pop(0) if isinstance(answer, list) else answer

    return get, calls


def _run(get, key="k", deadline=150):
    sleeps: list[float] = []
    lines: list[str] = []
    passed, problems = smoke.run(BASE, key, deadline, get=get, sleep=sleeps.append, say=lines.append)
    return passed, problems, sleeps, lines


def test_all_good_passes_first_round_without_waiting():
    get, calls = _ok_site()
    passed, problems, sleeps, _ = _run(get)
    assert passed and problems == [] and sleeps == []
    assert {p for p, _ in calls} == {c.path for c in smoke.CHECKS}


def test_api_key_is_sent_only_to_authed_endpoints():
    get, calls = _ok_site()
    _run(get, key="secret")
    keyed = {p for p, k in calls if k == "secret"}
    assert keyed == {"/api/v1/status", "/api/v1/brain/stage", "/api/v1/risk/limits"}
    assert all(k is None for p, k in calls if p not in keyed)


def test_without_api_key_authed_checks_are_skipped_with_a_warning():
    get, calls = _ok_site()
    passed, _, _, lines = _run(get, key=None)
    assert passed
    assert "/api/v1/status" not in {p for p, _ in calls}
    assert any(line.startswith("WARNING") for line in lines)


def test_live_trading_mode_fails_at_once_without_retrying():
    live = json.dumps({"trading_mode": "live", "live_trading_enabled": True}).encode()
    get, _ = _ok_site(**{"/api/v1/status": smoke.Response(200, "application/json", live)})
    passed, problems, sleeps, _ = _run(get)
    assert not passed and sleeps == []
    assert "NOT IN PAPER MODE" in problems[0]


def test_paper_mode_with_live_switch_on_also_fails():
    body = json.dumps({"trading_mode": "paper", "live_trading_enabled": True}).encode()
    get, _ = _ok_site(**{"/api/v1/status": smoke.Response(200, "application/json", body)})
    passed, problems, _, _ = _run(get)
    assert not passed and "NOT IN PAPER MODE" in problems[0]


def test_restarting_containers_are_retried_until_they_answer():
    down = smoke.Response(502, "text/html", b"")
    get, calls = _ok_site(
        **{"/api/v1/health": [smoke.Response(0, "", b""), down, smoke.Response(200, "", b"")]}
    )
    passed, _, sleeps, _ = _run(get)
    assert passed and sleeps == [5, 10]
    # Checks that already passed are not asked again.
    assert sum(1 for p, _ in calls if p == "/trademind") == 1


def test_still_failing_at_the_deadline_reports_plain_english():
    get, _ = _ok_site(**{"/api/v1/brain/stage": smoke.Response(404, "application/json", b"")})
    passed, problems, sleeps, _ = _run(get, deadline=40)
    assert not passed
    assert problems == ["brain stage: answered 404"]
    assert sum(sleeps) <= 40


def test_page_must_be_the_app_html():
    json_page = smoke.Response(200, "application/json", b"{}")
    assert "not with a web page" in smoke.judge_page(json_page)
    assert "not the app" in smoke.judge_page(smoke.Response(200, "text/html", b"<html>nginx</html>"))
    assert smoke.judge_page(PAGE) is None
    assert smoke.judge_page(smoke.Response(0, "", b"")) == "no answer"


def test_status_without_a_trading_mode_is_a_problem_not_a_pass():
    assert "trading mode" in smoke.judge_status(smoke.Response(200, "application/json", b"not json"))


def test_backoff_stays_inside_the_deadline():
    assert smoke.backoff_delays(150) == [5, 10, 20, 30, 30, 30]
    assert sum(smoke.backoff_delays(150)) <= 150
    assert smoke.backoff_delays(0) == []


def test_http_get_only_ever_sends_get(monkeypatch):
    seen = []

    class Answer:
        status = 200
        headers: ClassVar[dict] = {"Content-Type": "text/html"}

        def read(self, _limit):
            return b""

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout):
        seen.append((request.get_method(), request.data, request.get_header("X-api-key")))
        return Answer()

    monkeypatch.setattr(smoke.urllib.request, "urlopen", fake_urlopen)
    smoke.http_get(BASE + "/api/v1/status", "k")
    smoke.http_get(BASE + "/", None)
    assert seen == [("GET", None, "k"), ("GET", None, None)]


def test_main_writes_problems_for_the_telegram_step(monkeypatch, tmp_path):
    out = tmp_path / "out"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("SMOKE_DEADLINE_SECONDS", "0")
    monkeypatch.delenv("API_KEY", raising=False)
    monkeypatch.setattr(smoke, "http_get", lambda url, key: smoke.Response(0, "", b""))
    assert smoke.main() == 1
    text = out.read_text()
    assert text.startswith("problems<<SMOKE_EOF\n") and "website health check: no answer" in text


class _Answer:
    """An HTTP answer for a faked urlopen: a status, headers, and what read() hands back (or raises)."""

    status = 200

    def __init__(self, headers, body=b"", error=None):
        self.headers = headers
        self._body = body
        self._error = error

    def read(self, _limit):
        if self._error is not None:
            raise self._error
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _get_with(monkeypatch, answer):
    monkeypatch.setattr(smoke.urllib.request, "urlopen", lambda request, timeout: answer)
    return smoke.http_get(BASE + "/api/v1/ready", None)


def test_a_body_cut_short_of_its_declared_length_is_no_answer(monkeypatch):
    """A partial read must never pass: 200 with fewer bytes than Content-Length is treated as no answer."""
    whole = ready_body()
    cut = _Answer({"Content-Type": "application/json", "Content-Length": str(len(whole))}, whole[:20])
    resp = _get_with(monkeypatch, cut)
    assert resp.status == 0
    assert smoke.judge_ready(resp) == "no answer"


def test_a_read_that_raises_part_way_is_no_answer(monkeypatch):
    import http.client

    broken = _Answer({"Content-Type": "application/json"}, error=http.client.IncompleteRead(b"{", 50))
    resp = _get_with(monkeypatch, broken)
    assert resp.status == 0 and smoke.judge_ready(resp) == "no answer"
    reset = _Answer({"Content-Type": "application/json"}, error=ConnectionResetError())
    assert _get_with(monkeypatch, reset).status == 0


def test_a_complete_body_is_still_read_and_judged(monkeypatch):
    whole = ready_body()
    ok = _Answer({"Content-Type": "application/json", "Content-Length": str(len(whole))}, whole)
    resp = _get_with(monkeypatch, ok)
    assert resp.status == 200 and smoke.judge_ready(resp) is None


def test_a_cut_off_ready_answer_fails_the_smoke_test_then_passes_when_complete():
    cut = smoke.Response(0, "", b"")
    whole = smoke.Response(200, "application/json", ready_body())
    get, _ = _ok_site(**{"/api/v1/ready": [cut, whole]})
    passed, _, sleeps, _ = _run(get)
    assert passed and sleeps == [5]
    get, _ = _ok_site(**{"/api/v1/ready": cut})
    passed, problems, _, _ = _run(get, deadline=40)
    assert not passed and problems == ["database ready check: no answer"]


def test_ready_needs_the_body_to_say_ready_database_and_scheduler():
    """HTTP 200 alone is not up: /ready answers 200 even when the database or the scheduler is down."""
    ok = smoke.Response(200, "application/json", ready_body())
    assert smoke.judge_ready(ok) is None
    cases = [
        (ready_body(scheduler=False), "scheduler"),
        (ready_body(database=False), "database"),
        (ready_body(ready=False), "not ready"),
        (b"{}", "ready"),
        (b"not json", "ready"),
        (json.dumps({"ready": "true", "database": True, "scheduler_running": True}).encode(), "ready"),
    ]
    for body, fragment in cases:
        problem = smoke.judge_ready(smoke.Response(200, "application/json", body))
        assert problem and fragment in problem, (body, problem)
    assert smoke.judge_ready(smoke.Response(503, "", b"")) == "answered 503"
    assert smoke.judge_ready(smoke.Response(0, "", b"")) == "no answer"


def test_a_scheduler_that_is_down_fails_the_smoke_test_with_a_plain_reason():
    stopped = smoke.Response(200, "application/json", ready_body(scheduler=False))
    get, _ = _ok_site(**{"/api/v1/ready": stopped})
    passed, problems, _, _ = _run(get, deadline=40)
    assert not passed
    assert len(problems) == 1 and problems[0].startswith("database ready check:")
    assert "scheduler" in problems[0]


def test_a_scheduler_that_comes_up_after_the_restart_passes_on_a_retry():
    stopped = smoke.Response(200, "application/json", ready_body(scheduler=False))
    running = smoke.Response(200, "application/json", ready_body())
    get, _ = _ok_site(**{"/api/v1/ready": [stopped, running]})
    passed, _, sleeps, _ = _run(get)
    assert passed and sleeps == [5]


def test_expect_200():
    assert smoke.expect_200(smoke.Response(200, "", b"")) is None
    assert smoke.expect_200(smoke.Response(500, "", b"")) == "answered 500"
