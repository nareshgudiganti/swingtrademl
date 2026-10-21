"""ev15: the locked Phase B stock split is reproducible and has not been edited."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from swing_trade_ml.brain.stock_split import (
    ALGORITHM,
    EXTRA_SIZE,
    FILE_NAME,
    NOTE_NAME,
    REJECT_SIZE,
    SEED,
    build,
    file_sha256,
    split_population,
)

DIR = Path(__file__).resolve().parents[2] / "docs" / "brain" / "evidence" / "stock_split"


@pytest.fixture(scope="module")
def locked() -> dict:
    return json.loads((DIR / FILE_NAME).read_text(encoding="utf-8"))


def test_file_hash_matches_note() -> None:
    recorded = re.search(
        r"SHA-256 of file \| `([0-9a-f]{64})`", (DIR / NOTE_NAME).read_text(encoding="utf-8")
    )
    assert recorded, "note must record the file's SHA-256"
    assert file_sha256(DIR / FILE_NAME) == recorded.group(1)


def test_split_recomputes_from_population(locked: dict) -> None:
    assert locked["seed"] == SEED == 7
    assert locked["algorithm"] == ALGORITHM
    reject, extra = split_population(locked["population"], locked["seed"])
    assert reject == locked["reject_set"]
    assert extra == locked["extra_training_set"]
    assert build(locked["used_49"], locked["population"]) == locked


def test_sizes_and_disjoint(locked: dict) -> None:
    used, pop = set(locked["used_49"]), set(locked["population"])
    reject, extra = set(locked["reject_set"]), set(locked["extra_training_set"])
    assert len(used) == 49 and len(pop) == 257
    assert len(reject) == REJECT_SIZE == 129 and len(extra) == EXTRA_SIZE == 128
    assert not reject & extra
    assert reject | extra == pop
    assert not (reject | extra) & used


def test_split_is_seed_sensitive_and_order_free(locked: dict) -> None:
    pop = locked["population"]
    assert split_population(list(reversed(pop))) == split_population(pop)
    assert split_population(pop, seed=8) != split_population(pop)


def test_wrong_population_refused() -> None:
    with pytest.raises(ValueError):
        split_population([f"S{i}" for i in range(256)])
