# APOLLOHOSP future-data mutation check, v1 (completes the two INCONCLUSIVE cases)

Date: 2026-11-08. Status: evidence, UNSIGNED. Local database, SELECT only (read-only transaction); no model was fitted, no holdout evaluated.
Code: `backend/tests/test_apollohosp_pit_mutation.py` (14 tests: 10 real-data, 4 synthetic twin; real-data tests skip when the local Postgres is unreachable). Table regenerated with `python tests/test_apollohosp_pit_mutation.py --write-md <path>`.

## What was checked, in plain words

The earlier verification scrambled all later data and showed the five restored APOLLOHOSP rows did not move, but for D = 2022-11-01 and 2022-11-02 it could not show that the scramble really reached a later row (it compared against "60 calendar days later", which was not a trading day for those two). Here the later rows are the **next 1, 2, 5, 10, 20 and 60 trading sessions after D, read from APOLLOHOSP's own candle calendar**.

Decision days D: 2022-10-27, 2022-11-01, 2022-11-02, 2022-11-03, 2022-11-04 (all five restored rows). Horizons: 5 (SX5, endpoint label +2%) and 10 (SX10, barrier +6% / -3.5%). No exclusions were applied, so the neighbouring rows 2022-10-28 and 2022-10-31 are also in the compared set.

Scramble: every stock price (open/high/low/close multiplied by one random factor 0.5-2 per bar, so each bar stays consistent), volume (x0.2-5), NIFTY 50, all 15 sector indices, INDIA VIX and both breadth columns (random 0-1), for every bar dated (IST) after the cut. Seeded, so repeatable.

- **A**: cut = D. Rebuild the 56 inputs with the batch builder (`assemble_training_matrix`). The inputs of D and of every earlier row must be bit-identical (byte comparison of the float64 values). **Power**: the row n sessions after D must change.
- **B**: cut = the n-th session after D. Everything dated after the cut is scrambled. All rows up to the cut (D and every row between D and the cut included) must be bit-identical, and the first row after the cut must change (power).
- **C (mirror)**: the as-of builder (`assemble_asof_row`) at D equals the batch row at D, on (i) the full data, (ii) all data after D removed, (iii) all data after D scrambled.

## Result

**All checks pass for all five rows, both horizons: 0 failures, 0 cases without power.**

- A: row D and all earlier rows bit-identical in 10 of 10 (day x horizon) cases.
- A power: in every case the rows 1, 2, 5, 10, 20, 60 sessions after D changed (52-55 of the 56 inputs differ each time; the remaining few inputs were equal in those rows, which a discrete input can be). So the two formerly inconclusive cases (2022-11-01 and 2022-11-02) now show real power at every distance.
- B: every cut from 1 to 60 sessions identical up to and including the cut; the first row after the cut changed in 52-53 of 56 inputs.
- C: as-of equals batch in 30 of 30 checks.
- The test also contains a sanity test that scrambling data BEFORE the decision day does move the row (a check that "identical" means something), and a synthetic copy of the whole battery that runs without a database.

Which later rows changed: all of them, for every D, at every distance listed (the "A power" and "B next row" lines below give the date and the number of changed inputs).

Limits: this proves the point-in-time property of the 56 inputs of these five rows in the local data; it does not test labels (they are meant to use the future) and it is not a test of the fitted model.

## Full table (per decision day, horizon, number of sessions)

### Horizon 5 (SX5)

