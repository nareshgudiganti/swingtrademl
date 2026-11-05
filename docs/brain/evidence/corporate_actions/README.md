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
| `hul_fresh_fetch_readonly.sh` | Read-only script for the owner to compare fresh Kite bars for HINDUNILVR and BAJAJELEC with stored values (hardened 2026-11-05; never run) |
| `FETCH-INSTRUCTIONS.md` | Plain-English instructions for running that script and what to send back |
| `CHECKSUMS.txt` | sha256 of every file in this folder (except itself); see "Checksums" below |

## How each number was produced
Run order for the audit (each script only reads the DB; some write local files):
1. `audit_scripts/scan.py` reads the candles and writes `bars.pkl` and `raw_flags.csv` (the scan: close-to-close move, open gap, volume vs 20-day median, ratio signature). These two intermediates are not kept (bars.pkl is 33 MB); rerun to regenerate.
2. `audit_scripts/build.py` adds the event type / ratio / status / URL (hand-entered in the script from the web research) and writes `events.csv` and `impact_by_event.csv` (feature windows 5/10/20/50/200/252 and label windows 5/10/15).
3. `audit_scripts/mk_tables.py` turns `events.csv` into tables A, B, C (these are in `corporate_actions_audit.md`).
4. `scan2.py`, `scan3.py`, `known.py`, `show.py` are exploration helpers (signature checks, known split dates, listing); `q1.py`, `arr.py`, `dbcheck.py` check table contents (corrections table, candle arrival times, table list).
Follow-up: `verify49_scripts/q*.py` print the raw candles around the three ex-dates, the watchlist, and positions/signals date ranges; `sens.py` recomputes the every-stock 5D average with affected stock-days excluded (writes `sens.json`); it imports `swing_trade_ml`, so run it with the backend package importable.

How to run any script: `backend/.venv/Scripts/python.exe -I <script>` with local Docker Postgres up on port 5433. Set the environment variable `SWING_LOCAL_DB_URL` to the local Postgres connection string (the `<LOCAL_PG_PASSWORD>` placeholder stands for the local Docker password; a script that needs it stops with a clear message if the variable is unset, and never prints it). Inputs are read from this folder by a path relative to the script (`events.csv`, `../stock_split/stock_split_ev15.json`); intermediates and outputs go to `work/` next to this README (git-ignored), or to the folder named by `SWING_EVIDENCE_WORK`. I did not re-run the scripts while assembling this folder, so reproducibility from these copies is untested.

## Caveats
- 355 of 419 flagged rows are UNVERIFIED (mostly +/-20% high-volume days, INFERRED to be circuit-band market moves). They were not searched individually.
- Web evidence is search snippets and news articles; where a company or exchange PDF is cited, it was returned by search and not opened.
- Production candles were not examined; they may differ from local ones.
- Dividends, rights issues, mergers and small (<7%) residual steps were not checked.
- No recomputation of any verdict after a correction was done, other than the scorer-level sensitivity in `verify49_report.md`.

## Portability change (2026-11-05)
On 2026-11-05 the scripts in `audit_scripts/` and `verify49_scripts/` were made portable: the owner's machine-specific absolute paths (a Windows user profile scratchpad and a `D:` drive project path) were replaced by paths relative to the script, the database connection string by the `SWING_LOCAL_DB_URL` environment variable, and the output location by `work/` / `SWING_EVIDENCE_WORK`. No query, formula, number or conclusion was changed. The scripts were not re-run after this change.

## Checksums
`CHECKSUMS.txt` was recomputed on 2026-11-05. The hashes of the changed scripts and of this README differ from the earlier list **because of the portability change above and nothing else**. Also, the hashes are now taken with carriage returns removed, so they match on Windows and Linux checkouts alike (the earlier list was computed on Windows files with CRLF line endings and would not verify on a Linux checkout). To verify one file: `tr -d '\r' < path | sha256sum`. Note: `events.csv` and `impact_by_event.csv` were listed here but had been left out of the repository by the global `*.csv` ignore rule; they are now included (the ignore rule has an exception for this folder) and their content is unchanged from the original listing.
