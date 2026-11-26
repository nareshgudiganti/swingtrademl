"""Owner gate: hold back PRs that touch sensitive files until the owner ticks a box.

Runs from .github/workflows/owner-gate.yml on pull_request_target, so this file is always the
copy on main: a PR cannot weaken the gate that judges it. It never checks out or runs PR code.

Rules
- A PR that touches no sensitive file passes at once (routine work merges on green CI).
- A PR that touches a sensitive file gets an "Owner approval" checkbox in its description,
  listing the files. The check fails until the box is ticked.
- New commits, opening or reopening the PR untick the box, so an approval only ever covers
  the code the owner looked at. A box that is already ticked when the PR is opened does not count.
- Claude sessions use the owner's GitHub account, so GitHub cannot tell who ticked the box.
  Claude must never tick it (rule in CLAUDE.md and AGENTS.md).
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# (glob, reason). Matched against repo-relative paths, both the new and the old name of a rename.
SENSITIVE: list[tuple[str, str]] = [
    ("backend/alembic/**", "database migration"),
    (".github/**", "CI / deployment workflow"),
    ("infra/**", "deployment"),
    ("docker-compose*", "deployment"),
    ("**/Dockerfile*", "deployment"),
    ("frontend/nginx.conf", "deployment"),
    ("render.yaml", "deployment"),
    (".env.example", "settings / secrets layout"),
    (".gitleaks.toml", "security"),
    ("backend/src/swing_trade_ml/core/config.py", "settings (trading mode, limits)"),
    ("backend/src/swing_trade_ml/core/security.py", "security"),
    ("backend/src/swing_trade_ml/api/deps.py", "authentication"),
    ("backend/src/swing_trade_ml/api/v1/endpoints/auth.py", "authentication"),
    ("backend/src/swing_trade_ml/api/v1/endpoints/account_auth.py", "authentication"),
    ("backend/src/swing_trade_ml/**/*auth*", "authentication"),
    ("backend/src/swing_trade_ml/**/*mfa*", "authentication"),
    ("backend/src/swing_trade_ml/**/billing*", "billing"),
    ("backend/src/swing_trade_ml/**/billing/**", "billing"),
    ("backend/src/swing_trade_ml/brokers/**", "order placement"),
    ("backend/src/swing_trade_ml/services/execution.py", "order placement"),
    ("backend/src/swing_trade_ml/services/real_orders.py", "order placement"),
    ("backend/src/swing_trade_ml/api/v1/endpoints/orders.py", "order placement"),
    ("backend/src/swing_trade_ml/services/limits.py", "risk limits"),
    ("backend/src/swing_trade_ml/services/risk.py", "risk limits"),
    ("backend/src/swing_trade_ml/api/v1/endpoints/risk.py", "risk limits"),
    ("backend/src/swing_trade_ml/brain/modules/m07_risk/**", "risk limits"),
    ("backend/src/swing_trade_ml/ml/registry.py", "model activation"),
    ("backend/src/swing_trade_ml/api/v1/endpoints/ml.py", "model activation"),
    ("backend/src/swing_trade_ml/services/brain_golive/**", "model activation / go-live"),
    ("backend/src/swing_trade_ml/**/*promot*", "model activation"),
    ("backend/tests/trial_freeze.json", "frozen trial files"),
    ("backend/tests/trial_freeze.py", "frozen trial files"),
    ("backend/scripts/approve_trial_change.py", "frozen trial files"),
    ("scripts/approve_trial_change.py", "frozen trial files"),
]

FROZEN_PREFIX = "backend/src/swing_trade_ml/"
START = "<!-- owner-gate:start -->"
END = "<!-- owner-gate:end -->"
TICK_RE = re.compile(r"^\s*[-*]\s*\[([ xX])\]\s*\*\*Owner approval\*\*", re.MULTILINE)
RESET_ACTIONS = {"opened", "reopened", "synchronize"}


def _match(path: str, pattern: str) -> bool:
    # fnmatch's * already crosses "/", so "**" behaves like "*"; also let "**/x" match a top-level x.
    if fnmatch.fnmatchcase(path, pattern):
        return True
    return pattern.startswith("**/") and fnmatch.fnmatchcase(path, pattern[3:])


def sensitive_files(paths: list[str], frozen: set[str]) -> dict[str, str]:
    """Return {path: reason} for every path that needs the owner's approval."""
    found: dict[str, str] = {}
    for path in paths:
        if path in frozen:
            found[path] = "frozen trial file"
            continue
        for pattern, reason in SENSITIVE:
            if _match(path, pattern):
                found[path] = reason
                break
    return found


def frozen_files(freeze_json: Path) -> set[str]:
    try:
        data = json.loads(freeze_json.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {FROZEN_PREFIX + rel for rel in data.get("files", {})}


def is_ticked(body: str) -> bool:
    block = _block(body)
    if block is None:
        return False
    m = TICK_RE.search(block)
    return bool(m and m.group(1) in "xX")


def _block(body: str) -> str | None:
    i, j = body.find(START), body.find(END)
    if i == -1 or j == -1 or j < i:
        return None
    return body[i : j + len(END)]


def render_block(found: dict[str, str], ticked: bool) -> str:
    box = "x" if ticked else " "
    lines = [
        START,
        "### Owner approval needed",
        "This PR changes files that need the owner's explicit approval before it can merge:",
        "",
    ]
    lines += [f"- `{p}` ({r})" for p, r in sorted(found.items())]
    lines += [
        "",
        f"- [{box}] **Owner approval**: I, the owner, read these changes and approve the merge.",
        "",
        "_New commits untick this box. Claude never ticks it._",
        END,
    ]
    return "\n".join(lines)


def with_block(body: str, block: str) -> str:
    old = _block(body)
    if old is not None:
        return body.replace(old, block)
    return (body.rstrip() + "\n\n" + block) if body.strip() else block


def decide(action: str, paths: list[str], body: str, frozen: set[str]) -> tuple[bool, str | None, str]:
    """Return (passed, new_body_or_None, message)."""
    body = body or ""
    found = sensitive_files(paths, frozen)
    if not found:
        return True, None, "No sensitive files changed. Routine PR: no owner approval needed."

    ticked = False if action in RESET_ACTIONS else is_ticked(body)
    new_body = with_block(body, render_block(found, ticked))
    changed = new_body if new_body != body else None
    listing = ", ".join(sorted(found))
    if ticked:
        return True, changed, f"Owner approved the sensitive changes: {listing}"
    why = "New commits reset the approval. " if action == "synchronize" else ""
    return False, changed, f"{why}Waiting for the owner to tick 'Owner approval'. Sensitive files: {listing}"


def _gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def main() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    repo = os.environ["GITHUB_REPOSITORY"]
    pr = event["pull_request"]
    number = pr["number"]
    action = event.get("action", "")

    raw = _gh("api", "--paginate", f"repos/{repo}/pulls/{number}/files",
              "--jq", ".[] | .filename, (.previous_filename // empty)")
    paths = sorted({line for line in raw.splitlines() if line})
    frozen = frozen_files(Path("backend/tests/trial_freeze.json"))

    passed, new_body, message = decide(action, paths, pr.get("body") or "", frozen)
    if new_body is not None:
        # An edit made with the workflow token does not start another run, so this cannot loop.
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{repo}/pulls/{number}", "-F", "body=@-"],
                       input=new_body, text=True, check=True, capture_output=True)

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(f"## Owner gate: {'passed' if passed else 'waiting'}\n\n{message}\n")
    print(message)
    if not passed:
        print(f"::error::{message}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
