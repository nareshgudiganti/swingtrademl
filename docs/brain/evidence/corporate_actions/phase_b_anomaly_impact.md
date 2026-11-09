# Phase B: impact of the known price-data steps (counts and structural bounds, not results)

Status: analysis note, UNSIGNED, changes no price, rule, tag, list or result. Prepared 2026-11-07, before Phase B may run (2026-11-09).
What was done: bar DATES were read from the local database (SELECT only, read-only transaction, local only) and the folds, horizon and
lookbacks were applied. **No price, return, model score, candidate output or stock ranking was read or computed.** No Phase B number exists
or was looked at. Scripts: `phase_b_impact_scripts/` (set `PHASE_B_IMPACT_LOCAL_DSN` to the local database URL; they print counts only).

Phase B facts used (read from `phase_b.py`, `walk_forward.py`, `ml/train.py`, `ml/features.py`): development window 2025-02-01 to 2026-08-15,
20 test folds of 28 days, model cutoff = day before each fold; each fold trains on history up to the cutoff (B1 and B3: the 49; B2: the 49 + 128);
label and trade path = 15 bars from the next open (+8% / -4% barriers); features look back up to 252 bars (52-week, 200-day average).
Scored unit: 379 trading days, 18,571 stock-days for the 49 (49.0 per day); reject set 129 stocks, 48,667 stock-days.

## 1. What each step touches (counts)

"Label" = decision days whose 15-bar path crosses the step (14 per event). "Feature" = decision days after the step whose lookback still
contains pre-step bars (up to 251). "Folds" are the test folds 1 to 20.

| Event (set) | Label days inside dev window | Feature days inside dev window (50 / 200 / 252 bar lookback) | Test folds touched | In training (folds) |
|---|---|---|---|---|
| ITC 2025-01-06 (49) | 0 | 29 / 179 / 231 (1.24% of scored stock-days at 252) | features only: folds 1 to 13 | all 20 |
| RELIANCE 2023-07-20 (49) | 0 | 0 / 0 / 0 | none | all 20 |
| HINDUNILVR 2025-12-05 (49) | **14 (0.075%)** | 49 / 171 / 171 (0.92%) | labels fold 11; features folds 11 to 20 | folds 12 to 20 |
| BAJAJELEC 2023-09-14 (B2 extra) | 0 (not scored) | not scored | none (never scored) | all 20 (B2 only) |

Training-row share touched (rows with a label or 252-bar feature window containing a step): B1/B3 training 0.92% (fold 1) to 1.39% (fold 20)
of about 29k to 47k rows; B2 training 0.66% to 0.88% of about 103k to 166k rows. BAJAJELEC alone: 14 label rows (0.008% to 0.014%) and 251
feature rows (0.15% to 0.24%) of B2 training in every fold.

## 2. NOT in the current disclosure (section 13a of the Phase B protocol), found by this check

The audit lists 14 mechanical steps; only four are named in the disclosure. The other ten sit outside the 49 but inside Phase B's data:

