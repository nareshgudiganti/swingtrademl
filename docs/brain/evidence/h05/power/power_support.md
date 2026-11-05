# h05 run-length and false-pass support (reproducible)

History: 2022-06-24 to 2026-09-04, 1042 sessions with outcomes (5 non-overlapping 180-session windows). Table sha256 `8a314947ffea144c`.

Average net return of EVERY eligible stock under the lane's fixed rule and assumed costs: large -0.382%, mid -0.682%, small -0.846%.

## Random picks (no skill): how often does the frozen procedure say PASS?

| setting | selection PASS: large / mid / small / any group | economic PASS: large / mid / small / any group |
|---|---|---|
| history/stick0.0/missing0.0 | 1.7% / 1.0% / 1.0% / **3.6%** | 0.0% / 0.0% / 0.0% / **0.0%** |
| history/stick0.0/missing0.2 | 1.7% / 1.3% / 1.1% / **4.1%** | 0.0% / 0.0% / 0.0% / **0.0%** |
| history/stick0.8/missing0.0 | 1.3% / 1.7% / 1.6% / **4.5%** | 0.0% / 0.0% / 0.0% / **0.0%** |
| history/stick0.8/missing0.2 | 0.7% / 0.5% / 0.3% / **1.5%** | 0.0% / 0.0% / 0.0% / **0.0%** |
| bootstrap/stick0.0/missing0.0 | 0.8% / 1.2% / 0.9% / **2.9%** | 0.0% / 0.0% / 0.0% / **0.0%** |
| bootstrap/stick0.0/missing0.2 | 1.5% / 1.1% / 1.6% / **4.0%** | 0.0% / 0.0% / 0.0% / **0.0%** |
| bootstrap/stick0.8/missing0.0 | 1.7% / 1.0% / 1.5% / **4.1%** | 0.1% / 0.0% / 0.0% / **0.1%** |
| bootstrap/stick0.8/missing0.2 | 0.4% / 0.3% / 0.3% / **1.0%** | 0.0% / 0.0% / 0.0% / **0.0%** |

## A pick set with a real edge of `delta` per trade (bootstrap, sticky 0.8, 10% of sessions missed)

| run length | delta | selection PASS large / mid / small | economic PASS large / mid / small |
|---|---|---|---|
| 30 | 0.0% | 1.8% / 2.0% / 2.4% | 0.0% / 0.1% / 0.0% |
| 30 | 0.5% | 35.8% / 28.5% / 27.3% | 5.7% / 0.9% / 0.4% |
| 30 | 1.0% | 75.7% / 69.3% / 67.6% | 33.3% / 11.9% / 5.2% |
| 30 | 1.5% | 83.1% / 82.2% / 82.8% | 69.5% / 47.7% / 32.2% |
| 30 | 2.0% | 84.5% / 83.7% / 84.8% | 89.4% / 79.3% / 68.0% |
| 60 | 0.0% | 1.5% / 1.1% / 0.9% | 0.0% / 0.0% / 0.0% |
| 60 | 0.5% | 62.0% / 51.1% / 45.2% | 5.7% / 0.3% / 0.0% |
| 60 | 1.0% | 93.1% / 91.3% / 87.0% | 56.6% / 15.9% / 5.5% |
| 60 | 1.5% | 93.7% / 94.7% / 91.4% | 93.4% / 68.6% / 49.1% |
| 60 | 2.0% | 93.8% / 94.8% / 91.4% | 98.6% / 94.5% / 87.9% |
| 90 | 0.0% | 1.5% / 1.0% / 1.4% | 0.0% / 0.0% / 0.0% |
| 90 | 0.5% | 79.2% / 67.2% / 58.5% | 6.8% / 0.0% / 0.0% |
| 90 | 1.0% | 96.8% / 95.9% / 95.0% | 70.4% / 21.4% / 5.6% |
| 90 | 1.5% | 96.9% / 96.6% / 95.8% | 98.8% / 86.1% / 61.5% |
| 90 | 2.0% | 96.9% / 96.6% / 95.8% | 99.7% / 99.6% / 97.6% |
