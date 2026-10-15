"""Spec 3.5: calling every Observatory route runs no brain, queue, alert, broker or Telegram code, and writes
nothing. The database refusal (tests/test_brain_observatory_readonly.py, test_brain_observatory_api.py) is
the enforcement; these are extra checks, and the Postgres counters are supplementary only."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from observatory_fixtures import committed, obs_ns  # noqa: F401 — fixture
from swing_trade_ml.db.session import engine
from test_brain_observatory_api import BASE, OWNER, RUN_PREFIX, seed

pytestmark = pytest.mark.usefixtures("obs_ns")

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml" / "services" / "brain_observatory"
FORBIDDEN = (
    "swing_trade_ml.brain.service",
    "swing_trade_ml.brain.runner",
    "swing_trade_ml.brain.queue",
    "swing_trade_ml.brain.alerts",
    "swing_trade_ml.brokers",
    "swing_trade_ml.notifications",
    "redis",
)
PATHS = (
    "/days?from=2026-10-14&to=2026-10-15",
    "/runs?date=2026-10-15",
    f"/runs/{RUN_PREFIX}n1",
    f"/runs/{RUN_PREFIX}n1/stocks",
    "/learning?from=2026-10-01&to=2026-10-15",
    "/outcomes?from=2026-10-01&to=2026-10-15&category=practice",
    "/outcomes?from=2026-10-01&to=2026-10-15&category=backtest",
    "/forward-gate",
    "/effectiveness",
)


def test_package_does_not_import_side_effect_modules_directly():
    for path in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert not name.startswith(FORBIDDEN), f"{path.name} imports {name}"


def test_routes_never_call_side_effect_entry_points(client, monkeypatch):
    import swing_trade_ml.brain.alerts.service as alerts
    import swing_trade_ml.brain.queue as queue
    import swing_trade_ml.brain.runner as runner
    import swing_trade_ml.brain.service as service
    import swing_trade_ml.brokers as brokers
    from swing_trade_ml.notifications.telegram import TelegramNotifier

    def boom(*_a, **_k):
        raise AssertionError("side effect called")

    for mod, name in (
        (service, "run_brain"),
        (runner, "execute"),
        (queue, "request_run"),
        (queue, "process_next"),
        (alerts, "send"),
        (brokers, "get_broker"),
        (TelegramNotifier, "send_sync"),
    ):
        monkeypatch.setattr(mod, name, boom)
    with committed(*seed()):
        for p in PATHS:
            assert client.get(BASE + p, headers=OWNER).status_code == 200, p


def _tuple_counters() -> dict:
    with Session(engine) as s:
        s.execute(text("SELECT pg_stat_clear_snapshot()"))
        rows = s.execute(
            text("SELECT relname, n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables")
        ).all()
    return {r[0]: r[1:] for r in rows}


def test_supplementary_postgres_counters_do_not_move(client):
    """Supplementary only: statistics are reported asynchronously, so this cannot prove absence."""
    with committed(*seed()):
        before = _tuple_counters()
        for p in PATHS:
            client.get(BASE + p, headers=OWNER)
        after = _tuple_counters()
    moved = {t for t in before if after.get(t) != before[t]}
    assert not moved, moved
