"""infra/staging/preflight.sh and set-secret/gen-secrets: refuse unsafe staging settings.

Runs the real bash scripts against temp env files made here from random values - no secret is in
the repo. Skipped when bash is missing, and the file-mode cases are skipped where chmod 600 does
not stick (Windows file systems).
"""

from __future__ import annotations

import os
import secrets
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "infra" / "staging"
BASH = shutil.which("bash")

pytestmark = pytest.mark.skipif(BASH is None, reason="bash not available")


def _good() -> dict[str, str]:
    return {
        "ENVIRONMENT": "staging",
        "APP_BASE_URL": "https://staging.example.test",
        "FRONTEND_URL": "https://staging.example.test",
        "CORS_ORIGINS": "https://staging.example.test",
        "TRADING_MODE": "paper",
        "ALLOW_LIVE_TRADING": "false",
        "ALLOW_REAL_HOLDINGS_ORDERS": "false",
        "ENABLE_SCHEDULER": "false",
        "BRAIN_ENABLED": "false",
        "TELEGRAM_ENABLED": "false",
        "ALLOW_SIGNUP": "true",
        "REQUIRE_EMAIL_VERIFICATION": "true",
        "BILLING_ENABLED": "true",
        "BILLING_PROVIDER": "razorpay",
        "ALLOW_LIVE_BILLING": "false",
        "BILLING_ACCEPT_NEW_CHECKOUTS": "true",
        "EMAIL_PROVIDER": "resend",
        "EMAIL_FROM": "TradeMind Staging <no-reply@send.staging.example.test>",
        "RESEND_API_KEY": "re_" + secrets.token_hex(16),
        "RAZORPAY_KEY_ID": "rzp_test_" + secrets.token_hex(6),
        "RAZORPAY_KEY_SECRET": secrets.token_hex(12),
        "RAZORPAY_WEBHOOK_SECRET": secrets.token_hex(12),
        "JWT_SECRET_KEY": secrets.token_hex(32),
        "API_KEY": secrets.token_hex(32),
        "POSTGRES_PASSWORD": secrets.token_hex(32),
        "KITE_API_KEY": "",
        "TELEGRAM_BOT_TOKEN": "",
    }


def _write(tmp_path: Path, values: dict[str, str | None], mode: int = 0o600) -> Path:
    path = tmp_path / ".env"
    lines = [f"{k}={v}" for k, v in values.items() if v is not None]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    path.chmod(mode)
    return path


def _run(args: list[str], **kw) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [BASH, *args], capture_output=True, text=True, timeout=60, **kw
    )


