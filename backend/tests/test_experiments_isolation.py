"""Horizon experiments must never touch money, orders, the brain or the 15-day trial.

1. No module in the experiments package imports trading, broker, risk, execution, portfolio or brain code.
2. Recording and scoring picks leaves the bot's paper cash, value and positions exactly as they were.
3. Every experiment route is owner-only (writes and reads)."""

from __future__ import annotations

import ast
import pathlib
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import swing_trade_ml.services.experiments as pkg
from swing_trade_ml.brokers.paper import paper_broker
from swing_trade_ml.core.security import create_access_token
from swing_trade_ml.db.models.session import User
from swing_trade_ml.services.portfolio import portfolio_value_and_cash

IST = ZoneInfo("Asia/Kolkata")
FORBIDDEN = (
    "swing_trade_ml.brokers",
    "swing_trade_ml.brain",
    "swing_trade_ml.strategies",
    "swing_trade_ml.services.execution",
    "swing_trade_ml.services.risk",
    "swing_trade_ml.services.portfolio",
    "swing_trade_ml.services.engine",
    "swing_trade_ml.services.tester_paper",
    "swing_trade_ml.services.brain_golive",
    "swing_trade_ml.db.models.trading",
    "swing_trade_ml.db.models.brain",
    "swing_trade_ml.db.models.brain_golive",
    "swing_trade_ml.db.models.safety",
)


def test_the_experiments_package_imports_nothing_that_moves_money():
    files = list(pathlib.Path(pkg.__file__).parent.glob("*.py"))
    assert len(files) >= 5  # the scan really read the package
    for f in files:
        for node in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                # "from swing_trade_ml.services import portfolio" imports swing_trade_ml.services.portfolio
                names = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            for n in names:
                assert not n.startswith(FORBIDDEN), f"{f.name} imports {n}"


def test_scoring_leaves_the_bot_book_untouched(db_session):
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.services.experiments import ledger, scorer
    from test_experiments_ledger import SAT, _bars, _inst

    nifty = _inst(db_session, settings.BENCHMARK_INDEX_SYMBOL, segment="INDICES", itype=None)
    _bars(db_session, nifty, date(2026, 10, 19), 40, open_=24_000.0, step=10.0)
    stock = _inst(db_session, "ISOA")
    _bars(db_session, stock, date(2026, 10, 19), 40)
    before = (paper_broker.get_available_cash(db_session), portfolio_value_and_cash(db_session, "paper"))
    ledger.submit(db_session, symbol="ISOA", intended_horizon=5, note=None, user="owner", now=SAT)
    scorer.run(db_session, now=datetime(2026, 12, 31, 21, tzinfo=IST))
    db_session.expire_all()
    after = (paper_broker.get_available_cash(db_session), portfolio_value_and_cash(db_session, "paper"))
    assert before == after


def _user(db, owner: bool):
    u = User(username=f"exp-{owner}", hashed_password="x", is_active=True, is_superuser=owner, plan="pro")
    db.add(u)
    db.flush()
    return {"Authorization": f"Bearer {create_access_token(u.username, {'uid': u.id})}"}


ROUTES = [
    ("GET", "/api/v1/experiments/protocol"),
    ("GET", "/api/v1/experiments/selections"),
    ("GET", "/api/v1/experiments/outcomes"),
    ("GET", "/api/v1/experiments/report"),
    ("POST", "/api/v1/experiments/selections"),
    ("POST", "/api/v1/experiments/selections/1/correct"),
]


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_experiment_route_refuses_a_non_owner(client, db_session, method, path):
    r = client.request(
        method, path, json={"symbol": "X", "intended_horizon": 5}, headers=_user(db_session, False)
    )
    assert r.status_code in (401, 403), f"{method} {path}: {r.status_code}"


@pytest.mark.parametrize(("method", "path"), ROUTES)
def test_every_experiment_route_refuses_no_credentials(client, method, path):
    r = client.request(method, path, json={"symbol": "X", "intended_horizon": 5})
    assert r.status_code in (401, 403)


def test_the_owner_can_record_and_read(client, db_session):
    owner = _user(db_session, True)
    r = client.post(
        "/api/v1/experiments/selections",
        json={"symbol": "NOSUCH", "intended_horizon": 30, "note": "x"},
        headers=owner,
    )
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert client.get("/api/v1/experiments/selections", headers=owner).json()[0]["symbol"] == "NOSUCH"
    rep = client.get("/api/v1/experiments/report", headers=owner).json()
    assert rep["protocol"]["code"] == "horizon-v1"


def test_the_nightly_job_never_raises_and_records_a_failure(monkeypatch):
    from swing_trade_ml.services.experiments import scorer
    from swing_trade_ml.workers import jobs

    recorded = {}

    def boom(db, *, now, protocol=None):
        raise RuntimeError("candles table on fire")

    def fake_record_failure(error):
        recorded["error"] = error

    monkeypatch.setattr(scorer, "run", boom)
    monkeypatch.setattr(jobs, "_record_experiment_failure", fake_record_failure)
    jobs.job_score_experiments()  # must not raise
    assert "on fire" in recorded["error"]


def test_the_nightly_job_is_scheduled_after_the_evening_jobs():
    import importlib
    import inspect

    module = importlib.import_module(
        "swing_trade_ml.workers.scheduler"
    )  # the module, not its scheduler object
    src = inspect.getsource(module.start_scheduler)
    assert "jobs.job_score_experiments" in src
    block = src[src.index("jobs.job_score_experiments") :][:400]
    assert "hour=20" in block and 'id="score_experiments"' in block
