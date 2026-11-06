# Row reconciliation v2: SX5 / SX10 eligible rows (PREPARATION; nothing trained)

Each raw stock-day row is counted ONCE, against the first reason that applies, in this order: warm-up (first 252 sessions) -> label incomplete (last h sessions) -> corporate-action event window -> existing-input gap -> sector gap. Rows that also meet a later reason are in the overlap tables.
Universe: 49 model stocks; SX universe = 47 mapped; unmapped (features missing, never 0): ASIANPAINT, BHARTIARTL.
Events file rows: 419. Adjustment status: RELIANCE 2023-07-20 and ITC 2025-01-06 ADJUSTED_OK (retained, flagged); HINDUNILVR 2025-12-05 PENDING (removed); BAJAJELEC 2023-09-14 PENDING (not in the 49).

## Horizon 5 sessions

| universe | raw rows | warm-up | label incomplete | event windows | existing-input gap | sector gap | final eligible |
|---|---|---|---|---|---|---|---|
| (i) SX 47 mapped, sector required | 59314 | 11844 | 235 | 187 | 1103 | 10 | **45935** |
| (ii) full 49 baseline, existing inputs only | 61838 | 12348 | 245 | 187 | 1149 | 0 | **47909** |

(iii) Matched baseline = existing inputs on exactly the (i) rows: **45935** rows (a subset of (ii): True).

| set | final rows | dataset sha256 (sorted SYMBOL and DATE) |
|---|---|---|
| (i) SX 47 | 45935 | `fdf0b5665613a501f059d6f6de421463673156efcc1b5a9e7a35fe18e1d19f04` |
| (ii) full 49 baseline | 47909 | `8b32492c653890e5da4334d888893b73c7f417a8d7ccf2c86ce610c68c0e10af` |
| (iii) matched baseline | 45935 | `fdf0b5665613a501f059d6f6de421463673156efcc1b5a9e7a35fe18e1d19f04` (same row list as (i)) |

Exclusion-report policy numbers (event rows only, before the existing-input gap stage): buildable 49245, excluded 187 {'feature': 182, 'label': 5}, retained 49058, sha256 `5800233d76617208db30ea6e1d42b486aee921dcb45c70b57b84f6ee1d5693c6`.

### Events (each row once; earliest event wins)
- (i) HINDUNILVR:2025-12-05: 187 rows {'label': 5, 'feature': 182}
- event vs event overlap: none

### Overlaps: rows counted at the first stage that also meet a later reason
| universe | overlap | rows |
|---|---|---|
| (i) SX 47 | warm_up+existing_gap | 11844 |
| (i) SX 47 | warm_up+sector_gap | 1606 |
| (i) SX 47 | label_incomplete+existing_gap | 235 |
| (ii) full 49 | warm_up+existing_gap | 12348 |
| (ii) full 49 | label_incomplete+existing_gap | 245 |

Event windows that also have a sector gap: 0 rows (HINDUNILVR window vs sector gaps).

### Coverage loss of the SX 47 versus the full-49 baseline
1974 rows (4.12% of the full-49 baseline): {'APOLLOHOSP': 10, 'ASIANPAINT': 982, 'BHARTIARTL': 982}. ASIANPAINT and BHARTIARTL are unmapped; APOLLOHOSP loses rows because NIFTY HEALTHCARE history is incomplete early.

### Cross-check against the research assembler (`assemble_training_matrix`)
{'assembler_rows': 45935, 'reconciliation_rows': 45935, 'identical_row_sets': True, 'only_in_assembler': 0, 'only_in_reconciliation': 0}

## Horizon 10 sessions

| universe | raw rows | warm-up | label incomplete | event windows | existing-input gap | sector gap | final eligible |
|---|---|---|---|---|---|---|---|
| (i) SX 47 mapped, sector required | 59314 | 11844 | 470 | 187 | 1103 | 10 | **45700** |
| (ii) full 49 baseline, existing inputs only | 61838 | 12348 | 490 | 187 | 1149 | 0 | **47664** |

(iii) Matched baseline = existing inputs on exactly the (i) rows: **45700** rows (a subset of (ii): True).

| set | final rows | dataset sha256 (sorted SYMBOL and DATE) |
|---|---|---|
| (i) SX 47 | 45700 | `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444` |
| (ii) full 49 baseline | 47664 | `2a4cf9e4b4dd1b0a8a0a90a14b9ee6f83b82d7296c67376b32b9c22d78a5f852` |
| (iii) matched baseline | 45700 | `d10ef048f52a7bfe377472ff51814f8f3710998a5847f3159e7ae66fe359b444` (same row list as (i)) |

Exclusion-report policy numbers (event rows only, before the existing-input gap stage): buildable 49000, excluded 187 {'feature': 177, 'label': 10}, retained 48813, sha256 `5bd1c1884a727fe036e3f05bdd39c793450cb7db1d50daf6da7d985316d0f842`.

### Events (each row once; earliest event wins)
- (i) HINDUNILVR:2025-12-05: 187 rows {'label': 10, 'feature': 177}
- event vs event overlap: none

### Overlaps: rows counted at the first stage that also meet a later reason
| universe | overlap | rows |
|---|---|---|
| (i) SX 47 | warm_up+existing_gap | 11844 |
| (i) SX 47 | warm_up+sector_gap | 1606 |
| (i) SX 47 | label_incomplete+existing_gap | 470 |
| (ii) full 49 | warm_up+existing_gap | 12348 |
| (ii) full 49 | label_incomplete+existing_gap | 490 |

Event windows that also have a sector gap: 0 rows (HINDUNILVR window vs sector gaps).

### Coverage loss of the SX 47 versus the full-49 baseline
1964 rows (4.121% of the full-49 baseline): {'APOLLOHOSP': 10, 'ASIANPAINT': 977, 'BHARTIARTL': 977}. ASIANPAINT and BHARTIARTL are unmapped; APOLLOHOSP loses rows because NIFTY HEALTHCARE history is incomplete early.

### Cross-check against the research assembler (`assemble_training_matrix`)
{'assembler_rows': 45700, 'reconciliation_rows': 45700, 'identical_row_sets': True, 'only_in_assembler': 0, 'only_in_reconciliation': 0}