def _preflight(path: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return _run([str(SCRIPTS / "preflight.sh"), str(path), *extra])


def _mode_sticks(tmp_path: Path) -> bool:
    probe = tmp_path / "probe"
    probe.write_text("x")
    probe.chmod(0o600)
    return stat.S_IMODE(probe.stat().st_mode) == 0o600 and os.name != "nt"


def _assert_no_secret_printed(
    result: subprocess.CompletedProcess[str], values: dict[str, str | None]
) -> None:
    out = result.stdout + result.stderr
    for key in ("JWT_SECRET_KEY", "API_KEY", "POSTGRES_PASSWORD", "RESEND_API_KEY",
                "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET", "RAZORPAY_KEY_ID"):
        value = values.get(key)
        if value:
            assert value not in out, f"{key} value leaked into preflight output"


def test_good_env_passes(tmp_path):
    if not _mode_sticks(tmp_path):
        pytest.skip("chmod 600 does not stick on this file system")
    values = _good()
    result = _preflight(_write(tmp_path, values))
    assert result.returncode == 0, result.stdout
    assert "PREFLIGHT PASSED" in result.stdout
    _assert_no_secret_printed(result, values)


@pytest.mark.parametrize(
    "change, expect_text",
    [
        ({"ENVIRONMENT": "production"}, "ENVIRONMENT"),
        ({"TRADING_MODE": "live"}, "TRADING_MODE"),
        ({"ALLOW_LIVE_TRADING": "true"}, "ALLOW_LIVE_TRADING"),
        ({"ALLOW_REAL_HOLDINGS_ORDERS": "true"}, "ALLOW_REAL_HOLDINGS_ORDERS"),
        ({"ENABLE_SCHEDULER": "true"}, "ENABLE_SCHEDULER"),
        ({"BRAIN_ENABLED": "true"}, "BRAIN_ENABLED"),
        ({"TELEGRAM_ENABLED": "true"}, "TELEGRAM_ENABLED"),
        ({"TESTING_NO_LIMITS": "true"}, "TESTING_NO_LIMITS"),
        ({"ALLOW_LIVE_BILLING": "true"}, "ALLOW_LIVE_BILLING"),
        ({"BILLING_PROVIDER": "stripe"}, "BILLING_PROVIDER"),
        ({"ALLOW_SIGNUP": "false"}, "ALLOW_SIGNUP"),
        ({"REQUIRE_EMAIL_VERIFICATION": "false"}, "REQUIRE_EMAIL_VERIFICATION"),
        ({"KITE_API_KEY": "anything-nonempty"}, "KITE_API_KEY"),
        ({"KITE_TOTP_SECRET": "anything-nonempty"}, "KITE_TOTP_SECRET"),
        ({"TELEGRAM_BOT_TOKEN": "anything-nonempty"}, "TELEGRAM_BOT_TOKEN"),
        ({"TELEGRAM_CHAT_ID": "12345"}, "TELEGRAM_CHAT_ID"),
        ({"RAZORPAY_KEY_ID": "rzp_live_abcdef123456"}, "RAZORPAY_KEY_ID"),
        ({"EMAIL_FROM": "TradeMind <no-reply@example.test>"}, "EMAIL_FROM"),
        ({"APP_BASE_URL": "https://swingtrademl.com"}, "APP_BASE_URL"),
        ({"APP_BASE_URL": "http://staging.example.test"}, "APP_BASE_URL"),
        ({"JWT_SECRET_KEY": "short"}, "JWT_SECRET_KEY"),
        ({"API_KEY": "change-me"}, "API_KEY"),
        ({"POSTGRES_PASSWORD": "a" * 31}, "POSTGRES_PASSWORD"),
        ({"RESEND_API_KEY": ""}, "RESEND_API_KEY"),
        ({"RAZORPAY_WEBHOOK_SECRET": "<paste-here>"}, "RAZORPAY_WEBHOOK_SECRET"),
        ({"JWT_SECRET_KEY": None}, "JWT_SECRET_KEY"),
    ],
)
def test_unsafe_env_is_refused(tmp_path, change, expect_text):
    if not _mode_sticks(tmp_path):
        pytest.skip("chmod 600 does not stick on this file system")
    values: dict[str, str | None] = dict(_good())
    values.update(change)
    result = _preflight(_write(tmp_path, values))
    assert result.returncode == 1, result.stdout
    assert f"FAIL  {expect_text}" in result.stdout or f"FAIL  {expect_text} " in result.stdout
    assert "PREFLIGHT FAILED" in result.stdout
    _assert_no_secret_printed(result, values)


def test_same_secret_reused_is_refused(tmp_path):
    if not _mode_sticks(tmp_path):
        pytest.skip("chmod 600 does not stick on this file system")
    values = _good()
    values["API_KEY"] = values["JWT_SECRET_KEY"]
    result = _preflight(_write(tmp_path, values))
    assert result.returncode == 1
    assert "must all differ" in result.stdout


def test_loose_file_mode_is_refused(tmp_path):
    if not _mode_sticks(tmp_path):
        pytest.skip("chmod 600 does not stick on this file system")
    result = _preflight(_write(tmp_path, _good(), mode=0o644))
    assert result.returncode == 1
    assert "FAIL  file mode" in result.stdout


def test_pending_third_party_allows_empty_but_not_bad(tmp_path):
    if not _mode_sticks(tmp_path):
        pytest.skip("chmod 600 does not stick on this file system")
    values: dict[str, str | None] = dict(_good())
    for k in ("RESEND_API_KEY", "RAZORPAY_KEY_ID", "RAZORPAY_KEY_SECRET", "RAZORPAY_WEBHOOK_SECRET"):
        values[k] = ""
    ok = _preflight(_write(tmp_path, values), "--allow-pending-third-party")
    assert ok.returncode == 0, ok.stdout
    # without the flag the same file is refused
    assert _preflight(_write(tmp_path, values)).returncode == 1
    # a filled live key is still refused under the flag
    values["RAZORPAY_KEY_ID"] = "rzp_live_abcdef123456"
    bad = _preflight(_write(tmp_path, values), "--allow-pending-third-party")
    assert bad.returncode == 1


def test_missing_file_is_refused(tmp_path):
    result = _preflight(tmp_path / "nope.env")
    assert result.returncode == 1


def test_set_secret_writes_without_echo_and_refuses_kite(tmp_path):
    env_file = tmp_path / "staging.env"
    env_file.write_text("A=1\nRESEND_API_KEY=\nB=2\n", newline="\n")
    value = "re_" + secrets.token_hex(12)
    env = {**os.environ, "STAGING_ENV_FILE": str(env_file), "STAGING_SET_SECRET_NO_CONFIRM": "1"}
    ok = _run([str(SCRIPTS / "set-secret.sh"), "RESEND_API_KEY"], input=value + "\n", env=env)
    assert ok.returncode == 0, ok.stderr
    assert value not in ok.stdout + ok.stderr
    lines = env_file.read_text().splitlines()
    assert lines == ["A=1", f"RESEND_API_KEY={value}", "B=2"]
    bad = _run([str(SCRIPTS / "set-secret.sh"), "KITE_API_KEY"], input="x\n", env=env)
    assert bad.returncode != 0
    assert "KITE_API_KEY" not in env_file.read_text()


def test_gen_secrets_fills_once_and_never_prints(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl not available")
    env_file = tmp_path / "staging.env"
    env = {**os.environ, "STAGING_ENV_FILE": str(env_file)}
    first = _run([str(SCRIPTS / "gen-secrets.sh")], env=env)
    assert first.returncode == 0, first.stderr
    data = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    assert set(data) == {"JWT_SECRET_KEY", "API_KEY", "POSTGRES_PASSWORD"}
    assert all(len(v) == 64 for v in data.values())
    assert len(set(data.values())) == 3
    for v in data.values():
        assert v not in first.stdout + first.stderr
    second = _run([str(SCRIPTS / "gen-secrets.sh")], env=env)
    again = dict(line.split("=", 1) for line in env_file.read_text().splitlines())
    assert again == data  # kept, not regenerated
    assert "kept" in second.stdout
