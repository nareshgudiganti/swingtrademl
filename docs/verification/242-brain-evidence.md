# #242 Verification: Brain decisions carry evidence, WATCH explains itself

Baseline: main at 5de3b9c (23-24 Nov 2026 IST). Tests and this note only. No change to Brain decision code, frozen files, models or the sealed trial.

## In plain English

- Every decision word the Brain can give has a rule behind it, and the first reason on the card names that rule's real cause. Ideas: TRADE, WATCH, WAIT, AVOID. Holdings: HOLD, MONITOR, REDUCE, EXIT. Each rule's first reason is checked for the text that names its cause; the tests do not prove no generic line exists anywhere.
- When a rule holds an idea back, the card keeps the first reason as the reason it was held back, and the size goes to zero. The word only ever moves toward caution.
- WATCH from the risk check quotes the risk gate's own words. I produced 16 of its refusals through the REAL risk gate (not copied text). Every one maps to a specific "what would change it" line, not the catch-all "account limits" line.
- The "what would change it" numbers match the numbers the rules use (sector top N, 15% drawdown, minimum position, half-size in a defensive market).
- The banner explains itself: missing risk gate, owner pause, stale market data, a module's own headline, a defensive suggestion, and "Market state is unknown".
- One thing is shown but not fixed: the "15 trading days" label on 5-day scores (#385), pinned as two strict expected failures that state the intended behaviour.

## Results

| # | Check | File:line (baseline) | Expected | Observed | Result |
|---|---|---|---|---|---|
| 1 | Each idea rule: word, first reason names cause, evidence line, downgrade reason = first reason | `brain/modules/m08_decide/rules.py` IDEA_RULES, `engine.py` `_draft_idea` | 8 rules, 8 scenarios, specific line each | as expected; a new rule without a scenario fails the test | pass |
| 2 | Each holding rule | `rules.py` HOLDING_RULES | EXIT/REDUCE/MONITOR/HOLD with cause first | as expected; stop and first target fire exactly at their levels, lagging at -10% | pass |
| 3 | WATCH from risk check quotes the real reason | `rules.py` risk_check, `services/what_would_change.py` `_risk_line` | specific line per refusal | 16 real gate refusals all mapped to specific keys | pass |
| 4 | Thresholds in "what would change" equal rule thresholds | `what_would_change.py:104-245` | same numbers | sector top N, 15%, minimum, half size agree | pass |
| 5 | Banner explains NO_NEW_TRADES / DEFENSIVE | `brain/constitution.py` `enforce` | headline names the cause | as expected | pass |
| 6 | 15-day label on 5-day scores | `engine.py` plan line, `contracts.py` `Opinion.horizon_days` | label matches the score's horizon | label is always "15 trading days"; no Brain opinion sets its own horizon | gap #385, strict xfail x2, not fixed |

## Limits

- Two risk refusals (LIQUIDITY needs 20 days of stored traded value; CASH is believed to be shadowed by the cash-sized ceiling (not tested)) are not produced through the real gate. They are covered by copied text in `test_what_would_change.py`.
- Trace access is covered by a separate access-control change; not re-verified here.
- A held-back idea keeps its entry zone, target and stop (only size goes to 0). Pinned by a test; screens must not show those levels as an instruction.

## Not tested

- Order of reasons when several causes apply at once: only single-cause scenarios are run, so "the first reason is the deciding one" is shown per rule, not for combinations.

## Tests

New: `backend/tests/test_brain_evidence_verification.py` (55 pass, 2 strict xfail). Existing suites cited: `test_brain_m08_engine.py`, `test_what_would_change.py`, `test_brain_caution_only.py`, `test_brain_what_would_change_api.py`, `test_brain_api.py`.
