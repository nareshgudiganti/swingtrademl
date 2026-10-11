"""`swingtrade brain replay-score`: the command parses, runs the report and writes the JSON."""

from __future__ import annotations

import json
from contextlib import contextmanager

from swing_trade_ml import cli

EMPTY_TRACK = {
    "ideas": 0,
    "no_price_data": 0,
    "open": 0,
    "resolved": 0,
    "target": 0,
    "stop": 0,
    "timeout": 0,
    "hit_rate": None,
    "avg_net_return": None,
    "avg_locked_return": None,
    "half_out": 0,
    "gaps": 0,
    "by_score": {},
}
REPORT = {
    "generated_at": "x",
    "window": {
        "from": "2026-09-01",
        "to": "2026-09-05",
        "days_replayed": 0,
        "failed_days": [],
        "scored_up_to": "2026-09-05",
    },
    "track_a": EMPTY_TRACK,
    "track_b": EMPTY_TRACK,
    "baselines": {},
    "ideas": [],
    "limitations": ["a limit"],
}


def test_parser_knows_replay_score():
    args = cli.build_parser().parse_args(
        ["brain", "replay-score", "--from", "2026-09-01", "--to", "2026-09-05", "--draws", "10"]
    )
    assert args.brain_command == "replay-score" and args.draws == 10 and args.book == "paper"


def test_replay_score_writes_json_and_prints_the_summary(tmp_path, monkeypatch, capsys, db_session):
    seen = {}

    def fake_run(db, **kwargs):
        seen.update(kwargs)
        return REPORT

    @contextmanager
    def fake_scope():
        yield db_session

    monkeypatch.setattr("swing_trade_ml.brain.replay_score.run_replay_score", fake_run)
    monkeypatch.setattr("swing_trade_ml.db.session.session_scope", fake_scope)
    out = tmp_path / "r.json"
    args = cli.build_parser().parse_args(
        [
            "brain",
            "replay-score",
            "--from",
            "2026-09-01",
            "--to",
            "2026-09-05",
            "--symbols",
            "infy, tcs",
            "--out",
            str(out),
        ]
    )
    assert cli.cmd_brain(args) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["window"]["from"] == "2026-09-01"
    assert seen["symbols"] == ["INFY", "TCS"] and seen["book"] == "paper"
    assert "Replay of 2026-09-01 to 2026-09-05" in capsys.readouterr().out


def test_replay_score_rejects_a_missing_range(monkeypatch, capsys, db_session):
    @contextmanager
    def fake_scope():
        yield db_session

    monkeypatch.setattr("swing_trade_ml.db.session.session_scope", fake_scope)
    args = cli.build_parser().parse_args(["brain", "replay-score"])
    assert cli.cmd_brain(args) == 1
    assert "--from" in capsys.readouterr().err


def test_parser_knows_the_asof_flags_and_asof_train():
    p = cli.build_parser()
    a = p.parse_args(
        [
            "brain",
            "replay-score",
            "--from",
            "2026-07-13",
            "--to",
            "2026-08-14",
            "--asof-model",
            "m",
            "--allow-in-sample",
        ]
    )
    assert a.asof_model == "m" and a.allow_in_sample is True
    t = p.parse_args(["brain", "asof-train", "--cutoff", "2026-07-10", "--symbols", "INFY,TCS"])
    assert t.brain_command == "asof-train" and t.cutoff == "2026-07-10" and t.symbols == "INFY,TCS"


def test_replay_score_with_an_unknown_model_name_stops_clearly(monkeypatch, capsys, db_session):
    @contextmanager
    def fake_scope():
        yield db_session

    monkeypatch.setattr("swing_trade_ml.db.session.session_scope", fake_scope)
    args = cli.build_parser().parse_args(
        ["brain", "replay-score", "--from", "2026-07-13", "--to", "2026-07-14", "--asof-model", "nope_asof"]
    )
    assert cli.cmd_brain(args) == 1
    assert "nope_asof" in capsys.readouterr().err


def test_replay_score_refuses_a_window_the_model_trained_on(monkeypatch, capsys, db_session):
    from types import SimpleNamespace

    @contextmanager
    def fake_scope():
        yield db_session

    model = SimpleNamespace(id=1, name="m_asof", version="1", metrics={"asof_cutoff": "2026-07-10"})
    monkeypatch.setattr("swing_trade_ml.db.session.session_scope", fake_scope)
    monkeypatch.setattr(cli, "_load_asof_model", lambda db, name: model)
    args = cli.build_parser().parse_args(
        ["brain", "replay-score", "--from", "2026-07-08", "--to", "2026-07-14", "--asof-model", "m_asof"]
    )
    assert cli.cmd_brain(args) == 1
    assert "2026-07-10" in capsys.readouterr().err
