# ruff: noqa: E501 (long lines in test code)
"""The identity admin command (#389): a guarded, manual entry for the writers that have no job."""

from __future__ import annotations

import ast
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from identity_fixtures import FRIDAY, THURSDAY, instrument
from swing_trade_ml.core.market_session import IST
from swing_trade_ml.db.models.brain import BrainDecision, BrainRun
from swing_trade_ml.db.models.identity import ScoreLedger, Security
from swing_trade_ml.db.models.trading import StockScore
from swing_trade_ml.services.identity import admin, resolve

SRC = Path(__file__).resolve().parents[1] / "src" / "swing_trade_ml"
TEST_URL = "postgresql+psycopg://someone:secretpw@localhost:5433/swing_trade_ml_dev9_test"
PROD_URL = "postgresql+psycopg://someone:secretpw@db.example.com:5432/swing_trade_ml"


class _Proxy:
    """A session that works inside the test's transaction: commit and rollback act on a savepoint."""

    def __init__(self, db):
        self._db = db
        self._sp = db.begin_nested()

    def __getattr__(self, name):
        return getattr(self._db, name)

    def commit(self):
        self._db.flush()
        self._sp.commit()

    def rollback(self):
        self._sp.rollback()

    def close(self):
        pass


@pytest.fixture()
def cli(db_session, monkeypatch):
    import swing_trade_ml.db.session as session_module

    monkeypatch.setattr(session_module, "SessionLocal", lambda: _Proxy(db_session))

    def run(*argv: str, url: str = TEST_URL) -> int:
        return admin.main(list(argv), database_url=url, environ={})

    return run


def _count(db, model) -> int:
    return len(list(db.scalars(select(model))))


# ------------------------------------------------------------------------------------------ the guard


def test_a_non_test_database_is_refused_without_the_owner_flag_and_the_url_is_never_shown(cli, capsys, db_session):
    before = _count(db_session, Security)
    assert cli("backfill-instruments", url=PROD_URL) == admin.REFUSED
    shown = capsys.readouterr()
    assert "refused" in shown.err
    for secret in ("secretpw", "someone", "postgresql+psycopg", "://"):  # the guard names host and database, never the URL
        assert secret not in shown.out + shown.err
    assert _count(db_session, Security) == before


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://u:p@localhost:5433/swing_trade_ml",  # not *_test
        "postgresql+psycopg://u:p@db.example.com:5432/swing_trade_ml_test",  # not local
        "postgresql+psycopg://u:p@localhost:5433/swing_trade_ml_test?host=elsewhere",  # query parameters
        "mysql://u:p@localhost/x_test",
    ],
)
def test_only_a_local_test_database_passes_the_guard(url):
    with pytest.raises(RuntimeError):
        admin.check_database(url, {}, owner_approved=False)
    admin.check_database(url, {}, owner_approved=True)  # the owner's explicit say-so


def test_a_local_test_database_passes_and_a_routing_variable_does_not():
    admin.check_database(TEST_URL, {}, owner_approved=False)
    with pytest.raises(RuntimeError):
        admin.check_database(TEST_URL, {"PGHOSTADDR": "10.0.0.5"}, owner_approved=False)


def test_a_command_is_required(capsys):
    with pytest.raises(SystemExit):
        admin.main([], database_url=TEST_URL, environ={})


# ------------------------------------------------------------------------------------- the commands


def test_backfill_instruments_seeds_securities_and_is_idempotent(cli, db_session, capsys):
    inst = instrument(db_session, "ADMINA390")
    assert resolve(db_session, symbol="ADMINA390") is None
    assert cli("backfill-instruments") == 0
    assert resolve(db_session, token=inst.instrument_token) is not None
    out = capsys.readouterr().out
    assert out.startswith("backfill-instruments: ") and "added=" in out
    before = _count(db_session, Security)
    assert cli("backfill-instruments") == 0
    assert _count(db_session, Security) == before


def test_a_dry_run_shows_the_counts_and_saves_nothing(cli, db_session, capsys):
    instrument(db_session, "ADMINDRY390")
    before = _count(db_session, Security)
    assert cli("--dry-run", "backfill-instruments") == 0
    assert "dry run" in capsys.readouterr().out
    assert _count(db_session, Security) == before
    assert resolve(db_session, symbol="ADMINDRY390") is None


