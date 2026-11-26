"""Link check for the docs: python scripts/check_doc_links.py FILE...  (exit 1 on any broken reference).

Checks two things in each markdown file: relative markdown links [text](path), and backticked repo paths that start
with a known top-level folder (docs/, backend/, frontend/, .github/, scripts/, infra/) or are a root file such as
CLAUDE.md. A path under backend/src/swing_trade_ml/ may also be written relative to that package, as the
architecture docs do (`core/modules.py:102`). A trailing :line is ignored; paths with * or {} or a space are skipped.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "backend" / "src" / "swing_trade_ml"
TOP = ("docs/", "backend/", "frontend/", ".github/", "scripts/", "infra/")
ROOT_FILES = {"CLAUDE.md", "AGENTS.md", "README.md"}
# Local-only or untracked on purpose: the queue and handoff are never pushed; the venv is not in git.
LOCAL_ONLY = ("docs/ai/DEV-QUEUE.md", "docs/ai/HANDOFF.md", "backend/.venv/")
LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)(?:#[^)]*)?\)")
TICK = re.compile(r"`([^`\n]+)`")


def exists(ref: str, doc: Path) -> bool:
    ref = re.sub(r":\d+(-\d+)?$", "", ref)
    return (ROOT / ref).exists() or (doc.parent / ref).exists() or (PKG / ref).exists()


def check(doc: Path) -> list[str]:
    bad: list[str] = []
    text = doc.read_text(encoding="utf-8")
    for n, line in enumerate(text.splitlines(), 1):
        for m in LINK.finditer(line):
            ref = m.group(1)
            if "://" not in ref and not ref.startswith("mailto:") and not exists(ref, doc):
                bad.append(f"{doc.relative_to(ROOT)}:{n}: broken link {ref}")
        for m in TICK.finditer(line):
            ref = m.group(1)
            if any(c in ref for c in "*{} ()=<>") or ref.startswith(LOCAL_ONLY) or not (ref.startswith(TOP) or ref in ROOT_FILES):
                continue
            if not exists(ref, doc):
                bad.append(f"{doc.relative_to(ROOT)}:{n}: missing path {ref}")
    return bad


def main(argv: list[str]) -> int:
    problems = [p for a in argv for p in check(Path(a).resolve())]
    print("\n".join(problems) if problems else f"link check passed ({len(argv)} files)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
