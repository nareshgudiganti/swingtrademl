# Corporate actions and paper positions (stock splits and bonus issues only)

Status: built, switched off. Nothing is scheduled, wired into the app, or exposed as an API route. It is a set of
functions the owner runs by hand after checking the company's announcement.

## The problem in one paragraph

When a company splits its shares or issues bonus shares, the exchange price drops (for example it halves in a 2-for-1
split) but the owner is not poorer: there are now twice as many shares. A paper position still records the old share
count and the old entry price, so the raw price looks like a 50% loss and the stop-loss would fire for no real reason.
The audit on 2026-11-03 found no past paper position (Bot or Testing book) held across such a date, so no history
needs repair. This work covers the forward risk.

## What is implemented

1. Two new tables, `corporate_actions` (the verified event, entered by hand) and `position_adjustments` (what the
   event did to each position). Nothing existing is altered.
2. Verified STOCK SPLITS and BONUS issues only. For a factor k (split 10 to 2 gives k = 5; bonus 1 new for every 2
   held gives k = 1.5; bonus 1:1 gives k = 2) an open position gets: shares and initial shares x k; entry price, stop,
   target, highest price, initial stop (and any broker stop price) / k. Charges are unchanged. Money invested
   (shares x entry price) is unchanged, so the paper cash figure does not move.
3. If shares x k is not a whole number (for example 101 shares with a 1:2 bonus) nothing is guessed: the position is
   flagged NEEDS_REVIEW with the reason.
4. Only positions that were open before the ex-date are touched. Closed positions, and positions bought on or after the
   ex-date, are never changed. Real-money or own-holdings positions are never changed (the broker holds the truth).
5. Safe by default: `apply_action(db, action_id)` is a dry run that returns the planned changes and writes nothing.
   A real change needs `apply=True`. The caller commits.
6. Re-running changes nothing: one adjustment row per (action, position), enforced by a database unique key. Each row
   holds the complete before and after of every changed field.
7. `review_open_positions(db, today, alert=...)` finds open positions held across a verified action's ex-date that
   have no APPLIED row, writes a NEEDS_REVIEW row (once), and returns plain-English lines. It accepts an alert function
   but sends nothing itself.
8. Bot and Testing books use the same code path and are tested separately.

## Exits are never suspended (the "never hide losses" rule)

- `check_exits` and every exit rule are unchanged. A position with an unresolved event can still hit its stop-loss,
  target or time stop exactly as before. There is no pause, no grace period and no skip.
- When an event leaves a mismatch, the position is flagged for immediate review, and the record includes what the
  original exit rules would do with the raw price (for example "raw price 900 <= stop 960 would trigger
  STOP_LOSS_HIT"), worked out on a copy so nothing is modified.
- Raw P&L stays as it is. A loss is never hidden; once a verified split or bonus is applied, the figures are simply on
  the new share basis.
- Original Orders, Trades, prices and signed evidence are untouched. No fake Order or Trade row is ever written.

## What is NOT implemented, and why

Demerger, rights issue, dividend (ordinary or special), merger, buyback and reverse split are stored and flagged
NEEDS_REVIEW only. Each is "not implemented: needs confirmed entitlement, availability dates, valuation and cash
treatment". Never use a tax cost-of-acquisition percentage as a market-price adjustment factor: it is a tax figure, not
the price split between the old and new company, and it is often published after the ex-date.

## How the owner enters a verified action

1. Read the company's own announcement (exchange filing) and note the ex-date and ratio.
2. Insert a `corporate_actions` row: instrument, `kind` = `split` or `bonus`, `ex_date`, ratio, `source_url`, and
   `status` = `VERIFIED` only after the announcement is checked. Split: `ratio_numerator` = old face value,
   `ratio_denominator` = new face value (10 and 2). Bonus: numerator = new shares, denominator = shares held (1 and 2).
3. Run `apply_action(db, id)` first (dry run), read the planned before and after, then `apply_action(db, id, apply=True)`
   and commit. Do this on the morning of the ex-date, before the first exit check.
4. Run `review_open_positions(db, today)` any day to list positions that still need attention.

## Checklist before any later phase (demerger, rights, dividend, merger)

- Confirmed entitlement (how many new shares or how much cash per share held).
- Availability dates (record date, ex-date, when the new shares or cash actually arrive).
- Valuation (what the new instrument is worth, from a published price, never a guess).
- Cash treatment (how paper cash changes, with its own ledger, not a fake trade).
- No automatic tax cost-of-acquisition percentage as a price factor.
- Owner approval, a test, and a dated note, because these touch cost basis.

## Files

`db/models/corporate_actions.py`, `services/corporate_action_accounting.py`,
`alembic/versions/20261103_1800_corporate_actions.py`, `tests/test_corporate_action_accounting.py`. No fingerprinted
trial file is edited.
