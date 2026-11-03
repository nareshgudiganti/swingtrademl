# Corporate-action evidence (2026-11-03)

**Status: PRELIMINARY EVIDENCE. No data was changed.** Nothing here alters a price, a signed protocol, a sealed record, a result or a model. All database work was SELECT-only against the local Docker Postgres. No production call was made.

## Purpose
Record, durably, what was found when the local daily candles were checked for corporate actions (splits, bonuses, demergers) and what the effect on past results would be if they were ever corrected.

## Labels
- **VERIFIED**: an external record (URL given) or a direct read of our database/code.
- **INFERRED**: derived from our data or from secondary reasoning.
- **UNKNOWN**: could not be determined.

## Data cutoff
Local candles end **2026-09-08** (IST dates). 306 NSE EQ stocks, 378,034 daily bars, 2021-08-06 to 2026-09-08.

## Contents
| File | What it is |
|---|---|
| `corporate_actions_audit.md` | First full audit: summary (i), flagged-event tables A/B/C (ii), adjusted-or-not (iii), impact (iv), policy recommendation, not implemented (v), unknowns (vi) |
| `verify49_report.md` | Follow-up on the three mechanical steps inside the 49 primary stocks (RELIANCE, ITC, HINDUNILVR), sensitivity of past results, positions, nightly-ingestion risk |
| `events.csv` | All 419 flagged rows with type, ratio, status, source URL |
| `impact_by_event.csv` | Per mechanical event: how many feature/label rows its windows touch |
| `sens.json` | Output of the sensitivity run (`verify49_scripts/sens.py`) quoted in `verify49_report.md` section 4 |
| `audit_scripts/` | Scripts behind the audit |
| `verify49_scripts/` | Scripts behind the follow-up |
| `CHECKSUMS.txt` | sha256 of every file in this folder (except itself) |

## How each number was produced
Run order for the audit (each script only reads the DB; some write local files):
1. `audit_scripts/scan.py` reads the candles and writes `bars.pkl` and `raw_flags.csv` (the scan: close-to-close move, open gap, volume vs 20-day median, ratio signature). These two intermediates are not kept (bars.pkl is 33 MB); rerun to regenerate.
2. `audit_scripts/build.py` adds the event type / ratio / status / URL (hand-entered in the script from the web research) and writes `events.csv` and `impact_by_event.csv` (feature windows 5/10/20/50/200/252 and label windows 5/10/15).
3. `audit_scripts/mk_tables.py` turns `events.csv` into tables A, B, C (these are in `corporate_actions_audit.md`).
4. `scan2.py`, `scan3.py`, `known.py`, `show.py` are exploration helpers (signature checks, known split dates, listing); `q1.py`, `arr.py`, `dbcheck.py` check table contents (corrections table, candle arrival times, table list).
Follow-up: `verify49_scripts/q*.py` print the raw candles around the three ex-dates, the watchlist, and positions/signals date ranges; `sens.py` recomputes the every-stock 5D average with affected stock-days excluded (writes `sens.json`); it imports `swing_trade_ml`, so run it with the backend package importable.

How to run any script: `backend/.venv/Scripts/python.exe -I <script>` with local Docker Postgres up on port 5433. Edit the original-machine paths at the top of each script, and put the local DB password in place of `<LOCAL_PG_PASSWORD>`. I did not re-run the scripts while assembling this folder, so reproducibility from these copies is untested.

## Caveats
- 355 of 419 flagged rows are UNVERIFIED (mostly +/-20% high-volume days, INFERRED to be circuit-band market moves). They were not searched individually.
- Web evidence is search snippets and news articles; where a company or exchange PDF is cited, it was returned by search and not opened.
- Production candles were not examined; they may differ from local ones.
- Dividends, rights issues, mergers and small (<7%) residual steps were not checked.
- No recomputation of any verdict after a correction was done, other than the scorer-level sensitivity in `verify49_report.md`.
