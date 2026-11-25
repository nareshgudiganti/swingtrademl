# #389 consolidated audit: branches, overlaps, contracts, owner decisions

Status: READ-ONLY AUDIT. No code, migration, schema or contract is implemented here. Written 2026-11-25 (IST) against
`origin/main` `13b9c31b`. Nothing was run against production or a database. Times are IST.

## 0. In plain English

The task named "eight" #389 branches. `git branch -a --list "*389*"` finds nine local names (three also on origin).
The most important finding: **the three built branches are already merged into `main`** (PRs #448, #452, #456). What is
left unmerged is design documents, one defects test file and three local `feat/` twins of the merged branches. The real
open work is not "pick a branch": it is that the written contracts and the merged code disagree in a few places
(section 4), and several contracts the Feature 1-3 issues need have no home yet.

## 1. Branch table

Ahead/behind are against `origin/main` (13b9c31b). "Pushed" = exists on origin.

| Branch | Last commit (IST, SHA, author) | Ahead | Files changed (vs merge base) | Pushed | PR | Worktree |
|---|---|---|---|---|---|---|
| `feature/389-stock-identity-phase1` | 2026-11-23 16:57 `018a6544` N. Gudiganti | 0 | none left (merged) | yes | #448 MERGED 2026-11-23 | pr-389-wt |
| `feature/389-identity-consumers` | 2026-11-23 18:02 `dcbbab04` (origin tip `58f91440`) | 0 | none left (merged) | yes | #452 MERGED 2026-11-23 | pr-389-consumers-wt |
| `feature/389-identity-verify` | 2026-11-23 21:26 `2ccb743d` (origin tip `2a94527f`) | 0 | none left (merged) | yes | #456 MERGED 2026-11-24 | pr-389-verify-wt |
| `feat/389-identity-phase1` | 2026-11-23 16:56 `454dad11` | 8 | 18 files, +2552/-14: migration `identity01`, `db/models/identity.py`, `services/identity/*`, `ingestion.py`, `score_history.py`, `held_read.py`, 7 tests | no | none | identity-build-wt |
| `feat/389-identity-consumers` | 2026-11-23 18:01 `60a627fa` | 4 | 7 files, +755/-1: `identity/consumers.py`, `ledger.py`, `score_history.py`, `IDENTITY-READ-API.md`, 3 tests | no | none | identity-consumers-wt |
| `feat/389-identity-verify` | 2026-11-23 19:07 `72562e1e` | 5 | 21 files, +2583/-98: `simulation/store.py`, `db/models/simulation.py`, migration `simulation_persistence`, `identity/admin.py`, cross-module tests (note: "multiple merge bases") | no | none | identity-verify-wt |
| `docs/389-stock-identity-design` | 2026-11-23 10:13 `64f8cb43` | 2 | `STOCK-IDENTITY-DESIGN.md` (409 lines), `MODEL2-TRACEABILITY.md` (231) | no | none | identity-wt |
| `docs/389-identity-contracts` | 2026-11-23 11:58 `fb4a9d0c` | 1 | `IDENTITY-CONTRACTS.md` (227 lines) | no | none | contracts-389-wt |
| `test/389-identity-defects` | 2026-11-23 10:17 `a27df8ad` | 1 | `backend/tests/test_identity_defects_389.py` (276 lines, strict xfail for #355/#360-type defects) | no | none | identity-tests-wt |

All authored by Naresh Gudiganti (git identity). Local `feature/*` consumers and verify tips differ from their origin
tips (`dcbbab04` vs `58f91440`; `2ccb743d` vs `2a94527f`): they look like merge-from-main commits; not diffed further.

How the `feat/` twins relate to the merged `feature/` branches: `git diff feat/X feature/X` is large (49, 27, 14 files),
but that is because `feature/*` were branched from a newer main. Their own work is the same slices. `feat/389-identity-phase1`,
`-consumers` and `-verify` are NOT ancestors of `origin/main` (checked with `merge-base --is-ancestor`), yet main already has
every file they add (`services/identity/*`, `simulation/store.py`, migration `identity01`, `simulation_persistence`).
Whether the twins hold any commit not in the merged branches was not verified line by line.

## 2. Overlap groups

- **Group A, identity code (same files, same idea):** `feature/389-stock-identity-phase1` (#448) = `feat/389-identity-phase1`;
  `feature/389-identity-consumers` (#452) = `feat/389-identity-consumers`; `feature/389-identity-verify` (#456) =
  `feat/389-identity-verify`. Overlapping files: `services/score_history.py`, `services/identity/ledger.py`,
  `tests/test_identity_review_fixes.py`, `tests/test_user_name_mobile.py`. Superseded by main.
- **Group B, design documents (same idea, different depth):** `docs/389-stock-identity-design` (inventory, trace, S0-S7 plan,
  9 open questions) and `docs/389-identity-contracts` (turns it into rules D1-D9, adds signal and prediction rules). The
  contracts doc cites the design doc and says where it differs. On main: `IDENTITY-READ-API.md` (the as-built read contract).
  Neither design doc is on main.
- **Group C, evidence:** `test/389-identity-defects` (two suspected defects as strict xfail: same-day re-run overwrites a daily
  score and uses clock date; re-issued Kite token loses the batch). Touches `services/score_history.py` and
  `services/ingestion.py`, the same files as Group A; the main code may have fixed these, so the xfails may now fail
  strictly. Not run.
- No branch overlaps `MODEL2-TRACEABILITY.md` (it is about model 2 inputs, #226, not identity design).

**Most complete:** `feature/389-identity-verify` (#456), now in main: it contains phase 1 + consumers + cross-module + admin
callers + simulation persistence. Among unmerged branches: `feat/389-identity-verify` by line count, but it is stale.
**Most reusable design:** `docs/389-identity-contracts` (rules with owner decisions D1-D9, rollback and tests per contract), on top
of `docs/389-stock-identity-design` (the inventory and S0-S7 steps). `IDENTITY-READ-API.md` on main is the best as-built contract.

## 3. What Features 1-3 need from #389

#389 (issue body): one permanent stock id; immutable `prediction_id` = stock + scan + model version + horizon + input cutoff;
`scan_id` per logical scan (retries reuse it); `signal_id` for a qualifying research signal (PAYTM 90, 50, 80, 95 example);
separate Brain provenance. #390 (absorbed into #389): inventory IDs, idempotency, alias mapping, account isolation, missing
data, independent horizon windows. #386: daily Brain and model score snapshots with model version and session date, gaps not
interpolated, separate trails across model-version changes. #387: per-horizon workflows storing model version, input session,
decision horizon. #282: the issue body has no matching terms for these contracts (not verified in comments).

## 4. Contract table

"D" = `docs/389-stock-identity-design`; "C" = `docs/389-identity-contracts`; "main" = `origin/main` code.

| Contract | Defined where | Conflict between definitions? |
|---|---|---|
| stock identity `security_id` | C section 1, D 5.1; as built in main `db/models/identity.py` (`securities`, `security_symbols`, `security_aliases`), `services/identity.resolve()` | Mild. C names the alias table `stock_aliases` (Groww branch) and the resolver `services/security_resolver.py`; main built `security_aliases` and `services/identity/__init__.py`. C says nullable `security_id` on `instruments`/`user_watchlist_items`; main has none (#389 comment: "not yet"). `isin` is nullable in main, "not null" in C. No ISIN source loaded. |
| score history | D 5.3, C section 4, main `ScoreLedger` + `IDENTITY-READ-API.md` | Key differs: D = security, session, horizon, source, model_id, model_version, scan_key, revision; C = per section 4 (not fully diffed); read API says key = session, horizon, source, model name, model version. Brain rows leave horizon `None` (#385) in main; D/C expect horizon. |
| prediction identity / `prediction_id` | C section 2 key `(security_id, session_date, horizon_days, model_id, model_version, revision)`; D 5.2 key `(security_id, model_id, horizon_days, input_cutoff)`; #389 body: stock + scan + model + horizon + cutoff | **Conflict:** three different keys. Main has no `prediction_id`; `predictions` still overwrites (ON CONFLICT DO UPDATE in frozen `ml/predict.py`). The trigger-copy plan (C section 2) is not on main. |
| signal identity | C section 3 `(strategy_id, security_id, session_date, horizon_days, rule_version)`; D 5.2 `(strategy_id, security_id, session_date, rule_version)`; main `signals.signal_key` (migration `signalkey01`, `services/execution.py make_signal_key`) = `strategy.id:instrument.id:mode:kind:horizon:session` | **Conflict:** main uses `instrument.id` (not `security_id`), includes mode and signal kind, has no `rule_version`. No `signal_id` as such, only a string key. Qualifying rule undefined (owner D4). |
| prediction horizon | C D9 (5, 10, 15 only); main `horizon_records` (migration `horizon01`) and ledger `horizon_days` smallint | Consistent on 5/10/15. Model horizon lives on `ml_models.prediction_horizon_days`, not on the prediction (C). Brain horizon default 15 mislabels (#385). |
| model version | ledger and `horizon_records`: `model_id` (plain int), `model_name`, `model_version` text | Consistent across ledger and horizon records. Brain rows have no model identity. `predictions.model_id` still CASCADE (C D5 wants RESTRICT; not on main). |
| verdict / decision | `horizon_records.decision` (12 chars) + `reason` + `policy_code`; brain vocabulary in `brain/contracts.py` (frozen) | No branch defines a "verdict" contract; two vocabularies exist (idea TRADE/WATCH/WAIT/AVOID vs signal BUY/SELL types in `make_signal_key`). Not verified how `horizon_records.decision` values map. |
| data quality | Brain `DataQuality@1` in frozen `brain/contracts.py`; ledger `status` (`scored/missing/stale/late/no_score`) | No identity branch defines a data-quality contract. Ledger status is the only per-stock gap signal; brain M01 quality is not linked to `security_id`. |
| scan identity `scan_key` | D 5.2 `kind:session_date:book`; ledger/`horizon_records` carry `scan_key` String(64) | Format only documented in D; writers in main were not checked for the format. |
| research-config version | C section 7 reference, `horizon_records.research_config_version` + sha256 | Defined on `horizon_records` only; ledger has no such column (D mentions it on rows). |

## 5. Recommended single authoritative location (a recommendation, not a decision)

| Contract | Authority |
|---|---|
| `security_id`, resolver, aliases | `services/identity` + `docs/architecture/IDENTITY-READ-API.md` (as built). Retire the `stock_aliases`/`security_resolver` names in C. |
| score history | `score_ledger` through `ledger.history()`; document one key in the read API and make C/D point to it |
| prediction identity | one section in `IDENTITY-READ-API.md`, chosen from the three keys (owner decision 3) |
| signal identity | `signals.signal_key` (already migrated); amend its definition rather than add `signal_id` |
| horizon, model version, decision, research config | `horizon_records` (#387) |
| data quality | brain `DataQuality@1`; expose via ledger `status` only, no new contract until a Feature needs it |
| design rationale and history | merge or archive the two docs branches into `docs/architecture/` after owner picks answers below |

## 6. Decisions the owner must make

1. Which of the unmerged branches to keep: the three `feat/` twins duplicate merged work. Nothing was deleted; this audit
   recommends nothing destructive.
2. ISIN source: C (own Groww holdings), A (manual NSE file) or B (NSE licence). Already open in the #389 comment.
3. The prediction key: C's, D's or the issue body's. Needs one. Also whether to add `prediction_id` at all given
   `predictions` is frozen and overwrites.
4. Signal key: keep main's `instrument.id` plus mode and kind, or move to `security_id` with `rule_version`. Define the
   qualifying rule (C's D4).
5. Add nullable `security_id` to `instruments` and `user_watchlist_items` (needs a migration; one at a time).
6. `predictions.model_id` CASCADE to RESTRICT (D5).
7. Brain horizon labelling (#385): store `None` or fix the 15 default (touches frozen brain code).
8. Verdict vocabulary: one list for horizon `decision` and signal types.
9. Data quality: is it needed per stock per session in the ledger, or only in brain?
10. Production migration of `identity01` and later (needs a deploy approval).
11. Whether the defects tests (`test/389-identity-defects`) should be merged, rebased or dropped once main has fixes.
12. Deliver `docs/389-*` design docs to `main` or leave as history.

## 7. Frozen and trial-sensitive items

Checked with `backend/tests/trial_freeze.json` (98 files listed under `files`; the file's own rule: a change fails
`tests/test_trial_freeze.py` until the owner approves via `scripts/approve_trial_change.py`). Paths mentioned in the four
identity docs and in the three `feat/` diffs:

| Path | In trial_freeze.json? | Why it matters |
|---|---|---|
| `ml/predict.py` | **YES** | The overwrite (`ON CONFLICT DO UPDATE`, #355). C and D plan to avoid editing it (trigger instead). |
| `brain/service.py` | **YES** | Stores brain decisions; per-decision model identity would need a freeze change (D question 8). |
| `brain/reader.py` | **YES** | Brain's `FALLBACK_MODEL_NAME`; all brain reads. |
| `brain/universe.py` | **YES** | Watchlist universe. |
| `brain/contracts.py` | **YES** | Holds `DataQuality@1`; edited under 2026-10-20 approval. |
| `ml/features.py`, `ml/market_context.py`, `ml/real_question.py`, `ml/sector_map.py` | **YES** | Model inputs (model 2 traceability). |
| `services/engine.py`, `services/risk.py`, `strategies/ml_swing.py`, `strategies/brain.py` | **YES** | Pick, size and exit logic. |
| `brain/modules/m09_learn/learn.py` | **YES** (a prior commit `49615078` records a freeze approval) | Not an identity path. |
| `services/ingestion.py`, `services/score_history.py`, `services/held_read.py`, `services/execution.py`, `db/models/*`, `services/identity/*`, `simulation/*`, `brain/horizons/*` | no | Not frozen, but `score_history.py` and `execution.py` write signals/scores that the frozen trial reads: behaviour-sensitive. |

Other trial-sensitive items: the 5-day paper trial (#279, signed rev 4) and sealed trial evidence; `signal_key` changes
alter how many signals a retry creates, which changes trial counts. `make_signal_key` is in `services/execution.py`,
which is not listed as frozen: verify behaviour impact before any change.

## 8. What could not be verified

- Line-by-line equality of the `feat/` twins with the merged `feature/` branches.
- Whether `test/389-identity-defects` still fails on main (tests not run; no database).
- Section 4 of the contracts doc (score history key) was not read in full; the table row is from sections 1-3 and the read API.
- #282 comments and body for identity contract terms; #386/#387/#390 bodies read only by keyword.
- That any `scan_key` writer in main follows D's format.
- Mapping of `horizon_records.decision` values to a verdict vocabulary.
- Production state, deploy status of migrations (no prod access by design).
- The `trial_freeze.json` path matching for the docs was by file basename then confirmed by exact name; grep misses paths
  written in prose without `.py`.
