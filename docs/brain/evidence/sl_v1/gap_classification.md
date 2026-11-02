# Overnight moves over 20% in the 177 stocks: written classification (sl-protocol-v1)

Found by the lab's own rule on the local price data (6 moves in 6 stocks). Checked against public news on 2026-11-02.

| Stock | Day | Move | Class | Why |
|---|---|---|---|---|
| ABFRL | 2025-05-22 | -52% | verified_error | Ex-date of the Madura demerger (1:1). A mechanical price break, not a market return. |
| SANOFI | 2024-06-13 | -30% | verified_error | Ex-date of the consumer-healthcare demerger (1:1). Mechanical price break. |
| VEDL | 2026-04-30 | -29% | verified_error | Ex-date of the Vedanta demerger into four companies. Mechanical price break. |
| PAYTM | 2024-02-02 | -20% | real_gap | Second straight lower circuit after the RBI order on Paytm Payments Bank. A real move; kept. |
| BAJAJELEC | 2023-09-14 | +32% | unresolved | No source found for this day. Kept in the main run, dropped in the sensitivity run. |
| KFINTECH | 2025-04-07 | -20% | unresolved | No source found for this day. Kept in the main run, dropped in the sensitivity run. |

"verified_error" removes the affected training days; "real_gap" is always kept; "unresolved" is kept in the main
result and dropped only in the sensitivity run. Prepared by the assistant from news reports; the owner reviews it by
merging. Nothing was run.
