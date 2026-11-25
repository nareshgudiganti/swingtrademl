# #389 stock identity: decisions for the owner

Status: DESIGN ONLY. No code, migration, engine change or production query. Written 2026-11-25 (IST) against `origin/main`
`36bb2830`. Builds on `docs/design/389-consolidated-design-proposal.md` (branch `docs/389-consolidated-audit`, commit `424e814c`,
written against `13b9c31b`). Paths are under `backend/src/swing_trade_ml/` unless stated. Times are IST.

## 0. Checks done

1. The three built branches are in `main`. `git merge-base --is-ancestor <merge commit> origin/main` succeeded for all three:
   - PR #448 (identity phase 1): merge commit `90f0250f`, in main.
   - PR #452 (read contract, consumers): merge commit `a14b4286`, in main.
   - PR #456 (cross-module checks, admin callers): merge commit `1f8402a7`, in main.
2. Between the audit base `13b9c31b` and the current main `36bb2830` only 7 files changed (Dockerfile, release scripts, `ml/model_card.py`,
   a build-plumbing test, a Feature 1 status file). Nothing touches identity, so the audit's findings still hold. I re-checked each
   decision against the code itself (results below), not only against that diff.

## 1. The 12 decisions: status on main

| # | Decision (audit section 6) | Open on main? | What merged code already settles |
|---|---|---|---|
| 1 | Keep or drop the three unmerged `feat/389-*` twins | OPEN | Nothing. Main has every file they add, but the branches are still not ancestors of main. |
| 2 | ISIN source (own Groww holdings, manual NSE file, NSE licence) | OPEN | `securities.isin` is nullable and unique (`db/models/identity.py:56`); the comment at :54 says no ISIN source is loaded. The resolver accepts a well-formed ISIN (`services/identity/__init__.py:40`) but nothing supplies one. |
| 3 | Prediction identity key | PARTLY SETTLED, still open for `predictions` | `horizon_records` has a unique key `(security_id, session_date, horizon_days, coalesce(model_id,-1), model_version, revision)` (`db/models/horizon.py:75-84`). That is the audit's "C" key, built for the per-horizon workflow. There is still no `prediction_id`; `predictions` is untouched and `ml/predict.py` (frozen) still overwrites. |
| 4 | Signal key | PARTLY SETTLED | `signals.signal_key` exists (migration `signalkey01`, `services/execution.py:65-73`): `strategy.id:instrument.id:mode:kind:horizon:session`. It uses `instrument.id`, not `security_id`, and has no `rule_version`. The qualifying-signal rule is still undefined. |
| 5 | Nullable `security_id` on `instruments` and `user_watchlist_items` | OPEN | No such column on main (grep of `db/models/market.py`, `db/models/user.py`: none). The link lives in `security_aliases` (kite token). |
| 6 | `predictions.model_id` CASCADE to RESTRICT | OPEN | Still `ondelete="CASCADE"` at `db/models/ml.py:117`. Newer tables use RESTRICT (`lane_shadow.py:38`, `horizon.py:45`). |
| 7 | Brain horizon labelling (#385) | PARTLY SETTLED | The ledger already stores `horizon_days=None` when the model is unknown (`services/score_history.py:296,313,366`; read API says "None when the model is unknown"). Brain contracts still default 15 (`brain/contracts.py:78,226,245,279`, frozen). |
| 8 | One verdict vocabulary | PARTLY SETTLED | Horizon decisions are fixed by code: TRADE, WATCH, WAIT, NO_DECISION (`db/models/horizon.py:36`, DB check constraint). Signal types (BUY/SELL kinds in `signal_key`) are a separate list, not mapped. |
| 9 | Data quality per stock per session in the ledger | OPEN | Ledger `status` (scored, missing, stale, late, no_score) is the only per-stock gap signal. Brain `DataQuality@1` is not linked to `security_id`. G10 (see `g8-g10-evidence-and-decisions.md`) would add candle-level events; this decision says whether they feed the ledger. |
| 10 | Production migration of `identity01` and later | OPEN | Needs a deploy approval. Not verifiable from the repo and I did not query production. Migration files on main: `identity01` (20261123), `horizon01` (20261124), `simulation_persistence` (20261125), `signalkey01` and `simulation_rule_ref` (20261126). |
| 11 | Defects test file `test/389-identity-defects` | OPEN | The file is not on main (no `test_identity_defects_389.py` in the tree). Whether its xfails now fail strictly was not run. |
| 12 | Deliver the `docs/389-*` design docs to main or keep as history | OPEN | Not on main; only `docs/architecture/IDENTITY-READ-API.md` is. |

Decisions already made by merged code: none is closed completely. #3, #4, #7 and #8 are narrowed (above); the owner now chooses
whether to adopt what was built or change it. All 12 remain open in some form.

## 2. Decisions, one section each

### D1. Unmerged `feat/389-*` twins (decision 1)
- Options: (a) keep until the owner archives; (b) tag each tip (for example `archive/389-identity-phase1`), then delete the branch and its worktree; (c) delete without tags.
- Recommendation: (b), after a one-time check that no commit in a twin is missing from main. Not verified yet.
- Touches: nothing frozen, no trial effect, no migration. Deleting a branch is a manual owner step by project rule.
- Question: "May I tag and then remove the three `feat/389-*` branches, or keep them?"

### D2. ISIN source (decision 2)
- Options: (A) manual NSE equity list file loaded once by an admin script; (B) NSE data licence; (C) read ISINs from the owner's own Groww holdings (covers held stocks only).
- Recommendation: (A). It covers the whole watchlist and costs nothing. C covers too few stocks; B costs money.
- Touches: `securities.isin` column already exists, so no migration. Loading data is a production write (needs approval). Not frozen, no trial effect.
- Question: "Which ISIN source: A (NSE file), B (licence) or C (Groww holdings only)?"

### D3. Prediction identity (decision 3)
- Options: (a) adopt the `horizon_records` key as the one prediction identity and add no `prediction_id` to `predictions`; (b) add a `prediction_id` to `predictions` (touches the frozen overwrite in `ml/predict.py`, or a database trigger); (c) the issue body's key (stock, scan, model, horizon, cutoff). `horizon_records` already carries `scan_key` and `input_cutoff`, so (c) can be shown as extra fields without a new key.
- Recommendation: (a), written into `IDENTITY-READ-API.md`. `predictions` stays untouched during the trial.
- Touches: (a) docs only. (b) frozen file or migration plus trial risk.
- Question: "Is the horizon-record key the official prediction identity, with no change to the `predictions` table?"

### D4. Signal key and the "qualifying signal" (decision 4)
- Options: (a) keep the `instrument.id` key as is, document it, define "qualifying" separately; (b) rewrite to `security_id` plus `rule_version` (changes key text, so retries of old signals no longer match and trial signal counts can change).
- Recommendation: (a) now. Revisit (b) after the trial because it changes trial behaviour.
- Touches: `services/execution.py` is not on the freeze list, but a key change alters how many signals a retry creates. Needs a trial-behaviour check.
- Question: "Keep today's signal key until the trial ends? And what makes a signal 'qualifying' (a score threshold, a decision word, or something else)?"

### D5. `security_id` on `instruments` and watchlist rows (decision 5)
- Options: (a) add nullable columns, one table per migration; (b) keep the alias table as the only link.
- Recommendation: (b) until a feature needs a direct join. Consumers built so far resolve through `resolve()`.
- Touches: (a) is a schema migration and needs approval; no frozen file.
- Question: "Do you want direct `security_id` columns now, or keep the alias link?"

### D6. `predictions.model_id` CASCADE to RESTRICT (decision 6)
- Options: (a) change to RESTRICT (a model with predictions can no longer be deleted); (b) leave.
- Recommendation: (a) after the trial, in its own migration. Today deleting a model deletes its prediction history, which is evidence loss.
- Touches: migration (approval required) on a table the frozen `ml/predict.py` writes. Trial: no behaviour change unless someone deletes a model.
- Question: "Approve RESTRICT on `predictions.model_id`, now or after the trial?"

### D7. Brain horizon label (decision 7)
- Options: (a) leave the brain default 15 and let the ledger store `None` or the real horizon (today); (b) change `brain/contracts.py` defaults (frozen).
- Recommendation: (a). Display layers must read the ledger, not the brain default.
- Touches: (b) frozen file; trial approval via `scripts/approve_trial_change.py`.
- Question: "Confirm that the brain's default 15 stays untouched during the trial?"

### D8. Verdict words (decision 8)
- Options: (a) two lists kept apart and documented (horizon: TRADE/WATCH/WAIT/NO_DECISION; signal: BUY/SELL kinds); (b) one merged list.
- Recommendation: (a); add a mapping table to the read API doc.
- Touches: docs only for (a). (b) touches a DB check constraint and brain vocabulary (frozen).
- Question: "Keep the two word lists and document the mapping?"

### D9. Data quality in the ledger (decision 9)
- Options: (a) ledger `status` only; (b) add candle-event links (from G10) per stock per session; (c) brain only.
- Recommendation: (a) now; decide (b) when G10 is approved.
- Touches: (b) migration. No frozen file.
- Question: "Should candle problems (late, corrected, missing) appear beside each stock's score history?"

### D10. Production migration (decision 10)
- Options: deploy with the next owner-approved release; wait until after the trial.
- Recommendation: deploy with the next approved release; the identity tables are additive and nothing frozen reads them. Rehearse first (`backend/scripts/rehearse_p0_migration.py` is the existing pattern).
- Touches: production database; a deploy approval is required (a merge does not deploy).
- Question: "Which release carries the identity and later migrations, and who runs the deploy?"

### D11. Defects tests (decision 11)
- Options: rebase and merge as strict xfail; run first and drop those main already fixed; drop all.
- Recommendation: run on a rebased branch first (needs Docker Postgres) and keep only the tests still failing.
- Touches: tests only.
- Question: "May an agent rebase and run `test/389-identity-defects` and keep only the tests still failing?"

### D12. Design docs on main (decision 12)
- Options: merge one trimmed document into `docs/architecture/`; keep on branches as history.
- Recommendation: merge one document after D2-D9 are answered, so it states what is decided.
- Touches: docs only.
- Question: "Merge the design docs after your answers, or leave them on branches?"