| Event | Where | Move | Effect |
|---|---|---|---|
| SANOFI 2024-06-13 | B2 extra training | -28.0% | training only, all 20 folds |
| ABFRL 2025-05-22 | B2 extra training | -55.9% | training only, folds 5 to 20 (step inside fold 4's test window, but ABFRL is not scored) |
| VEDL 2026-04-30 | B2 extra training | -32.9% | training only, folds 18 to 20 |
| SIEMENS 2025-04-07, TMPV 2025-10-14, ALLCARGO 2025-11-12, TRIVENI 2026-07-22 | **reject set, inside the dev window** | -25.1%, -13.1%, -60.1%, -41.6% | 56 reject-set stock-days (0.115%) have a path crossing the step; also their features |
| NMDC 2022, SCI 2023, ALLCARGO 2023 | reject set, before the window | +85.7%, +30%, -21% | never scored (no dev-window path); the reject set is never trained on |

A -56% step inside a 15-bar path reads as a false -4% stop; it affects 14 label rows per event in training, which is negligible by count.

## 3. Structural worst-case bounds (no scores used)

Daily edge = (mean net of the day's picks) - (mean net of every stock). A wrong net return `E` on one stock on one day moves the every-stock
mean by at most `E/n` (n = 49) and the picks' mean by at most `E/m` (m = picks that day) only if that stock is picked. So the mean daily edge
moves by at most `A * E * (1/m + 1/49) / N` (A affected days, N days with ideas). HINDUNILVR: A = 14.

| Case | every-stock avg per trade | top-5 (B2, B3), N = 379 / 100 / 30 | B1 with one idea that day, N = 379 / 100 / 30 |
|---|---|---|---|
| E = 1.91 pp (HUL cost-apportionment share, price level only) | <= 0.0014 pp | 0.016 / 0.059 / 0.197 pp | 0.072 / 0.27 / 0.91 pp |
| E = 12 pp (a +8% outcome flipped to a -4% stop, absolute worst) | <= 0.009 pp | 0.098 / 0.37 / 1.23 pp | 0.45 / 1.7 / 5.7 pp |

Reading: the worst case needs the stock picked on all 14 days. The reject-set share is <= 0.0046 pp (false -4% stops) to 0.0138 pp (12 pp flips)
of the reject-set average per trade. Direction: a false loss lowers the every-stock baseline, so candidates look slightly BETTER than they are
(the optimistic direction); magnitude is far below the second-decimal differences Phase B compares. Threshold link: the 30-trading-day gate
counts days with ideas and does not depend on returns, so labels cannot change it; `edge_low` > 0 can only flip if the true bound is within the
shift above (published wf/fd daily-edge lower bounds were about -0.155 pp, so a worst-case flip needs concentration on very few ideas days).

Feature channel (HUL 171 and ITC 231 stock-days): ratio features move by at most the mechanical share (<= 1.91%); per-stock only, so at most
one name per day changes rank; cannot be bounded tightly without model scores, and it was not tested. B3 breadth: one of 49 stocks changing
its 50-day-average status moves breadth by at most 2.04 pp for <= 49 days; whether such a day is near the 30% line was deliberately NOT looked at
(it would expose B3's trading days).

## 4. Reconciliation with the earlier audit (`verify49_report.md` section 4)

The audit measured (5-day and 30-day-hold scorers, not Phase B's 15-day, no model): excluding every affected row moved the every-stock average by
at most 0.04 pp anywhere and by +0.005 pp (path crossing) to +0.014 pp (plus features) in the HUL window; best-5 bound 0.03 pp. Those figures
are consistent with the bounds above (0.0014 to 0.009 pp for the label channel). The audit's "8 trade-path rows" for HUL used its 30-day-hold
variant; Phase B's 15-bar path gives 14. The audit did not list the ten steps in section 2, because they are outside the 49.

## 5. Conclusion

Realistic effect: **negligible** (label channel 0.075% of scored stock-days, bound <= 0.016 pp on a top-5 edge at 379 days; reject-set effect
<= 0.014 pp; both in the optimistic direction). **Cannot tell** only for the feature channel and for an extreme concentration case (HUL
picked on all 14 days with very few ideas days), where the bound reaches 0.2 pp but still requires a flip the data do not suggest.

## 6. Options for the owner (before 2026-11-09)

1. **Accept and widen the disclosure (recommended).** Add the ten steps in section 2 and the counts in section 1 to protocol section 13a; no rule,
   list, price or tag changes. Consequence: none for the signed numbers; the record states exactly what was known.
2. **HINDUNILVR fresh fetch first.** If the vendor has since adjusted HUL, the stored prices differ from what Phase B would read; replacing
   stored prices changes the data the signed settings run on, so it needs an amendment and a statement before 9 Nov. Consequence: a delay and
   a new signed step; the other steps (ITC, RELIANCE, reject set, B2 extras) stay.
3. **Exclude affected stocks or rows by a new signed protocol version.** Changes stock lists or the split file (hash `bc8878f2...`) and so
   `phase-b-settings`; needs a new tag and signatures before 9 Nov. Consequence: loses comparability with the signed plan; not recommended given
   the size above.
