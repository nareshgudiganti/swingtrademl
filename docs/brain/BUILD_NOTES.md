# TradeMind Brain — Build Notes

Running notes kept while building the brain module by module. The design is in
the build book (`docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html`);
each module's step-by-step plan is in `docs/superpowers/plans/`. This file is
the short "what we learned" companion: read it before starting a module.

## Owner decisions in force

- Vocabulary **Option A** (confirmed 2026-10-01): ideas TRADE / WATCH / WAIT / AVOID;
  holdings HOLD / MONITOR / REDUCE / EXIT; market NORMAL / DEFENSIVE / NO NEW TRADES.
- Locked trade rule: +8% target, −4% stop, half booked at +5%, up to 15 trading days.
- Rules must be addable and removable without touching the rest (pluggable rule lists).
- M06 = ONE calibrated combining model (owner, 2026-10-01). Starts in trial (SHADOW); switch
  on only if unseen-month evidence says its chances pay after costs.

## Status

| Module | Branch | Notes |
|---|---|---|
| M00 core | brain/m00-core | runner, contracts, fallbacks, constitution, storage, API, CLI |
| M07 risk gate | brain/m07-risk | batch allocator over v1 `check_entry` |
| M01 data quality | brain/m01-quality | freshness and sanity score; market-wide stale → NO NEW TRADES |
| M17 console | brain/m17-console | `/brain` page, overrule toward caution, health |
| M02 perception | brain/m02-perception | model's 53 features per stock per night, `feature_snapshots` |
| M03 + M10 | brain/m03-m10-market | state facts + market mode on v1's regime table |
| M08 decision engine | brain/m08-decide | draft → named rules (only lower) → opportunity notes; rules in `m08_decide/rules.py`, numbers in `policy.py` |
| M16 alerts and cards | brain/m16-alerts | detectors (pluggable) → one Telegram message per run, once a day; console preview/send; sidebar badge; Copy plan |
| M11 sector brain | brain/m11-sector | ranks 15 sector indices vs NIFTY (20 and 60 days), rotation quadrant, `sector` modifier opinion (tilt ±0.05/±0.1) + card line; table stored in `brain_runs.context` (migration 5b7e2d9c3a11) and shown on the console |
| M09 learning loop | brain/m09-learn | scores every live-nightly IDEA decision (+8%/−4%/15d from the decision day's close, no look-ahead) into `brain_decisions` outcome columns; expected vs actual by model score (model-scored rows only — `score_source`), by word, by week; stop-out patterns; feature drift (≥ 15 recent days, market-wide features once per day) stored weekly in `brain_learning_runs`; buy-level proposals in `brain_proposals` — NOTHING changes until Accept (reader then uses the accepted buy level; "Go back to the default" reverts). Weekly job Sat 10:00 IST, `swingtrade brain learn`, `/brain/learning`, `/brain/proposals`, console "Learning from results". Built with subagent-driven development (plan 2026-10-03-brain-m09-learning.md) |
| M15 trade tracker | brain/m15-tracker | STATE plug-in (runs intraday too): each holding with an entry day vs the 25–75% band of similar trades keyed on its ENTRY-day situation (M05 `similar_cases`/`typical_path`; all past trades when no match, said on the card); on track / ahead / drift / breakdown / stop hit / past horizon / no data; M08 `off_track` rule → MONITOR with what changed; +5% evidence on REDUCE; `brain_track` (migration 6e1b4d8a2c73, stop never stored lower), `GET /brain/track/{symbol}`, `HoldingTracker` chart |
| M14 portfolio | brain/m14-portfolio | 60-day return correlations (≥ 40 shared days), pairs > 0.7 and concentration into `PortfolioState`; `portfolio` modifier per idea (−0.1 "moves closely with X, which you already hold", +0.05 "adds variety"); allocator judges an idea that pairs with a stronger one of the same run last (`RiskVerdict.note`, shown by M08); `POST /brain/whatif`; console panel + what-if form |
| M05 memory | brain/m05-memory | `brain_experience` (migration 3c9a7e1f5b28, 51k stock-days, rebuilt by `swingtrade brain memory-build` and after live nightly runs); key = market label · stock trend · last 20 days · volatility; recall widens below 30 (vol, then market, then trend) and records it; reports raw history AND honest figures (base + 0.25 × difference). SHADOW |
| M04 situations | brain/m04-situations | market label (crash › bear phase › correction › recovery › up-trend › sideways) + unknown check (nearest neighbour vs 99th pct) + a trend/extended label per stock; `brain/market_mode.effective_mode` turns a defensive suggestion into DEFENSIVE for M07, M08, the decide fallback and the constitution (C3); `brain_episodes` (migration 8d3f6a2b9e47) re-derived after live nightly runs and by `swingtrade brain episodes-backfill`; console shows the situation and Market history |
| M12 stock brain | brain/m12-stock | setups (pullback, breakout, base, breakdown) → situations shown in the why; delivery ≥ 1.2× usual on 3 of 5 days; institutional deals (whitelist, same-day round trips ignored); one-line profile on cards; `setup` modifier weighted by the WEIGHTS table (evidence). SHADOW |
| M13 news and events | brain/m13-news | results within 5 trading days → `results soon` (AVOID new ideas, line on holdings); split/bonus/rights within 2 trading days → `event blackout`; ex-date ± 2 days → `price reset` (M08 ignores a `breakdown` then); ASM/GSM ≤ 4 days old → `StockState.restrictions` (AVOID); `event` modifier lines. Replays read only rows stored by their date |
| M06 reasoning | brain/m06-meta | `swingtrade brain meta-train` → `brain_meta_vN` (combiner + honesty map); live module writes a `combined`, `calibrated` opinion; buy level = break-even after costs + 5 points. SHADOW |

## How to add a module (checklist)

1. Plan in `docs/superpowers/plans/`, tests first.
2. Pure logic in its own file; the module class only gathers facts and returns a `Contribution`.
3. Register it in `brain/modules/__init__.py`; add its id to `tests/test_brain_api.py`.
4. Step modules leave fields they do not own empty (merge only fills gaps).
5. Full suite with a clean environment; lint only brain paths; local check on the check DB.
6. Update this file.

## How to add or remove a decision rule (M08)

- Add: write `check(decision, facts, policy) -> (word, reason) | None` in
  `brain/modules/m08_decide/rules.py` and append a `Rule(id, plain name, "idea"|"holding", check)`
  to `IDEA_RULES` or `HOLDING_RULES`. Add a test in `tests/test_brain_m08_engine.py`.
- Remove without deleting: put its id in `DecidePolicy.disabled`.
- A rule can only make a decision more careful (the engine applies it with `downgrade`).
- Change a threshold: edit `DecidePolicy` in `policy.py`, nowhere else.

## How to add a modifier (sector tilt, setups, events)

A *modifier* opinion is context, never a view: `brain/opinions.py` skips it when choosing the
opinion that speaks for a stock, so a stock no model scored can never become TRADE because of
a modifier. Its stance nudges the order of liked ideas (`rank_strength`, weight `TILT_WEIGHT`
= 0.25) and its reasons become the last lines of the card (`modifier_notes`). To add one:
write `Opinion(source="<name>", stance=small, reasons=("Plain line.",))` from the module and
add `"<name>"` to `MODIFIER_SOURCES`. Removing it from that set turns it back into a view —
do not do that by accident.

## How to add or remove an alert (M16)

- Add: write `find(current_run, previous_run) -> list[AlertItem]` in `brain/alerts/detectors.py` and
  append a `Detector(id, plain name, find)` to `DETECTORS`. Give items a stable `key` (used for
  once-a-day de-duplication) and a `priority` (lower shows first).
- Remove: pass its id in `disabled` to `detect`.
- Alerts are sent only after live nightly/intraday runs, through v1's notifier as `signal`
  events, and only when `BRAIN_ALERTS_ENABLED=true`.

## Invariants (do not break)

- Modules never write to the database or place orders; the service stores runs.
- Decisions only become more careful after the draft (`contracts.downgrade`).
- The constitution runs last and cannot be switched off; M07 cannot be switched off.
- Replays never use "now" data (model score, holdings, account) and never approve trades.
- Every reason is a plain-English sentence; no promise words.

## Lessons learned

- **Daily bars are stamped at IST midnight** (18:30 UTC the previous day). Read dates in IST.
  M00 had this wrong; M01 caught it.
- **Merge is first-writer-wins**: a step module that sets a field blocks plug-ins from refining
  it. M03 leaves the market mode empty so M10 can decide it; `MarketState.mode` is optional.
- **The brain places no orders**, so per-stock risk checks cannot see each other. M07 keeps a
  running tally of cash, slots, sector and market room across the batch.
- **The market-context loaders cache whole histories per process**; clear once per run.
- **A model score is not a probability** of +8% before −4% (production models answer
  "+2% in 5 days"). Expected value appears only once similar-case hit rates exist (M05).
- **"Latest run" must skip replays**, or a past date shows up as today's ideas.
- **Reasons must name the real cause**: "all slots are already in use", not "a stronger idea
  took the slot", when nothing was approved.

- **Opinion choice is shared** (`brain/opinions.py`): the risk gate and the decision engine
  must read the same opinion the same way (combined view, then model, then strongest).
- **On real data (Sep 2026) the holding rules are informative**: 11 of 13 paper holdings were
  MONITOR (falling in a careful market, or trailing NIFTY by 15–20%).

- **Owner asked for no banner on every page** (it pushed the Holdings table down), so the brain's
  market mode is a small badge in the side menu's status strip.
- **Record an alert only after Telegram really sent it**; otherwise turning Telegram on later
  would silently skip what was never delivered.

- **Checkpoint review 2026-10-01 (10 findings, all fixed)**: savepoint around run/store so a DB
  failure is recorded with its cause; alert baseline = previous *alert-checked* run of the same
  book; health uses live nightly runs only; never clear v1's market cache unless it is behind the
  database (v1's 15:40 ingest refreshes it, and the 15:45 scan may be reading it); naive times are
  India time; per-module `intraday_budget_s`; EV costs on a real position size; `downgrade` keeps a
  holding's shares; fallbacks fill gaps only; one shared opinion rule set.

- **M06 (2026-10-01/02): ranking is not the same as a chance you can trade on.** On 9,551
  unseen stock-days (Nov 2025–Aug 2026) the combiner ranks better than the old model (AUC 0.636
  vs 0.614; top 10% hit 40.9% vs 17.4% base), but the first live run gave every stock 57–82%
  while its own record said such scores came true about a third of the time — the logistic step
  extrapolated into a market (Sep 2026, falling) it had barely seen. Fix: the **honesty map**
  (isotonic on walk-forward predictions, capped where fewer than 20 *different days* back a
  level — 47 stocks on one day are one market bet). Result: ceiling 24.5%, so every stock is
  WAIT against the 41% needed. M06 stays SHADOW. Do not "fix" this by lowering the margin:
  the evidence says no score level has paid +8%/−4% after costs over enough days.
- **M02 vs batch features differ on `obv_slope`** (snapshot −0.96 vs batch −0.02 for WIPRO,
  09-07): OBV is cumulative, so its slope depends on how many bars were loaded (M02 loads 400).
  Small effect on scores today (0.75 vs 0.74), but it is train/serve skew — fix in M02 later.

- **M11 (2026-10-02)**: a sector tilt written as a normal opinion would have let a stock with no
  model score become TRADE (positive stance = "liked"). Hence modifier opinions. Real check,
  data to 07 Sep 2026: Metals, Capital markets, Pharma lead; IT ranks 15 of 15 (weakening).
- **New brain_runs columns**: the test DB keeps its tables, so after adding a column run
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on `swing_trade_ml_test` (and stamp/upgrade the check DB).

- **M13 (2026-10-02)**: StockState merge was first-writer-wins for the whole record, so a
  plug-in could never add restrictions to M03's record. Now `_fill_gaps` per symbol (the build
  book's "M03's values are the floor" rule). Real check: TCS (results 08 Oct) is AVOID with the
  spec's sentence; no watch-listed stock is on ASM/GSM. No filings table exists yet, so "fresh
  filings as context" waits for a feed (connector contract).
- **Card lines must not repeat a reason**: M08 drops a modifier line whose text a reason
  already contains.

- **M12 (2026-10-02): test every rule against history before trusting it.** 5 years of
  watch-list stocks, +8% before −4% in 15 trading days, any day 17.6%: pullback 16.7%,
  breakout 16.4%, tight base 13.0%, **breakdown 20.4%**; the build book's delivery rule
  ("above average 3 of 5 days") fired on 53% of days with no edge (18.8%), 1.2× fired on 6% and
  reached 22.3%. So setups carry no weight and are not card lines, breakdown is no longer an
  AVOID (removed from M08's `AVOID_SITUATIONS`), delivery uses 1.2×. Re-run
  `docs/brain/evidence/m12_*.py` (check DB env vars) before changing WEIGHTS.
- **Bulk/block deals are mostly HFT firms** (QE Securities, HRTI, Jump…) buying and selling the
  same stock the same day; only whitelisted institutions count, round trips cancel. Only one
  day of deals is stored, so deal weights are untested.

- **M04 (2026-10-02): the spec's caution goes AGAINST this data.** Watch-list stocks, +8% before
  −4% in 15 trading days, by market label (Aug 2021–Sep 2026): up-trend 16.9% (−0.05 R),
  correction 16.9%, bear phase 29.2% (+0.12 R), recovery 10.1% (−0.29 R), unknown 29.6%
  (+0.37 R), crash 55.1% (+1.0 R). Few independent events (9 crash days, 16 unknown days) and a
  survivor-biased list (today's 49 stocks) — both inflate buy-the-dip results — so the spec's
  default (crash, bear phase, unknown → suggest DEFENSIVE) is KEPT for safety, as one set
  (`DEFENSIVE_LABELS`, plus the unknown flag in module.py). Owner decision pending. Re-check with
  `docs/brain/evidence/m04_labels_vs_outcomes.py` once history is longer / survivorship-free.
- **Backfill sanity check**: crashes found on 04 Jun 2024 (election result), 05 Aug 2024 (global
  sell-off), 07 Apr 2025 (tariffs) — real events. NIFTY history starts Aug 2021, so the spec's
  23 Mar 2020 replay runs only on a synthetic fixture.
- **Never run `ruff format` on the whole package** — it reformatted 51 v1 files (again, M04);
  reverted. Format only `src/swing_trade_ml/brain`, brain tests, and files you created.

- **M05 (2026-10-02): similar-case memory does not predict on unseen months.** 46 months,
  46,109 stock-days, walk-forward (only cases known before each month): AUC 0.520, Brier 0.1491
  vs 0.1457 for the plain average; matches scored 40%+ came true 22.5%. Adding distance from the
  1-year high to the key: AUC 0.526 — no real gain. So recall shows raw history with an honest
  figure beside it (RELIABILITY 0.25 in recall.py, from that slope), stays SHADOW, and is kept
  for M15's day-by-day band. Real check: HDFCBANK, TCS and WIPRO share one key → identical
  recall (1,199 cases, 16%, honest 18%) — the keys are too coarse to tell stocks apart.
- **M08's old expected-result formula counted every miss as a full −4% loss** — but ~41% of
  cases are day-15 timeouts near flat. With M05's average exit it now uses
  `expected_r_from_mean`; the old formula remains only for a recall without an average.
- **Three modules, one lesson (M06, M12, M04, M05):** on these 49 large caps, under +8%/−4% in
  15 days, nothing simple has a real edge yet. The next real gain needs new information
  (fundamentals, news, flows) or a different universe/rule — not more rules on prices.

- **M14 (2026-10-02)**: on 49 watch-list stocks only 6 of ~1,176 pairs exceed 0.7 (INFY–TCS,
  JSWSTEEL–TATASTEEL, IT with TECHM, ADANIENT–ADANIPORTS); median 0.15 — the spec's 0.7 picks
  real twins. Paper book today: 13 holdings, largest 1%, top sector FMCG 4%, no twins.

- **M15 (2026-10-02)**: real paper book: 9 on track, 1 drift, 3 "no data" — those were bought on
  the last price day of the stale check DB; the card says "No price since it was bought…" rather
  than "Bought today". A trade above the band reads "ahead of the usual range".
- **Shell traps**: one long bash command with several heredocs can fail to parse and run
  NOTHING — write files with the Write tool, keep edit scripts in the scratchpad. Prettier has no
  repo config here: never run it on existing files (defaults reformat to double quotes).

- **M09 (2026-10-03)**: on the check DB nothing can be scored yet — stored runs are 30 Sep–2 Oct
  but prices end 07 Sep. The first drift check compared ONE day × 60 stocks (index 8.4,
  nonsense); fixed with a 15-day minimum and once-per-day market-wide features.
  `BrainDecision.confidence` holds different kinds of number — `score_source` says which.
- **Subagents**: implementers must never use `git stash` (shared stack); one full-suite run had
  1 unidentified failure that did not reproduce on two re-runs (960 passed) — watch for a flaky test.

## Testing traps (Windows)

- Printing ₹ to the Windows console crashes (cp1252): set `PYTHONIOENCODING=utf-8` for scripts.

- Run pytest with `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE`.
- After adding columns to an existing brain table, drop it in `swing_trade_ml_test` (create_all
  does not alter tables).
- Format only brain paths, never the whole package.
- Only roll back a session in code under test when `not db.is_active`.

## M09 follow-ups (deferred minors from the subagent reviews, 2026-10-03)

- Task 1: minor (deferred): scoring._bars loads full candle history per symbol; add a ts <= upto filter in SQL.
- Task 1: minor (deferred): score_pending flushes, caller must commit — T5 hook (_sync_episodes) commits; CLI/job must too.
- Task 2: minor (deferred): add "calls one_per_day itself" tests for by_word/by_week/failure_patterns.
- Task 2: minor (deferred): failure_patterns share-of-all includes rows with no market/sector label.
- Task 3: minor (deferred): assert levels["rsi_14"] == "moderate" via a computed PSI; test a present-but-undersized feature being skipped; comment why _reference_frame omits build_dataset's 260-bar skip.
- Task 4: minor (deferred): rename test_no_proposal_when_no_candidate_has_enough_cases (None comes from min_gain_r); comment tie-break (lowest threshold wins).
- Task 5: minor (deferred): after-run hook failure event is still named "brain.memory.sync_failed" — rename to a job-agnostic name.
- Task 5: minor (deferred): learning_report filters `since` in Python after a full fetch — push into SQL when the table grows.
- Task 5: minor (deferred): new_proposals shape {id, kind, title, evidence} chosen by implementer.
- Task 6: minor (deferred): one shared pending flag disables every proposal's buttons during any decision.
- Final review: deferred (minor, not in the fix wave): #6 module_mode accept for unknown module → 500 (no generator yet); #7 no row lock on accept (single owner); #8 holiday nightly runs double-count a setup; #9 upto during market hours could freeze a partial close; #14 unscoreable ideas re-queried; #15 no note length limit; T2/T4/T5/T6 minors as triaged by the final reviewer.

## TradeMind live-data follow-ups (deferred minors, 2026-10-04)

- Task 1: minor (deferred): chip keeps CSS class name tm-demo-chip (rename when trademind.css is touched).
- Task 2: minor (deferred): Home's top-ideas score has no visible label; MARKET_PLAIN/MARKET_TONE duplicated in Home.tsx and Market.tsx; Opportunities ring shows 0-fill when confidence is null.
- Task 4: minor (deferred): spot-check PositionBand reason wording in the browser pass.
- Task 3: minor (deferred): WORD_TONE falls back to 'pos' for an unknown word (should be neutral); date parsing comment in live-stock.ts; finalWord duplicated; index keys.
- Task 5: minor (deferred): STEP_LABEL/MODE_LABEL copied from Brain.tsx into System.tsx.
- BrainGate component to replace the off/loading/error/no-run block copied into 9 pages.
- Local check DB has the wrong 28 Sep opening equity (₹1,83,647 vs ₹9,79,792) → Portfolio shows +435.6% / Max drawdown −81.6% (v1 data, not a UI bug).
