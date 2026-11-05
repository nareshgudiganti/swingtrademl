# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths are relative to this script; set SWING_LOCAL_DB_URL (local Postgres connection string) and optionally SWING_EVIDENCE_WORK.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import os, pathlib
_HERE = pathlib.Path(__file__).resolve().parent
EVID = _HERE.parent  # the corporate_actions evidence folder (events.csv lives here)
SPLIT_JSON = EVID.parent / "stock_split" / "stock_split_ev15.json"
WORK = pathlib.Path(os.environ.get("SWING_EVIDENCE_WORK", EVID / "work"))  # intermediates/outputs; override with SWING_EVIDENCE_WORK
WORK.mkdir(parents=True, exist_ok=True)
def _dsn():
    v = os.environ.get("SWING_LOCAL_DB_URL")
    if not v:
        raise SystemExit("Set SWING_LOCAL_DB_URL, e.g. postgresql://swingtrade:<LOCAL_PG_PASSWORD>@localhost:5433/swing_trade_ml (local Docker Postgres)")
    return v
import pandas as pd
P = str(WORK)
E = pd.read_csv(str(EVID / "events.csv"))


def md(df):
    cols = ['stock', 'date', 'move_pct', 'open_gap_pct', 'vol_vs_20d_median', 'event_type', 'ratio', 'status', 'in_49', 'source_url']
    lines = ['| ' + ' | '.join(['Stock', 'Date', 'Close move %', 'Open gap %', 'Vol x 20d med', 'Type', 'Ratio', 'Status', 'In 49', 'URL']) + ' |', '|' + '---|' * len(cols)]
    for r in df[cols].itertuples(index=False):
        vals = ['' if pd.isna(v) else str(v).replace('|', '/') for v in r]
        lines.append('| ' + ' | '.join(vals) + ' |')
    return '\n'.join(lines)


A = E[E.mechanical_step].sort_values(['in_49', 'date'], ascending=[False, True])
B = E[(E.in_49 == 'yes') & ~E.mechanical_step & (E.move_pct.abs() >= 15)].sort_values('date')
C = E[(E.in_49 == 'no') & ~E.mechanical_step & (E.move_pct.abs() >= 20)].sort_values('date')
open(str(WORK / "tbl_A.md"), 'w', encoding='utf-8').write(md(A))
open(str(WORK / "tbl_B.md"), 'w', encoding='utf-8').write(md(B))
open(str(WORK / "tbl_C.md"), 'w', encoding='utf-8').write(md(C))
print(len(A), len(B), len(C))
rest = E[(E.in_49 == 'no') & ~E.mechanical_step & (E.move_pct.abs() < 20)]
print('rest rows', len(rest), 'of which >=15', (rest.move_pct.abs() >= 15).sum())
