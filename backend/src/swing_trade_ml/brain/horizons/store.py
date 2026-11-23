"""Run history, labels and evaluations, kept apart per horizon.

In memory only. A database table for these records is a schema migration and needs the owner's
approval first; this class is the contract such a table must keep.

History and counts are different things:
- `runs()` and `evaluations()` are the append-only history, one entry per run. A rerun is kept as its own
  record and nothing is erased or rewritten.
- Every count or summary counts one (horizon, symbol, input session, model name, model version) once. That
  is the idempotency key, the same one `labels()` uses. Running the same stock, session and model version
  twice therefore adds history but never adds a count. A different model version is its own key.
  A key counts as "complete" if any of its runs completed (its label exists), otherwise as the first
  finished result ("unmeasurable" or "no_decision"), otherwise "pending". NO_DECISION runs have no model,
  so their key has no model name or version.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import date

from swing_trade_ml.brain.horizons.evaluate import Bar, Evaluation, evaluate_record
from swing_trade_ml.brain.horizons.policy import HORIZONS
from swing_trade_ml.brain.horizons.workflow import NO_DECISION, HorizonRecord

LabelKey = tuple[str, date, str, str]  # symbol, input session, model name, model version
RunKey = tuple[str, date, str | None, str | None]  # the same, where a NO_DECISION run has no model
FINISHED = {"complete", "unmeasurable", "no_decision"}


def run_key(record: HorizonRecord) -> RunKey:
    """The idempotency key: the horizon is the store's own partition, the rest identify the run."""
    return (record.symbol, record.input_session, record.model_name, record.model_version)


class HorizonStore:
    def __init__(self) -> None:
        self._runs: dict[int, list[HorizonRecord]] = {h: [] for h in HORIZONS}
        self._evaluations: dict[int, list[Evaluation]] = {h: [] for h in HORIZONS}
        self._labels: dict[int, dict[LabelKey, int]] = {h: {} for h in HORIZONS}

    def add(self, record: HorizonRecord) -> None:
        if record.decision_horizon not in self._runs:
            raise ValueError(f"no history for horizon {record.decision_horizon}; expected one of {HORIZONS}")
        self._runs[record.decision_horizon].append(record)
        self._evaluations[record.decision_horizon].append(Evaluation("pending"))

    def runs(self, horizon: int) -> list[HorizonRecord]:
        return list(self._runs[horizon])

    def labels(self, horizon: int) -> dict[LabelKey, int]:
        return dict(self._labels[horizon])

    def evaluations(self, horizon: int) -> list[Evaluation]:
        return list(self._evaluations[horizon])

    def evaluation_summary(self, horizon: int) -> dict[str, int]:
        """One count per run key (see the module docstring), consistent with `labels()`."""
        per_key: dict[RunKey, str] = {}
        for record, evaluation in zip(self._runs[horizon], self._evaluations[horizon], strict=True):
            key = run_key(record)
            current = per_key.get(key)
            status = evaluation.status
            if current is None or current == "pending":
                per_key[key] = status
            elif status == "complete" and current != "complete":
                per_key[key] = status  # a label exists for this key, so it is complete
        return dict(Counter(per_key.values()))

    def evaluate_due(
        self, sessions: Sequence[date], bars_by_symbol: Mapping[str, Mapping[date, Bar]], *, as_of: date
    ) -> None:
        """Re-check every unfinished record of every horizon. Finished results are never rewritten."""
        for horizon in HORIZONS:
            for i, record in enumerate(self._runs[horizon]):
                if self._evaluations[horizon][i].status in FINISHED:
                    continue
                if record.decision == NO_DECISION:
                    result = evaluate_record(record, sessions, {}, as_of=as_of)
                else:
                    result = evaluate_record(
                        record, sessions, bars_by_symbol.get(record.symbol, {}), as_of=as_of
                    )
                self._evaluations[horizon][i] = result
                if result.status == "complete":
                    assert record.model_name is not None and record.model_version is not None
                    key = (record.symbol, record.input_session, record.model_name, record.model_version)
                    # first finished result wins; a rerun is its own evaluation, never a rewrite
                    self._labels[horizon].setdefault(key, result.label)
