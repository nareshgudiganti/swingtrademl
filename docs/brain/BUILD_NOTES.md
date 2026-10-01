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
- Open: combine opinions with one calibrated meta-model (decide before M06).

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

## Testing traps (Windows)

- Run pytest with `env -u API_KEY -u DATABASE_URL -u JWT_SECRET_KEY -u TRADING_MODE`.
- After adding columns to an existing brain table, drop it in `swing_trade_ml_test` (create_all
  does not alter tables).
- Format only brain paths, never the whole package.
- Only roll back a session in code under test when `not db.is_active`.
