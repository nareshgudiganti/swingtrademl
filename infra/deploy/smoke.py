"""After-deploy smoke test (tracker qa2): does the live site still answer, from OUTSIDE the server?

release.sh already checks the deploy from inside the droplet (verify.py: API ready, migration at head,
fresh worker heartbeat). This checks what a user sees, over the public internet, right after a deploy:

  * /api/v1/health and /api/v1/ready answer 200
  * /api/v1/status answers 200 and says PAPER trading (a live trading mode fails loudly: risk rule)
  * /api/v1/brain/stage and /api/v1/risk/limits answer 200
  * the web pages / and /trademind load (200, HTML with the app's root element)

STRICTLY READ-ONLY: every request is a GET. It never logs in, never scans, never places an order.
Response bodies are never printed (the repo and its Actions logs are public): only status codes and
pass/fail lines. The authed checks need API_KEY; without it they are skipped with a warning.

Containers are still restarting just after a deploy, so failing checks are retried with backoff until
SMOKE_DEADLINE_SECONDS (default 150). A live trading mode is never retried: it is not a restart blip.

Usage:  SMOKE_BASE_URL=https://swingtrademl.com API_KEY=... python3 infra/deploy/smoke.py
Exit 0 = all good; 1 = something failed (plain-English summary on stdout, and in $GITHUB_OUTPUT as
`problems` when run in GitHub Actions). Standard library only.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

DEFAULT_BASE = "https://swingtrademl.com"
BODY_LIMIT = 512 * 1024  # enough for /status; never printed


@dataclass
class Response:
    status: int  # 0 = no answer at all (timeout, refused, DNS)
    content_type: str
    body: bytes


@dataclass
class Check:
    name: str  # plain English, shown in the summary
    path: str
    needs_key: bool
    judge: Callable[[Response], str | None]  # None = ok, else the problem in plain English


class FatalProblemError(Exception):
    """A failure that retrying cannot fix (e.g. the bot reports live trading)."""


def _json(resp: Response) -> dict:
    try:
        data = json.loads(resp.body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def expect_200(resp: Response) -> str | None:
    if resp.status == 200:
        return None
    return "no answer" if resp.status == 0 else f"answered {resp.status}"


def judge_status(resp: Response) -> str | None:
    problem = expect_200(resp)
    if problem:
        return problem
    data = _json(resp)
    mode = str(data.get("trading_mode", "")).lower()
    if not mode:
        return "answered 200 but did not say which trading mode it is in"
    if mode != "paper" or data.get("live_trading_enabled") is True:
        raise FatalProblemError(
            f"THE BOT IS NOT IN PAPER MODE (trading mode '{mode}', live trading switch "
            f"{'ON' if data.get('live_trading_enabled') else 'off'}). Going live is the owner's call "
            "only. Check TRADING_MODE and ALLOW_LIVE_TRADING in the server's .env now."
        )
    return None


def judge_page(resp: Response) -> str | None:
    problem = expect_200(resp)
    if problem:
        return problem
    if "text/html" not in resp.content_type.lower():
        return f"answered 200 but not with a web page ({resp.content_type or 'no content type'})"
    if b'id="root"' not in resp.body:
        return "answered 200 but the page is not the app (no root element)"
    return None


CHECKS = [
    Check("website health check", "/api/v1/health", False, expect_200),
    Check("database ready check", "/api/v1/ready", False, expect_200),
    Check("bot status (paper mode)", "/api/v1/status", True, judge_status),
    Check("brain stage", "/api/v1/brain/stage", True, expect_200),
    Check("risk limits", "/api/v1/risk/limits", True, expect_200),
    Check("home page /", "/", False, judge_page),
    Check("TradeMind page /trademind", "/trademind", False, judge_page),
]


def http_get(url: str, api_key: str | None, timeout: float = 20) -> Response:
    """GET only. Any other method is a bug in this script, so it is refused here."""
    request = urllib.request.Request(url, method="GET", headers={"User-Agent": "stml-smoke/1"})
    if request.get_method() != "GET":  # belt and braces: this script must never write
        raise RuntimeError("smoke test may only send GET requests")
    if api_key:
        request.add_header("X-API-Key", api_key)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return Response(answer.status, answer.headers.get("Content-Type", ""), answer.read(BODY_LIMIT))
    except urllib.error.HTTPError as exc:
        return Response(exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", b"")
    except (urllib.error.URLError, TimeoutError, OSError):
        return Response(0, "", b"")


def backoff_delays(deadline_seconds: float) -> list[float]:
    """Waits between rounds: 5, 10, 20, 30, 30, ... until the deadline is spent."""
    delays, spent, step = [], 0.0, 5.0
    while spent + step <= deadline_seconds:
        delays.append(step)
        spent += step
        step = min(step * 2, 30.0)
    return delays


def run(
    base_url: str,
    api_key: str | None,
    deadline_seconds: float = 150,
    get: Callable[[str, str | None], Response] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    say: Callable[[str], None] = print,
) -> tuple[bool, list[str]]:
    """Run every check, retrying the failing ones. Returns (passed, problems in plain English)."""
    get = get or http_get
    base = base_url.rstrip("/")
    checks = [c for c in CHECKS if api_key or not c.needs_key]
    if not api_key:
        say("WARNING: no API_KEY, so the paper-mode, brain-stage and risk-limit checks are skipped.")
    pending = {c.name: c for c in checks}
    problems: dict[str, str] = {}
    delays = backoff_delays(deadline_seconds)
    for round_number in range(len(delays) + 1):
        for check in list(pending.values()):
            resp = get(base + check.path, api_key if check.needs_key else None)
            try:
                problem = check.judge(resp)
            except FatalProblemError as exc:
                say(f"FAIL  {check.name}: {exc}")
                return False, [f"{check.name}: {exc}"]
            if problem is None:
                say(f"ok    {check.name} ({resp.status})")
                pending.pop(check.name)
                problems.pop(check.name, None)
            else:
                problems[check.name] = problem
        if not pending:
            return True, []
        if round_number < len(delays):
            say(f"...   {len(pending)} check(s) not passing yet; trying again in {delays[round_number]:.0f}s")
            sleep(delays[round_number])
    lines = [f"{name}: {problems[name]}" for name in pending]
    for line in lines:
        say(f"FAIL  {line}")
    return False, lines


def main() -> int:
    base = os.environ.get("SMOKE_BASE_URL") or DEFAULT_BASE
    api_key = os.environ.get("API_KEY") or None
    deadline = float(os.environ.get("SMOKE_DEADLINE_SECONDS") or 150)
    print(f"Smoke test of {base} (read-only GETs, up to {deadline:.0f}s of retries)")
    passed, problems = run(base, api_key, deadline)
    if passed:
        print("SMOKE TEST PASSED: the site, the API and the main pages answer after the deploy.")
        return 0
    summary = "\n".join(f"- {p}" for p in problems)
    print("SMOKE TEST FAILED after the deploy:\n" + summary)
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            stream.write(f"problems<<SMOKE_EOF\n{summary}\nSMOKE_EOF\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