def test_backfill_scores_copies_the_old_history_and_a_since_date_limits_it(cli, db_session):
    inst = instrument(db_session, "ADMINS390")
    db_session.add(StockScore(instrument_id=inst.id, as_of=THURSDAY, score=0.5, band="easing", model_version="m:v1", model_name="m"))
    db_session.add(StockScore(instrument_id=inst.id, as_of=FRIDAY, score=0.6, band="strong", model_version="m:v1", model_name="m"))
    db_session.flush()
    assert cli("backfill-scores", "--since", FRIDAY.isoformat()) == 0
    sid = resolve(db_session, symbol="ADMINS390")
    assert [r.session_date for r in db_session.scalars(select(ScoreLedger).where(ScoreLedger.security_id == sid))] == [FRIDAY]
    assert cli("backfill-scores") == 0
    assert len(list(db_session.scalars(select(ScoreLedger).where(ScoreLedger.security_id == sid)))) == 2


def test_brain_run_records_one_run_with_its_run_id(cli, db_session, capsys):
    instrument(db_session, "ADMINB390")
    db_session.add(BrainRun(id="admin390-run", kind="nightly", as_of=datetime(2026, 11, 20, 15, 50, tzinfo=IST), book="paper", live=True, status="done"))
    db_session.flush()
    db_session.add(BrainDecision(run_id="admin390-run", symbol="ADMINB390", kind="idea", word="WATCH", confidence=0.7, score_source="combined", horizon_days=15))
    db_session.flush()
    assert cli("brain-run", "admin390-run") == 0
    assert "written=1" in capsys.readouterr().out
    sid = resolve(db_session, symbol="ADMINB390")
    (row,) = db_session.scalars(select(ScoreLedger).where(ScoreLedger.security_id == sid))
    assert row.run_ref == "admin390-run" and row.source == "brain" and row.horizon_days is None
    assert cli("brain-run", "admin390-run") == 0
    assert "written=0" in capsys.readouterr().out


# ------------------------------------------------------------------------------- no job, no schedule


def test_nothing_calls_the_admin_command_so_no_job_can_run_it():
    callers = []
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC).as_posix()
        if rel == "services/identity/admin.py":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf8"))):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module, *(f"{node.module}.{a.name}" for a in node.names)]
            elif isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            if any(n.endswith("identity.admin") for n in names):
                callers.append(rel)
    assert callers == []


def _conflicting_score(db):
    """A score row whose instrument shares a symbol history with another company: the writer must refuse it."""
    from swing_trade_ml.services.identity import writer

    first = instrument(db, "CONFL390", name="Alpha Industries Limited")
    writer.ensure_for_instrument(db, first)
    first.tradingsymbol = "CONFLOLD390"  # the symbol is freed in `instruments`, but its history stays with Alpha
    db.flush()
    second = instrument(db, "CONFL390", name="Zebra Textiles Corporation")
    db.add(StockScore(instrument_id=second.id, as_of=FRIDAY, score=0.5, band="easing", model_version="m:v1", model_name="m"))
    db.flush()
    return second


@pytest.mark.parametrize("flags", [(), ("--dry-run",)])
def test_backfill_scores_counts_and_reports_a_skipped_conflict(cli, db_session, capsys, flags):
    from swing_trade_ml.services.identity import ledger

    second = _conflicting_score(db_session)
    result = ledger.backfill_from_stock_scores(db_session)
    assert result == {"written": 0, "skipped": 1}
    assert cli(*flags, "backfill-scores") == 0
    out = capsys.readouterr().out
    assert "skipped=1" in out and "written=0" in out
    assert "1 row(s) were skipped" in out and "different company" in out
    assert list(db_session.scalars(select(ScoreLedger).where(ScoreLedger.session_date == FRIDAY, ScoreLedger.note.like("backfilled%")))) == [] or second


def test_backfill_instruments_also_fills_security_id(cli, db_session):
    inst = instrument(db_session, "ADMINSID390")
    assert inst.security_id is None
    assert cli("backfill-instruments") == 0
    assert inst.security_id == resolve(db_session, symbol="ADMINSID390")
