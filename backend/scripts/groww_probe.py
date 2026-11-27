"""Groww hands-off sync probe (issue #388, step 0 - the gate before any build).

Question it answers: on Groww's Rs 0 plan, can holdings be fetched again AFTER the
first access token has expired (Groww says ~06:00 IST daily) with nobody signing
in, pasting a token or tapping Approve?

Run it twice, by hand, on your own machine:

    day1   any time            -> mints a token with TOTP, reads holdings once
    day2   after 06:00 IST     -> checks yesterday's token is dead, mints a NEW
           the next day           token with TOTP only, reads holdings again

PASS on day2 = hands-off sync works (yesterday's token was refused AND a fresh one worked).
INCONCLUSIVE = the old token still worked or could not be checked (e.g. a timeout): run day2
again later. Anything else = stop and report.

    fetch  any time            -> ONE read-only fetch that shows your holdings
                                  (symbol, ISIN, shares, average price) on YOUR
                                  screen so you can compare them with the Groww app,
                                  and saves %USERPROFILE%\\.groww_probe\\holdings.csv.
                                  Unlike day1/day2 this output DOES contain your
                                  holdings: share only what you choose to.

Safety:
  * Calls exactly two things: GrowwAPI.get_access_token (TOTP flow) and
    get_holdings_for_user. No order, position-changing or paid-data call exists here.
  * Secrets come from YOUR environment variables, never from a file in the repo:
        GROWW_TOTP_TOKEN   the TOTP token shown on Groww Cloud API keys page
        GROWW_TOTP_SECRET  the TOTP secret (from the QR setup)
  * Prints no secrets, no token, no amounts, no stock names: only pass/fail,
    counts, field presence and timestamps (IST). Safe to paste the output back.
  * Day 1's token is kept only in %USERPROFILE%\\.groww_probe\\state.json (your
    machine, outside the repo) so day 2 can prove it expired; day 2 deletes it.

Setup in PowerShell (separate venv, so nothing touches the backend's packages):
    python -m venv $env:USERPROFILE\\.groww_probe\\venv
    & $env:USERPROFILE\\.groww_probe\\venv\\Scripts\\pip install growwapi pyotp
    $env:GROWW_TOTP_TOKEN  = Read-Host "Paste TOTP token"
    $env:GROWW_TOTP_SECRET = Read-Host "Paste TOTP secret"
    & $env:USERPROFILE\\.groww_probe\\venv\\Scripts\\python backend\\scripts\\groww_probe.py fetch
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
STATE_DIR = Path.home() / ".groww_probe"
STATE = STATE_DIR / "state.json"
REQUIRED_FIELDS = ("isin", "trading_symbol", "quantity", "average_price")


def now_ist() -> datetime:
    return datetime.now(IST)


def say(line: str) -> None:
    print(f"[{now_ist():%Y-%m-%d %H:%M:%S} IST] {line}", flush=True)


def fail(step: str, exc: BaseException | None = None, note: str = "") -> None:
    # Class name and code only: an SDK message could echo request details.
    detail = ""
    if exc is not None:
        detail = f" ({type(exc).__name__}, code={getattr(exc, 'code', None)})"
    say(f"FAIL at {step}{detail} {note}".rstrip())
    sys.exit(1)


def creds() -> tuple[str, str]:
    token, secret = os.environ.get("GROWW_TOTP_TOKEN", ""), os.environ.get("GROWW_TOTP_SECRET", "")
    if not token or not secret:
        fail("setup", note="- set GROWW_TOTP_TOKEN and GROWW_TOTP_SECRET in this shell first")
    return token, secret


def mint_token(totp_token: str, totp_secret: str) -> str:
    import pyotp
    from growwapi import GrowwAPI

    try:
        access = GrowwAPI.get_access_token(api_key=totp_token, totp=pyotp.TOTP(totp_secret).now())
    except Exception as exc:  # noqa: BLE001 - any failure is the answer we are looking for
        fail("token (TOTP flow)", exc)
    if not access:
        fail("token (TOTP flow)", note="- empty token returned")
    say("OK token minted with TOTP only (no sign-in, no paste, no approve)")
    return str(access)


def read_holdings(access: str, label: str) -> list[dict]:
    from growwapi import GrowwAPI

    try:
        resp = GrowwAPI(access).get_holdings_for_user(timeout=10)
    except Exception as exc:  # noqa: BLE001
        fail(f"holdings read ({label})", exc)
    rows = resp.get("holdings") if isinstance(resp, dict) else None
    if rows is None:
        fail(f"holdings read ({label})", note=f"- unexpected response shape: {type(resp).__name__}")
    return rows


def describe(rows: list[dict]) -> None:
    say(f"OK holdings read: {len(rows)} rows")
    for field in REQUIRED_FIELDS:
        missing = sum(1 for r in rows if r.get(field) in (None, ""))
        say(f"   field {field:<15} present in {len(rows) - missing}/{len(rows)} rows")
    suffixed = sum(1 for r in rows if "-" in str(r.get("trading_symbol", "")))
    say(f"   symbols with a '-' suffix (e.g. -EQ): {suffixed}/{len(rows)}")
    for extra in ("pledge_quantity", "t1_quantity", "demat_free_quantity"):
        nonzero = sum(1 for r in rows if (r.get(extra) or 0) != 0)
        say(f"   rows with non-zero {extra}: {nonzero}")


_AUTH_WORDS = ("auth", "unauthori", "forbidden", "token", "expired", "session")


def is_auth_rejection(exc: BaseException) -> bool:
    """True only when the failure says the token was refused (HTTP 401/403, or an SDK error whose class
    name says so). A timeout or network error proves nothing about expiry."""
    for attr in ("code", "status_code", "status"):
        if getattr(exc, attr, None) in (401, 403, "401", "403"):
            return True
    name = type(exc).__name__.lower()
    return any(word in name for word in _AUTH_WORDS)


def next_cutoff(after: datetime) -> datetime:
    """The first 06:00 IST strictly after `after` - when Groww says tokens expire."""
    cut = datetime.combine(after.date(), time(6, 0), tzinfo=IST)
    return cut if cut > after else cut + timedelta(days=1)


def day1() -> None:
    totp_token, totp_secret = creds()
    access = mint_token(totp_token, totp_secret)
    describe(read_holdings(access, "day 1"))
    STATE_DIR.mkdir(exist_ok=True)
    STATE.write_text(json.dumps({"day1_at": now_ist().isoformat(), "token": access}))
    cutoff = next_cutoff(now_ist())
    say(f"DAY 1 DONE. Run 'day2' after {cutoff:%Y-%m-%d %H:%M} IST, touching nothing in Groww.")


def day2() -> None:
    if not STATE.exists():
        fail("day 2", note="- run day1 first")
    state = json.loads(STATE.read_text())
    day1_at = datetime.fromisoformat(state["day1_at"])
    if now_ist() < next_cutoff(day1_at):
        fail("day 2", note=f"- too early; wait until after {next_cutoff(day1_at):%Y-%m-%d %H:%M} IST")
    say(f"Day 1 ran at {day1_at:%Y-%m-%d %H:%M} IST")

    from growwapi import GrowwAPI

    expiry_proven = False
    try:
        GrowwAPI(state["token"]).get_holdings_for_user(timeout=10)
        say("NOTE yesterday's token still works - expiry not observed")
    except Exception as exc:  # noqa: BLE001
        if is_auth_rejection(exc):
            expiry_proven = True
            say(f"OK yesterday's token is rejected as expected ({type(exc).__name__})")
        else:
            say(f"NOTE yesterday's token could not be checked ({type(exc).__name__}) - not a rejection")

    totp_token, totp_secret = creds()
    access = mint_token(totp_token, totp_secret)
    describe(read_holdings(access, "day 2"))
    if not expiry_proven:
        # Keep the state: the owner can run day2 again (e.g. after a timeout) without redoing day 1.
        say("INCONCLUSIVE: a fresh token works, but yesterday's token was not shown to be rejected. "
            "Run 'day2' again later; do not count this as a pass.")
        sys.exit(2)
    STATE.unlink()
    say("PASS: holdings fetched after the token expiry with no sign-in, paste or approve.")


def fetch() -> None:
    """One read-only fetch, printed for the owner to compare with the Groww app."""
    import csv

    totp_token, totp_secret = creds()
    rows = read_holdings(mint_token(totp_token, totp_secret), "fetch")
    describe(rows)
    cols = ("trading_symbol", "isin", "quantity", "average_price", "pledge_quantity", "t1_quantity")
    print()
    print(f"{'SYMBOL':<22}{'ISIN':<15}{'SHARES':>10}{'AVG PRICE':>14}{'PLEDGED':>10}{'T1':>8}")
    for r in sorted(rows, key=lambda r: str(r.get("trading_symbol", ""))):
        vals = [r.get(c) for c in cols]
        print(f"{vals[0]!s:<22}{vals[1]!s:<15}{vals[2]!s:>10}{vals[3]!s:>14}{vals[4]!s:>10}{vals[5]!s:>8}")
    STATE_DIR.mkdir(exist_ok=True)
    out = STATE_DIR / "holdings.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(cols)
        writer.writerows([[r.get(c) for c in cols] for r in rows])
    print()
    say(f"Saved {len(rows)} rows to {out} (your machine only). Compare with the Groww app.")


if __name__ == "__main__":
    step = sys.argv[1] if len(sys.argv) > 1 else ""
    if step == "day1":
        day1()
    elif step == "day2":
        day2()
    elif step == "fetch":
        fetch()
    else:
        print(__doc__)
        sys.exit(2)
