# Deferred: Codex finding 9 — never rewrite a scored prediction

Status: DEFERRED by the owner on 2026-11-16. The `ml/predict.py` code change is not present (the file is
unchanged from HEAD); only this note and the parked test file are kept.

Why deferred: `ml/predict.py` is pinned by file hash in the h05 protocol
(`brain/lanes/h05_models.py`). Any edit to it makes the h05 lane refuse to run and fails
9 tests (`test_h05_hardening.py` 1, `test_h05_service.py` 8). Re-pinning h05 needs a separate owner
decision, which has not been made.

The change that was reverted (in `_upsert_prediction`, inside `on_conflict_do_update(...)`):

```python
        # A row the outcome job has already scored is track-record evidence: a re-run may refresh an
        # unscored prediction but must never rewrite one that has been scored (Codex audit finding 9).
        where=Prediction.evaluated_at.is_(None),
```

Its tests are kept in `test_prediction_history_guard.py.txt` (renamed so pytest does not collect it).
To revive: owner approves an h05 re-pin (or picks another approach), restore the line and rename the
test back into `backend/tests/`, then record the frozen-file change with
`backend/scripts/approve_trial_change.py`.
