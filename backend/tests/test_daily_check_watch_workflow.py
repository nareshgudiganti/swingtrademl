"""Static checks on .github/workflows/daily-check-watch.yml: simulate input and visible Telegram result."""

from __future__ import annotations

from pathlib import Path

import yaml

TEXT = (Path(__file__).resolve().parents[2] / ".github/workflows/daily-check-watch.yml").read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)
STEPS = DOC["jobs"]["check"]["steps"]


def test_simulate_input_exists_and_is_labelled():
    on = DOC.get("on", DOC.get(True))
    sim = on["workflow_dispatch"]["inputs"]["simulate"]
    assert sim["type"] == "choice" and sim["options"] == ["none", "failure"]
    run = STEPS[0]["run"]
    assert "TEST ONLY - simulated failure of the daily-check watcher; no real problem" in run
    assert STEPS[0]["env"]["SIMULATE"] == "${{ inputs.simulate }}"


def test_default_logic_unchanged_and_permissions_empty():
    assert DOC["permissions"] == {}
    run = STEPS[0]["run"]
    assert "brain/daily-checks/latest" in run and "Not a trading day" in run


def test_telegram_step_reports_delivery_and_always_fails():
    run = STEPS[1]["run"]
    assert '"$code" = "200"' in run and "NOT delivered" in run
    assert run.rstrip().endswith("exit 1")
