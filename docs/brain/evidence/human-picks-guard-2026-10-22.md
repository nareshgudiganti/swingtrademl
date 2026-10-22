# Human picks guard (evidence plan amendment 1, A3) — 2026-10-22

**Rule (A3):** a stock a person chose is never counted in any brain result, baseline or gate.

**Test:** `backend/tests/test_brain_results_exclude_human_picks.py`. It plants a stock from each human
source on a day before the trial, next to one brain idea and one version 1 idea, then reads every brain
result route and report.

## What the test found

One path broke the rule, and it is now fixed.

| Human source | Where it leaked | Fix |
|---|---|---|
| Manual paper testing (`tester_paper` strategy): the tester's BUY signals | `/brain/compare` (brain vs version 1). They were counted in the **version 1 baseline** and listed as a strategy | `services/brain_golive/compare.load` leaves the hand books out by type and by name |
| My Holdings / Real Trading (`real_trading` strategy, strategy type `ml_swing`, mode live): the daily scan's BUY signals for it | the same comparison, as part of the version 1 baseline | the same filter |
| Owner's horizon-experiment picks (`experiment_*` tables) | none. No brain path reads these tables | — |

There was no leak into the brain's own figures, the go-live gate or the "N of 30" counter. All of these
count only the brain strategy's rows (strategy type `brain`) or brain ideas (`kind = "idea"`). A person's
stock only reaches a brain run as a `holding` decision, and no result path reads holdings.

**Effect:** the version 1 figures on the brain-vs-version-1 card can change if testers or My Holdings had
signals there. The brain's own numbers, the gate and trading are unchanged.

**Hardening:** `brain/replay_score.v1_buys` (the trial journal's "Version 1 buys" set) already left out My
Holdings, because it reads paper signals only. It now also leaves out the hand books by name, so the rule
still holds if that book's mode ever changes.

**Not a brain result, so not changed:** fill quality (ps4) still checks every filled order, with paper and
real orders shown apart. It measures how realistic fill prices were, not how the brain did.
