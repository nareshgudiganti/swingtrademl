"""Day counts and the only checkable relation between universe size and idea decisions (spec 3.1, C3).

M08 makes an idea for each universe stock not held, and a holding decision for each held stock (which may
be outside the universe). Runs store neither list, so only universe - holdings <= ideas <= universe can be
checked; inside it nothing is claimed.
"""

from __future__ import annotations


def idea_relation(universe: int | None, ideas: int, holdings: int) -> dict:
    if universe is None:
        return {
            "state": "not_observed",
            "why": "This run stored no universe size.",
            "ideas": ideas,
            "holdings": holdings,
        }
    low = max(universe - holdings, 0)
    ok = low <= ideas <= universe
    return {
        "state": "within_range" if ok else "conflicting",
        "universe": universe,
        "ideas": ideas,
        "holdings": holdings,
        "allowed": [low, universe],
    }


def word_counts(rows: list[tuple[str, str, int]]) -> dict:
    out: dict = {"idea": {}, "holding": {}}
    for kind, word, n in rows:
        out.setdefault(kind, {})[word] = n
    out["ideas_total"] = sum(out["idea"].values())
    out["holdings_total"] = sum(out["holding"].values())
    return out
