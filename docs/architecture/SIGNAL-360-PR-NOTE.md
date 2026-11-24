# PR note: one v1 signal per scan decision (#360)

**What changed.** `signals.signal_key` (nullable, 96 chars) = strategy, stock, mode, type, horizon, session (the last
closed trading day of the scan time, so a retry after midnight keeps its session). `record_signal` returns the existing
row for a key instead of inserting; a unique index (only where the key is set) plus a savepoint make a concurrent scan
return the winner's row. `process_decision` returns a settled signal (executed, rejected, advisory-handled, HOLD)
unchanged: no second risk check, order, alert or risk event. An unsettled row (written, no order) is reused so the retry
completes the buy exactly once. Rows with no key are never touched. No sizing, stop, limit or threshold changed; no
frozen file edited (`execution.py` and `models/trading.py` are not in `trial_freeze.json`).

**Migration.** `signalkey01` (after `simulation01`): add column, add partial unique index. Additive, no backfill,
downgrade drops both. Single head; head pins in two tests updated.

**Tests.** `tests/test_signal_idempotency.py` (9), the #360 xfail now a plain pass. Four existing tests that made two
decisions for one stock in one session now advance the clock to a later session (a same-session repeat is a retry by
design) or stub the new lookup.

**Risk review.** Touches the signal-to-order path: needs owner approval before `main`.

**Open owner question.** Merge before or after the sealed trial's review? The change alters no value, but it changes
what a repeated same-session decision records (one row instead of two).