| D | Check | n sessions after D | Date compared | Result |
|---|---|---|---|---|
| 2022-10-27 | A: scramble all data dated after D; row D and all 19 rows up to D identical | - | 2022-10-27 | PASS |
| 2022-10-27 | A power: row n sessions later moves | 1 | 2022-10-28 | PASS (52 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 2 | 2022-10-31 | PASS (53 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 5 | 2022-11-03 | PASS (55 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 10 | 2022-11-11 | PASS (54 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 20 | 2022-11-25 | PASS (52 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 60 | 2023-01-20 | PASS (54 of 56 inputs changed) |
| 2022-10-27 | B: cut at D+n, scramble after it; 20 rows up to the cut identical | 1 | 2022-10-28 | PASS; next row 2022-10-31 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 21 rows up to the cut identical | 2 | 2022-10-31 | PASS; next row 2022-11-01 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 24 rows up to the cut identical | 5 | 2022-11-03 | PASS; next row 2022-11-04 changed in 52 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 29 rows up to the cut identical | 10 | 2022-11-11 | PASS; next row 2022-11-14 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 39 rows up to the cut identical | 20 | 2022-11-25 | PASS; next row 2022-11-28 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 79 rows up to the cut identical | 60 | 2023-01-20 | PASS; next row 2023-01-23 changed in 52 of 56 inputs |
| 2022-10-27 | C mirror: as-of row == batch row, data full | - | 2022-10-27 | PASS |
| 2022-10-27 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-10-27 | PASS |
| 2022-10-27 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-10-27 | PASS |
| 2022-11-01 | A: scramble all data dated after D; row D and all 22 rows up to D identical | - | 2022-11-01 | PASS |
| 2022-11-01 | A power: row n sessions later moves | 1 | 2022-11-02 | PASS (53 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 2 | 2022-11-03 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 5 | 2022-11-09 | PASS (55 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 10 | 2022-11-16 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 20 | 2022-11-30 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 60 | 2023-01-25 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | B: cut at D+n, scramble after it; 23 rows up to the cut identical | 1 | 2022-11-02 | PASS; next row 2022-11-03 changed in 53 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 24 rows up to the cut identical | 2 | 2022-11-03 | PASS; next row 2022-11-04 changed in 52 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 27 rows up to the cut identical | 5 | 2022-11-09 | PASS; next row 2022-11-10 changed in 53 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 32 rows up to the cut identical | 10 | 2022-11-16 | PASS; next row 2022-11-17 changed in 53 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 42 rows up to the cut identical | 20 | 2022-11-30 | PASS; next row 2022-12-01 changed in 52 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 82 rows up to the cut identical | 60 | 2023-01-25 | PASS; next row 2023-01-27 changed in 52 of 56 inputs |
| 2022-11-01 | C mirror: as-of row == batch row, data full | - | 2022-11-01 | PASS |
| 2022-11-01 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-01 | PASS |
| 2022-11-01 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-01 | PASS |
| 2022-11-02 | A: scramble all data dated after D; row D and all 23 rows up to D identical | - | 2022-11-02 | PASS |
| 2022-11-02 | A power: row n sessions later moves | 1 | 2022-11-03 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 2 | 2022-11-04 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 5 | 2022-11-10 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 10 | 2022-11-17 | PASS (54 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 20 | 2022-12-01 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 60 | 2023-01-27 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | B: cut at D+n, scramble after it; 24 rows up to the cut identical | 1 | 2022-11-03 | PASS; next row 2022-11-04 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 25 rows up to the cut identical | 2 | 2022-11-04 | PASS; next row 2022-11-07 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 28 rows up to the cut identical | 5 | 2022-11-10 | PASS; next row 2022-11-11 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 33 rows up to the cut identical | 10 | 2022-11-17 | PASS; next row 2022-11-18 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 43 rows up to the cut identical | 20 | 2022-12-01 | PASS; next row 2022-12-02 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 83 rows up to the cut identical | 60 | 2023-01-27 | PASS; next row 2023-01-30 changed in 53 of 56 inputs |
| 2022-11-02 | C mirror: as-of row == batch row, data full | - | 2022-11-02 | PASS |
| 2022-11-02 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-02 | PASS |
| 2022-11-02 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-02 | PASS |
| 2022-11-03 | A: scramble all data dated after D; row D and all 24 rows up to D identical | - | 2022-11-03 | PASS |
| 2022-11-03 | A power: row n sessions later moves | 1 | 2022-11-04 | PASS (52 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 2 | 2022-11-07 | PASS (54 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 5 | 2022-11-11 | PASS (52 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 10 | 2022-11-18 | PASS (54 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 20 | 2022-12-02 | PASS (53 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 60 | 2023-01-30 | PASS (53 of 56 inputs changed) |
| 2022-11-03 | B: cut at D+n, scramble after it; 25 rows up to the cut identical | 1 | 2022-11-04 | PASS; next row 2022-11-07 changed in 52 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 26 rows up to the cut identical | 2 | 2022-11-07 | PASS; next row 2022-11-09 changed in 53 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 29 rows up to the cut identical | 5 | 2022-11-11 | PASS; next row 2022-11-14 changed in 53 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 34 rows up to the cut identical | 10 | 2022-11-18 | PASS; next row 2022-11-21 changed in 52 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 44 rows up to the cut identical | 20 | 2022-12-02 | PASS; next row 2022-12-05 changed in 53 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 84 rows up to the cut identical | 60 | 2023-01-30 | PASS; next row 2023-01-31 changed in 52 of 56 inputs |
| 2022-11-03 | C mirror: as-of row == batch row, data full | - | 2022-11-03 | PASS |
| 2022-11-03 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-03 | PASS |
| 2022-11-03 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-03 | PASS |
| 2022-11-04 | A: scramble all data dated after D; row D and all 25 rows up to D identical | - | 2022-11-04 | PASS |
| 2022-11-04 | A power: row n sessions later moves | 1 | 2022-11-07 | PASS (52 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 2 | 2022-11-09 | PASS (54 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 5 | 2022-11-14 | PASS (54 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 10 | 2022-11-21 | PASS (54 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 20 | 2022-12-05 | PASS (53 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 60 | 2023-01-31 | PASS (53 of 56 inputs changed) |
| 2022-11-04 | B: cut at D+n, scramble after it; 26 rows up to the cut identical | 1 | 2022-11-07 | PASS; next row 2022-11-09 changed in 53 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 27 rows up to the cut identical | 2 | 2022-11-09 | PASS; next row 2022-11-10 changed in 53 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 30 rows up to the cut identical | 5 | 2022-11-14 | PASS; next row 2022-11-15 changed in 52 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 35 rows up to the cut identical | 10 | 2022-11-21 | PASS; next row 2022-11-22 changed in 52 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 45 rows up to the cut identical | 20 | 2022-12-05 | PASS; next row 2022-12-06 changed in 52 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 85 rows up to the cut identical | 60 | 2023-01-31 | PASS; next row 2023-02-01 changed in 52 of 56 inputs |
| 2022-11-04 | C mirror: as-of row == batch row, data full | - | 2022-11-04 | PASS |
| 2022-11-04 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-04 | PASS |
| 2022-11-04 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-04 | PASS |

### Horizon 10 (SX10)

| D | Check | n sessions after D | Date compared | Result |
|---|---|---|---|---|
| 2022-10-27 | A: scramble all data dated after D; row D and all 19 rows up to D identical | - | 2022-10-27 | PASS |
| 2022-10-27 | A power: row n sessions later moves | 1 | 2022-10-28 | PASS (52 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 2 | 2022-10-31 | PASS (53 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 5 | 2022-11-03 | PASS (55 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 10 | 2022-11-11 | PASS (54 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 20 | 2022-11-25 | PASS (52 of 56 inputs changed) |
| 2022-10-27 | A power: row n sessions later moves | 60 | 2023-01-20 | PASS (54 of 56 inputs changed) |
| 2022-10-27 | B: cut at D+n, scramble after it; 20 rows up to the cut identical | 1 | 2022-10-28 | PASS; next row 2022-10-31 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 21 rows up to the cut identical | 2 | 2022-10-31 | PASS; next row 2022-11-01 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 24 rows up to the cut identical | 5 | 2022-11-03 | PASS; next row 2022-11-04 changed in 52 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 29 rows up to the cut identical | 10 | 2022-11-11 | PASS; next row 2022-11-14 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 39 rows up to the cut identical | 20 | 2022-11-25 | PASS; next row 2022-11-28 changed in 53 of 56 inputs |
| 2022-10-27 | B: cut at D+n, scramble after it; 79 rows up to the cut identical | 60 | 2023-01-20 | PASS; next row 2023-01-23 changed in 52 of 56 inputs |
| 2022-10-27 | C mirror: as-of row == batch row, data full | - | 2022-10-27 | PASS |
| 2022-10-27 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-10-27 | PASS |
| 2022-10-27 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-10-27 | PASS |
| 2022-11-01 | A: scramble all data dated after D; row D and all 22 rows up to D identical | - | 2022-11-01 | PASS |
| 2022-11-01 | A power: row n sessions later moves | 1 | 2022-11-02 | PASS (53 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 2 | 2022-11-03 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 5 | 2022-11-09 | PASS (55 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 10 | 2022-11-16 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 20 | 2022-11-30 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | A power: row n sessions later moves | 60 | 2023-01-25 | PASS (54 of 56 inputs changed) |
| 2022-11-01 | B: cut at D+n, scramble after it; 23 rows up to the cut identical | 1 | 2022-11-02 | PASS; next row 2022-11-03 changed in 53 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 24 rows up to the cut identical | 2 | 2022-11-03 | PASS; next row 2022-11-04 changed in 52 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 27 rows up to the cut identical | 5 | 2022-11-09 | PASS; next row 2022-11-10 changed in 53 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 32 rows up to the cut identical | 10 | 2022-11-16 | PASS; next row 2022-11-17 changed in 53 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 42 rows up to the cut identical | 20 | 2022-11-30 | PASS; next row 2022-12-01 changed in 52 of 56 inputs |
| 2022-11-01 | B: cut at D+n, scramble after it; 82 rows up to the cut identical | 60 | 2023-01-25 | PASS; next row 2023-01-27 changed in 52 of 56 inputs |
| 2022-11-01 | C mirror: as-of row == batch row, data full | - | 2022-11-01 | PASS |
| 2022-11-01 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-01 | PASS |
| 2022-11-01 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-01 | PASS |
| 2022-11-02 | A: scramble all data dated after D; row D and all 23 rows up to D identical | - | 2022-11-02 | PASS |
| 2022-11-02 | A power: row n sessions later moves | 1 | 2022-11-03 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 2 | 2022-11-04 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 5 | 2022-11-10 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 10 | 2022-11-17 | PASS (54 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 20 | 2022-12-01 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | A power: row n sessions later moves | 60 | 2023-01-27 | PASS (53 of 56 inputs changed) |
| 2022-11-02 | B: cut at D+n, scramble after it; 24 rows up to the cut identical | 1 | 2022-11-03 | PASS; next row 2022-11-04 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 25 rows up to the cut identical | 2 | 2022-11-04 | PASS; next row 2022-11-07 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 28 rows up to the cut identical | 5 | 2022-11-10 | PASS; next row 2022-11-11 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 33 rows up to the cut identical | 10 | 2022-11-17 | PASS; next row 2022-11-18 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 43 rows up to the cut identical | 20 | 2022-12-01 | PASS; next row 2022-12-02 changed in 52 of 56 inputs |
| 2022-11-02 | B: cut at D+n, scramble after it; 83 rows up to the cut identical | 60 | 2023-01-27 | PASS; next row 2023-01-30 changed in 53 of 56 inputs |
| 2022-11-02 | C mirror: as-of row == batch row, data full | - | 2022-11-02 | PASS |
| 2022-11-02 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-02 | PASS |
| 2022-11-02 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-02 | PASS |
| 2022-11-03 | A: scramble all data dated after D; row D and all 24 rows up to D identical | - | 2022-11-03 | PASS |
| 2022-11-03 | A power: row n sessions later moves | 1 | 2022-11-04 | PASS (52 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 2 | 2022-11-07 | PASS (54 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 5 | 2022-11-11 | PASS (52 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 10 | 2022-11-18 | PASS (54 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 20 | 2022-12-02 | PASS (53 of 56 inputs changed) |
| 2022-11-03 | A power: row n sessions later moves | 60 | 2023-01-30 | PASS (53 of 56 inputs changed) |
| 2022-11-03 | B: cut at D+n, scramble after it; 25 rows up to the cut identical | 1 | 2022-11-04 | PASS; next row 2022-11-07 changed in 52 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 26 rows up to the cut identical | 2 | 2022-11-07 | PASS; next row 2022-11-09 changed in 53 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 29 rows up to the cut identical | 5 | 2022-11-11 | PASS; next row 2022-11-14 changed in 53 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 34 rows up to the cut identical | 10 | 2022-11-18 | PASS; next row 2022-11-21 changed in 52 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 44 rows up to the cut identical | 20 | 2022-12-02 | PASS; next row 2022-12-05 changed in 53 of 56 inputs |
| 2022-11-03 | B: cut at D+n, scramble after it; 84 rows up to the cut identical | 60 | 2023-01-30 | PASS; next row 2023-01-31 changed in 52 of 56 inputs |
| 2022-11-03 | C mirror: as-of row == batch row, data full | - | 2022-11-03 | PASS |
| 2022-11-03 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-03 | PASS |
| 2022-11-03 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-03 | PASS |
| 2022-11-04 | A: scramble all data dated after D; row D and all 25 rows up to D identical | - | 2022-11-04 | PASS |
| 2022-11-04 | A power: row n sessions later moves | 1 | 2022-11-07 | PASS (52 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 2 | 2022-11-09 | PASS (54 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 5 | 2022-11-14 | PASS (54 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 10 | 2022-11-21 | PASS (54 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 20 | 2022-12-05 | PASS (53 of 56 inputs changed) |
| 2022-11-04 | A power: row n sessions later moves | 60 | 2023-01-31 | PASS (53 of 56 inputs changed) |
| 2022-11-04 | B: cut at D+n, scramble after it; 26 rows up to the cut identical | 1 | 2022-11-07 | PASS; next row 2022-11-09 changed in 53 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 27 rows up to the cut identical | 2 | 2022-11-09 | PASS; next row 2022-11-10 changed in 53 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 30 rows up to the cut identical | 5 | 2022-11-14 | PASS; next row 2022-11-15 changed in 52 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 35 rows up to the cut identical | 10 | 2022-11-21 | PASS; next row 2022-11-22 changed in 52 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 45 rows up to the cut identical | 20 | 2022-12-05 | PASS; next row 2022-12-06 changed in 52 of 56 inputs |
| 2022-11-04 | B: cut at D+n, scramble after it; 85 rows up to the cut identical | 60 | 2023-01-31 | PASS; next row 2023-02-01 changed in 52 of 56 inputs |
| 2022-11-04 | C mirror: as-of row == batch row, data full | - | 2022-11-04 | PASS |
| 2022-11-04 | C mirror: as-of row == batch row, data truncated_after_D | - | 2022-11-04 | PASS |
| 2022-11-04 | C mirror: as-of row == batch row, data scrambled_after_D | - | 2022-11-04 | PASS |
