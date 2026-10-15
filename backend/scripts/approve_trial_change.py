"""Record an OWNER-APPROVED change to a frozen decision file during the forward trial.

    python scripts/approve_trial_change.py "why the owner approved it" [commit]

Re-fingerprints every frozen file and appends the reason to tests/trial_freeze.json, so the approval is
visible in review. Run it only after the owner has said yes to the change.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from trial_freeze import MANIFEST, fingerprint, frozen_paths


def main() -> int:
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        print(__doc__)
        return 2
    data = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {"approved": []}
    old = data.get("files", {})
    new = {p: fingerprint(p) for p in frozen_paths()}
    changed = sorted(p for p in new.keys() | old.keys() if new.get(p) != old.get(p))
    data["approved"].append(
        {
            "date": date.today().isoformat(),
            "commit": sys.argv[2] if len(sys.argv) > 2 else None,
            "why": sys.argv[1].strip(),
            "files": changed,
        }
    )
    data["files"] = new
    MANIFEST.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Recorded {len(changed)} changed file(s): {', '.join(changed) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
