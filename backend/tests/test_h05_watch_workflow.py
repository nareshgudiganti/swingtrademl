"""Static checks on .github/workflows/h05-watch.yml (read-only, no stored state, fails visibly)."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

TEXT = (Path(__file__).resolve().parents[2] / ".github/workflows/h05-watch.yml").read_text(encoding="utf-8")
DOC = yaml.safe_load(TEXT)
CODE = "\n".join(line for line in TEXT.splitlines() if not line.lstrip().startswith("#"))


def test_permissions_empty_and_no_storage():
    assert DOC["permissions"] == {}
    assert "actions/cache" not in CODE and "upload-artifact" not in CODE


def test_api_key_never_echoed():
    for line in CODE.splitlines():
        m = re.search(r"(echo|printf)(.*)|print\((.*)", line)
        if m:  # whatever is printed must not expand the key (the `[ -z "$API_KEY" ]` test before it is fine)
            assert "API_KEY" not in (m.group(2) or m.group(3) or "")
    assert "set -x" not in CODE
    assert "cat \"$RUNNER_TEMP/h05.json\"" not in CODE


def test_only_two_api_routes_fetched():
    urls = re.findall(r'"\$BASE/([^"]+)"', CODE)
    assert sorted(urls) == ["research/h05/report"]
    assert "-X POST" not in CODE and "-X PUT" not in CODE and "-X DELETE" not in CODE


def test_simulate_input_exists():
    on = DOC.get("on", DOC.get(True))
    sim = on["workflow_dispatch"]["inputs"]["simulate"]
    assert sim["type"] == "choice" and sim["options"] == ["none", "failure"]
    assert "TEST ONLY - simulated h05 failure, no real problem" in TEXT


def test_telegram_step_fails_job_on_non_200():
    step = DOC["jobs"]["watch"]["steps"][1]["run"]
    assert '"$code" != "200"' in step
    assert step.rstrip().endswith("exit 1")


def test_quiet_success_only_for_no_key_or_non_trading_day():
    run = DOC["jobs"]["watch"]["steps"][0]["run"]
    assert "No API_KEY" in run and "Not a trading day" not in run  # runs every day: Friday misses surface on Saturday
    assert "did not come back as expected" in run  # bad answers become an alert, which ends red

def test_it_runs_every_day_not_only_on_weekdays():
    crons = [e["cron"] for e in DOC[True]["schedule"]] if True in DOC else [e["cron"] for e in DOC["on"]["schedule"]]
    assert all(c.split()[-1] == "*" for c in crons), crons
