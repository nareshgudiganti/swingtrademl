"""The test suite must never run against live settings or a non-test database.

Codex audit finding 5: conftest used os.environ.setdefault, so a value already
in the shell (TRADING_MODE=live, ALLOW_LIVE_TRADING=true, a prod DATABASE_URL)
silently won, and nothing checked which database the fixtures built tables in.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import _env_safety as safety

BACKEND = Path(__file__).resolve().parents[1]
LOCAL_TEST_URL = "postgresql+psycopg://u:p@localhost:5433/swing_trade_ml_test"


# ------------------------------------------------------------ pure functions --


def test_pinning_overrides_values_already_in_the_environment():
    env = {
        "TRADING_MODE": "live",
        "ALLOW_LIVE_TRADING": "true",
        "ENABLE_SCHEDULER": "true",
        "TELEGRAM_ENABLED": "true",
    }
    safety.pin_safe_environment(env)
    assert env["TRADING_MODE"] == "paper"
    assert env["ALLOW_LIVE_TRADING"] == "false"
    assert env["ENABLE_SCHEDULER"] == "false"
    assert env["TELEGRAM_ENABLED"] == "false"


def test_pinning_blanks_every_credential_so_dotenv_cannot_supply_one():
    env = {"KITE_API_KEY": "real", "TELEGRAM_BOT_TOKEN": "real", "KITE_TOTP_SECRET": "real"}
    safety.pin_safe_environment(env)
    for name in safety.BLANKED_CREDENTIALS:
        assert env[name] == "", name


def test_pinning_keeps_a_caller_supplied_api_key_and_test_database():
    env = {"API_KEY": "mine", "DATABASE_URL": LOCAL_TEST_URL}
    safety.pin_safe_environment(env)
    assert env["API_KEY"] == "mine"
    assert env["DATABASE_URL"] == LOCAL_TEST_URL


def test_pinning_supplies_a_test_database_when_none_is_set():
    env: dict[str, str] = {}
    safety.pin_safe_environment(env)
    safety.assert_test_database(env["DATABASE_URL"])


@pytest.mark.parametrize(
    "url",
    [
        LOCAL_TEST_URL,
        "postgresql+psycopg://u:p@127.0.0.1:5433/anything_test",
        "postgresql://u:p@localhost/swing_trade_ml_test",
    ],
)
def test_a_local_test_database_is_accepted(url):
    safety.assert_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5433/swing_trade_ml",  # real db name
        "postgresql+psycopg://u:p@db.example.com:5432/swing_trade_ml_test",  # remote host
        "postgresql+psycopg://u:p@147.182.176.105:5432/swing_trade_ml_test",  # prod droplet
        "postgresql+psycopg://u:p@localhost:5433/",  # no database name
        "not a url",
    ],
)
def test_anything_else_is_refused_with_a_clear_message(url):
    with pytest.raises(RuntimeError, match="test database"):
        safety.assert_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        # Codex review finding 1: libpq lets query parameters override the host/database that the
        # URL's own host and path name, so the "local test database" would really be somewhere else.
        LOCAL_TEST_URL + "?host=db.example.com&dbname=swing_trade_ml",
        LOCAL_TEST_URL + "?dbname=swing_trade_ml",
        LOCAL_TEST_URL + "?hostaddr=147.182.176.105",
        LOCAL_TEST_URL + "?service=production",
        LOCAL_TEST_URL + "?options=-c%20search_path%3Dother",
        LOCAL_TEST_URL + "?sslmode=disable",  # no query parameter is needed, so none is allowed
        "postgresql+psycopg://u:p@localhost,db.example.com:5433/swing_trade_ml_test",  # multi-host
        "postgresql+psycopg://u:p@/swing_trade_ml_test?host=/var/run/postgresql",  # unix socket
        "mysql+pymysql://u:p@localhost/swing_trade_ml_test",  # not Postgres
    ],
)
def test_connection_routing_overrides_are_refused(url):
    with pytest.raises(RuntimeError, match="test database"):
        safety.assert_test_database(url)


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://user:s3cretpw@db.example.com/prod",
        # Codex review finding 2: hide_password only hides the password before the "@".
        LOCAL_TEST_URL + "?password=s3cretpw",
        "postgresql+psycopg://u:p@db.example.com/prod?password=s3cretpw&host=other",
        "postgresql+psycopg://user:s3cretpw@localhost:5433/prod?service=x",
        "s3cretpw not a url",
    ],
)
def test_the_refusal_message_never_prints_any_credential(url):
    with pytest.raises(RuntimeError) as err:
        safety.assert_test_database(url)
    assert "s3cretpw" not in str(err.value)


# ------------------------------------------------------- the running session --


def test_this_session_is_paper_only_and_cannot_trade_live():
    from swing_trade_ml.core.config import settings

    assert settings.TRADING_MODE == "paper"
    assert settings.ALLOW_LIVE_TRADING is False
    assert settings.is_live_trading is False
    assert settings.TELEGRAM_ENABLED is False
    assert settings.ENABLE_SCHEDULER is False


def test_this_session_holds_no_broker_or_telegram_credentials():
    from swing_trade_ml.core.config import settings

    for name in safety.BLANKED_CREDENTIALS:
        assert getattr(settings, name) == "", name


def test_this_session_uses_a_test_database():
    from swing_trade_ml.core.config import settings

    safety.assert_test_database(settings.DATABASE_URL)


# ------------------------------------- conftest itself, under a hostile shell --


SETTINGS_ONLY_TESTS = [
    "tests/test_test_environment_safety.py::test_this_session_is_paper_only_and_cannot_trade_live",
    "tests/test_test_environment_safety.py::test_this_session_holds_no_broker_or_telegram_credentials",
]
# Nothing listens on port 1, so if any of these child runs ever tried to open a database
# connection it would fail at once instead of reaching a real server. The two selected tests
# read settings only; they request no database fixture.
UNREACHABLE_TEST_URL = "postgresql+psycopg://u:p@localhost:1/swing_trade_ml_test"
NO_NETWORK = {"HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": ""}


def _run_in_child(extra_env: dict[str, str], *node_ids: str, collect_only: bool = False):
    """Run pytest in a child process whose shell is hostile (live trading, real-looking credentials)."""
    args = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"]
    if collect_only:
        args.append("--collect-only")
    return subprocess.run(
        [*args, *node_ids],
        cwd=BACKEND,
        env={**os.environ, **NO_NETWORK, **extra_env},
        capture_output=True,
        text=True,
        timeout=180,
    )


def test_conftest_aborts_when_the_shell_points_at_a_non_test_database():
    result = _run_in_child(
        {"DATABASE_URL": "postgresql+psycopg://u:hunter2@db.example.com:5432/swing_trade_ml"},
        SETTINGS_ONLY_TESTS[0],
        collect_only=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "test database" in output
    assert "hunter2" not in output


def test_conftest_aborts_on_a_query_string_that_reroutes_the_connection():
    result = _run_in_child(
        {"DATABASE_URL": UNREACHABLE_TEST_URL + "?host=db.example.com&password=hunter2"},
        SETTINGS_ONLY_TESTS[0],
        collect_only=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "test database" in output
    assert "hunter2" not in output


def test_a_live_shell_with_real_looking_credentials_still_runs_paper_only():
    """Runs the settings assertions inside a child pytest session started from a hostile shell."""
    result = _run_in_child(
        {
            "TRADING_MODE": "live",
            "ALLOW_LIVE_TRADING": "true",
            "ENABLE_SCHEDULER": "true",
            "TELEGRAM_ENABLED": "true",
            "KITE_API_KEY": "hostile-key",
            "KITE_API_SECRET": "hostile-secret",
            "TELEGRAM_BOT_TOKEN": "hostile-token",
            "DATABASE_URL": UNREACHABLE_TEST_URL,
        },
        *SETTINGS_ONLY_TESTS,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "2 passed" in output, output


# ------------------------- inherited libpq environment variables (Codex review round 2) --
# The driver (libpq) fills in any connection setting the URL leaves out from PG* environment
# variables: PGHOSTADDR makes it connect to a different IP than the URL's host, PGPORT picks the
# port when the URL has none (a forwarded local port can reach a remote database), PGSERVICE loads
# host/hostaddr/port from a service file. A URL that passes the guard is not enough.

ROUTING_VARS = [
    "PGHOSTADDR", "PGHOST", "PGPORT", "PGDATABASE", "PGSERVICE", "PGSERVICEFILE", "PGSYSCONFDIR",
    "PGOPTIONS", "PGTARGETSESSIONATTRS",
]


def test_the_driver_really_does_read_routing_settings_from_the_environment(monkeypatch):
    """Documents why the guard must look at the environment: libpq honours these variables."""
    pq = pytest.importorskip("psycopg.pq")
    monkeypatch.setenv("PGHOSTADDR", "10.9.8.7")
    monkeypatch.setenv("PGPORT", "6543")
    defaults = {o.keyword.decode(): o.val.decode() for o in pq.Conninfo.get_defaults() if o.val}
    assert defaults["hostaddr"] == "10.9.8.7"
    assert defaults["port"] == "6543"


@pytest.mark.parametrize("name", ROUTING_VARS)
def test_an_inherited_routing_variable_is_refused_by_name_never_by_value(name):
    from swing_trade_ml.core.db_guard import assert_no_connection_overrides

    with pytest.raises(RuntimeError, match=name) as err:
        assert_no_connection_overrides({name: "s3cretvalue"})
    assert "s3cretvalue" not in str(err.value)


def test_an_empty_routing_variable_counts_as_unset():
    from swing_trade_ml.core.db_guard import assert_no_connection_overrides

    assert_no_connection_overrides({"PGHOSTADDR": "", "PGPASSWORD": "fine", "PATH": "x"})


def test_a_clean_environment_is_accepted():
    from swing_trade_ml.core.db_guard import assert_no_connection_overrides

    assert_no_connection_overrides({"PATH": "x", "PGPASSWORD": "harmless"})


@pytest.mark.parametrize("name", ROUTING_VARS)
def test_pinning_the_test_environment_refuses_an_inherited_routing_variable(name):
    env = {name: "x", "DATABASE_URL": LOCAL_TEST_URL}
    with pytest.raises(RuntimeError, match=name):
        safety.pin_safe_environment(env)


def test_conftest_aborts_when_the_shell_exports_pghostaddr():
    result = _run_in_child(
        {"PGHOSTADDR": "10.9.8.7", "DATABASE_URL": UNREACHABLE_TEST_URL},
        SETTINGS_ONLY_TESTS[0],
        collect_only=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "PGHOSTADDR" in output
    assert "10.9.8.7" not in output


def test_the_migration_checker_refuses_an_inherited_routing_variable(monkeypatch, capsys):
    import importlib.util

    script_path = BACKEND / "scripts" / "check_migrations.py"
    spec = importlib.util.spec_from_file_location("check_migrations", script_path)
    script = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(script)
    monkeypatch.setenv("PGHOSTADDR", "10.9.8.7")
    # If the refusal ever regresses this must fail loudly, never open a connection.
    monkeypatch.setattr(script, "check", lambda url: pytest.fail("opened a database connection"))
    assert script.main() == 2
    err = capsys.readouterr().err
    assert "PGHOSTADDR" in err
    assert "10.9.8.7" not in err
