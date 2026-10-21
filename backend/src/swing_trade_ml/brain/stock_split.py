"""Evidence plan ev15: split the never-used stocks once, with a fixed seed, before Phase B.

Evidence plan (`docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md`, section 3): the 257
never-used stocks are split once, by stock, into a reject set of 129 (never used to train any
candidate; robustness check only) and an extra training set of 128 (used only by candidate B2). The
seed, both lists and their file hash are committed before the first Phase B run.

Population (read once from the local database, then frozen in the committed JSON):
- "the 49" = active, watchlisted instruments: the universe `walk_forward` trains and scores on
  (`Instrument.is_active and Instrument.is_watchlisted`).
- "never used" = active NSE equity shares (segment NSE, type EQ) with at least one daily candle that
  are not in the 49. Index series (segment INDICES, e.g. NIFTY BANK, INDIA VIX) are not stocks and are
  left out. This is the "306 shares with daily candles, 257 not on the watchlist" of
  `docs/brain/evidence/wider_universe_data_check_2026-10-12.md`.

Split algorithm (`split_population`): sort the symbols alphabetically, shuffle a copy with Python's
`random.Random(SEED).shuffle`, the first 129 are the reject set, the other 128 the extra training
set; each list is stored sorted. Seed 7 is the project's standard seed (the plan names none for the
split; section 3a uses 7 for the bootstrap).

Run once: `python -m swing_trade_ml.brain.stock_split` from `backend/`. It refuses to overwrite an
existing split: the split is a locked research artefact.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
from collections.abc import Sequence
from pathlib import Path

SEED = 7
REJECT_SIZE = 129
EXTRA_SIZE = 128
POPULATION_SIZE = REJECT_SIZE + EXTRA_SIZE  # 257
USED_SIZE = 49
ALGORITHM = (
    "population sorted alphabetically by symbol; copy shuffled with Python random.Random(7).shuffle; "
    "first 129 = reject_set, remaining 128 = extra_training_set; each list then stored sorted"
)
SOURCE = (
    "Local database (daily candles to 2026-09-08). used_49 = instruments with is_active and "
    "is_watchlisted (the walk_forward universe). population = active instruments with segment NSE, "
    "instrument_type EQ and at least one 'day' candle, minus used_49. Index series (segment INDICES) "
    "excluded. Matches the 306 = 49 + 257 count in "
    "docs/brain/evidence/wider_universe_data_check_2026-10-12.md. used_49 also equals every "
    "watchlist_snapshots day (2026-10-05..2026-10-16). Read on 2026-10-21 with the same filters as "
    "load_from_db (SQL: is_active and segment='NSE' and instrument_type='EQ' and exists a 'day' "
    "candle, minus is_active and is_watchlisted)."
)
FILE_NAME = "stock_split_ev15.json"
NOTE_NAME = "stock_split_ev15.md"


def split_population(population: Sequence[str], seed: int = SEED) -> tuple[list[str], list[str]]:
    """Return (reject_set, extra_training_set), each sorted. Deterministic for a given seed."""
    ordered = sorted(set(population))
    if len(ordered) != POPULATION_SIZE:
        raise ValueError(f"expected {POPULATION_SIZE} distinct stocks, got {len(ordered)}")
    shuffled = list(ordered)
    random.Random(seed).shuffle(shuffled)
    return sorted(shuffled[:REJECT_SIZE]), sorted(shuffled[REJECT_SIZE:])


def build(used_49: Sequence[str], population: Sequence[str]) -> dict:
    used, pop = sorted(set(used_49)), sorted(set(population))
    if len(used) != USED_SIZE:
        raise ValueError(f"expected {USED_SIZE} used stocks, got {len(used)}")
    if set(used) & set(pop):
        raise ValueError("population overlaps the 49 used stocks")
    reject, extra = split_population(pop)
    return {
        "task": "ev15",
        "plan": "docs/superpowers/specs/2026-10-15-evidence-and-pilot-plan.md section 3",
        "seed": SEED,
        "rng": "Python random.Random (Mersenne Twister), shuffle",
        "algorithm": ALGORITHM,
        "source": SOURCE,
        "used_49": used,
        "population": pop,
        "reject_set": reject,
        "extra_training_set": extra,
    }


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def note(result: dict, sha: str) -> str:
    return f"""# ev15: stock split for Phase B (locked)

Evidence plan section 3: the never-used stocks are split once, before the first Phase B run
(9 Nov 2026), so no one can pick the split after seeing results.

- **Reject set ({len(result["reject_set"])} stocks)**: never used to train any candidate. Used only for
  the robustness check, which can reject a candidate but never confirm one.
- **Extra training set ({len(result["extra_training_set"])} stocks)**: used only by candidate B2
  (trains on the 49 + these 128 = 177 stocks, scored on the same 49).
- The 49 stocks the model already uses are not part of the split.

| Item | Value |
|---|---|
| Population | {len(result["population"])} never-used stocks |
| Seed | {result["seed"]} (project standard seed; the plan names none for this split) |
| Random generator | {result["rng"]} |
| Algorithm | {result["algorithm"]} |
| Source | {result["source"]} |
| File | `{FILE_NAME}` |
| SHA-256 of file | `{sha}` |

Reproduce: `backend/tests/test_stock_split.py` recomputes the split from the committed population and
checks it against the lists and this hash. Do not edit or regenerate the JSON: any change breaks the
hash and the test, which is the point.
"""


def write(result: dict, directory: Path) -> tuple[Path, Path, str]:
    directory.mkdir(parents=True, exist_ok=True)
    js, md = directory / FILE_NAME, directory / NOTE_NAME
    if js.exists():
        raise FileExistsError(f"{js} exists: the split is locked and is never regenerated")
    js.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8", newline="\n")
    sha = file_sha256(js)
    md.write_text(note(result, sha), encoding="utf-8", newline="\n")
    return js, md, sha


def load_from_db(db) -> tuple[list[str], list[str]]:
    from sqlalchemy import select

    from swing_trade_ml.db.models.market import Candle, Instrument

    used = db.execute(
        select(Instrument.tradingsymbol).where(
            Instrument.is_active.is_(True), Instrument.is_watchlisted.is_(True)
        )
    ).scalars()
    with_candles = select(Candle.instrument_id).where(Candle.interval == "day").distinct()
    shares = db.execute(
        select(Instrument.tradingsymbol).where(
            Instrument.is_active.is_(True),
            Instrument.segment == "NSE",
            Instrument.instrument_type == "EQ",
            Instrument.id.in_(with_candles),
        )
    ).scalars()
    used_set = set(used)
    return sorted(used_set), sorted(set(shares) - used_set)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    from swing_trade_ml.db.session import SessionLocal

    p = argparse.ArgumentParser(description="ev15: seeded reject / extra-training stock split")
    p.add_argument("--out", default="../docs/brain/evidence/stock_split")
    a = p.parse_args(argv)
    with SessionLocal() as db:
        used, population = load_from_db(db)
    result = build(used, population)
    js, md, sha = write(result, Path(a.out))
    sys.stdout.reconfigure(errors="replace")
    print(
        f"used {len(used)}, population {len(population)}, reject {len(result['reject_set'])}, "
        f"extra {len(result['extra_training_set'])}"
    )
    print(f"Written: {js} and {md}; sha256 {sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
