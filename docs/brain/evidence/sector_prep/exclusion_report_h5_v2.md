# Exclusion report v2: 5D sector-only research set (49 large, adjustment-status aware)

PREPARATION REPORT. No data was modified. Not signed evidence. Recomputes nothing from sealed trials.

## Header: rule parameters
- Universe: 49 symbols; 49 had local daily candles.
- Label horizon (sessions): 5; feature lookback after an event (sessions): 252
- Warm-up (rows skipped at the start): 252 sessions; last 5 sessions skipped (label unknown)
- Feature window excluded: decision rows p with e <= p <= e + 252 (both ends included = 253 rows)
- Label window excluded: decision rows p with e - 5 <= p <= e - 1
- Events file: docs/brain/evidence/sector_prep/events_input_v2.csv (419 events; 32 on universe stocks)
- Base policy removes categories: EXCLUDE (price step not shown to be adjusted) and PENDING_FRESH_FETCH. RETAIN_GENUINE, RETAIN_VERIFIED_ADJUSTED and PROVISIONAL are kept.
- Adjustment status per event (ADJUSTED_OK / UNADJUSTED_CONFIRMED / PENDING / UNKNOWN) decides before the stale mechanical_step flag.
- Owner-retained genuine moves: ADANIENT, GABRIEL, GALAXYSURF, IREDA, PAYTM, POWERINDIA, WHIRLPOOL
- The 24-move rule is an anomaly screen only; unverified events stay PROVISIONAL.
- Pending fresh-fetch comparison: BAJAJELEC 2023-09-14, HINDUNILVR 2025-12-05
- Pending but NOT in this universe (no effect here): BAJAJELEC:2023-09-14

## Event classes on universe stocks
- PENDING_FRESH_FETCH: 1
- PROVISIONAL: 15
- RETAIN_GENUINE: 14
- RETAIN_VERIFIED_ADJUSTED: 2

## Counts (base policy)
- Buildable rows (after warm-up and label cut-off): 49245
- Excluded unique rows: 187  (by window type: {'feature': 182, 'label': 5})
- Retained rows: 49058
- Dataset hash (sha256 of sorted SYMBOL|DATE retained rows): 5800233d76617208db30ea6e1d42b486aee921dcb45c70b57b84f6ee1d5693c6
- Excluded-list hash: 761a9f9cf5b87da2855f8ff45de9c46bc4ebdaba2d4062f5166b00d052c628e2

## Events driving exclusions or flagged
| event id | category | adjust status | type | status |
|---|---|---|---|---|
| HINDUNILVR:2025-12-05 | PENDING_FRESH_FETCH | PENDING | demerger (Kwality Walls ice cream) | VERIFIED (dates/ratio); adjusted price not found |
| ADANIPORTS:2023-02-01 | PROVISIONAL | UNKNOWN | unknown (INFERRED market move: volume >=3x 20d med | UNVERIFIED |
| ADANIPORTS:2023-12-05 | PROVISIONAL | UNKNOWN | unknown (INFERRED market move: volume >=3x 20d med | UNVERIFIED |
| ADANIPORTS:2024-11-21 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| BAJAJ-AUTO:2024-10-17 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| BPCL:2024-06-04 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| COALINDIA:2024-06-04 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| HINDALCO:2024-02-13 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| INDUSINDBK:2024-10-25 | PROVISIONAL | UNKNOWN | unknown (INFERRED market move: volume >=3x 20d med | UNVERIFIED |
| JSWSTEEL:2022-05-23 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| LT:2024-06-04 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| ONGC:2022-07-01 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| POWERGRID:2024-06-04 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| SBIN:2024-06-04 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| TATASTEEL:2022-05-23 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| UPL:2026-02-23 | PROVISIONAL | UNKNOWN | ratio-signature only (<15% move); no event found | UNVERIFIED (no evidence of corporate action) |
| ITC:2025-01-06 | RETAIN_VERIFIED_ADJUSTED (KEPT, flagged) | ADJUSTED_OK | demerger (ITC Hotels) | VERIFIED |
| RELIANCE:2023-07-20 | RETAIN_VERIFIED_ADJUSTED (KEPT, flagged) | ADJUSTED_OK | demerger (Jio Financial Services) | VERIFIED |

## Sensitivity: rows lost
| horizon | feature lookback | removes | buildable | lost | lost % |
|---|---|---|---|---|---|
| 5 | 63 | verified+pending (base) | 49245 | 69 | 0.14 |
| 5 | 63 | verified+pending+provisional | 49245 | 947 | 1.92 |
| 5 | 126 | verified+pending (base) | 49245 | 132 | 0.27 |
| 5 | 126 | verified+pending+provisional | 49245 | 1955 | 3.97 |
| 5 | 252 | verified+pending (base) | 49245 | 187 | 0.38 |
| 5 | 252 | verified+pending+provisional | 49245 | 3705 | 7.52 |
| 10 | 63 | verified+pending (base) | 49000 | 74 | 0.15 |
| 10 | 63 | verified+pending+provisional | 49000 | 1012 | 2.07 |
| 10 | 126 | verified+pending (base) | 49000 | 137 | 0.28 |
| 10 | 126 | verified+pending+provisional | 49000 | 2016 | 4.11 |
| 10 | 252 | verified+pending (base) | 49000 | 187 | 0.38 |
| 10 | 252 | verified+pending+provisional | 49000 | 3750 | 7.65 |

## Exact excluded rows (base policy)
| symbol | decision date | window | reason | event id |
|---|---|---|---|---|
| HINDUNILVR | 2025-11-28 | label | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-01 | label | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-02 | label | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-03 | label | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-04 | label | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-05 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-08 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-09 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-10 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-11 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-12 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-15 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-16 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-17 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-18 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-19 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-22 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-23 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-24 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-26 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-29 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-30 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2025-12-31 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-01 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-02 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-05 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-06 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-07 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-08 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-09 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-12 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-13 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-14 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-16 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-19 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-20 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-21 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-22 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-23 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-27 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-28 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-29 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-01-30 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-01 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-02 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-03 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-04 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-05 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-06 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-09 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-10 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-11 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-12 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-13 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-16 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-17 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-18 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-19 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-20 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-23 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-24 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-25 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-26 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-02-27 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-02 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-04 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-05 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-06 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-09 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-10 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-11 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-12 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-13 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-16 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-17 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-18 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-19 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-20 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-23 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-24 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-25 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-27 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-03-30 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-01 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-02 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-06 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-07 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-08 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-09 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-10 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-13 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-15 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-16 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-17 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-20 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-21 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-22 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-23 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-24 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-27 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-28 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-29 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-04-30 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-04 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-05 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-06 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-07 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-08 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-11 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-12 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-13 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-14 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-15 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-18 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-19 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-20 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-21 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-22 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-25 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-26 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-27 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-05-29 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-01 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-02 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-03 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-04 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-05 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-08 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-09 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-10 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-11 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-12 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-15 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-16 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-17 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-18 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-19 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-22 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-23 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-24 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-25 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-29 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-06-30 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-01 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-02 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-03 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-06 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-07 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-08 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-09 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-10 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-13 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-14 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-15 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-16 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-17 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-20 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-21 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-22 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-23 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-24 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-27 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-28 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-29 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-30 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-07-31 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-03 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-04 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-05 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-06 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-07 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-10 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-11 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-12 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-13 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-14 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-17 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-18 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-19 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-20 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-21 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-24 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-25 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-26 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-27 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-28 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
| HINDUNILVR | 2026-08-31 | feature | PENDING_FRESH_FETCH: demerger (Kwality Walls ice cream) (VERIFIED (dates/ratio); adjusted price n) | HINDUNILVR:2025-12-05 |
