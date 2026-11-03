# READ-ONLY SELECT script: it only reads the local candle database and writes local files (never to the database).
# Run: backend/.venv/Scripts/python.exe -I <this file>   (local Docker Postgres, port 5433, must be up)
# The DB password was replaced by <LOCAL_PG_PASSWORD>; put the local Docker password there before running. Paths below are from the original machine and must be edited.
# Preserved as evidence from 2026-11-03; not a maintained tool.
import pandas as pd
P = r"C:\Users\nares\AppData\Local\Temp\claude\d--machine-learning-swing-trade-bot\7760ad1c-0af2-4782-9c69-ebf2dca1d1d5\scratchpad\corp_actions"
E = pd.read_csv(P + r"\events.csv")


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
open(P + r"\tbl_A.md", 'w', encoding='utf-8').write(md(A))
open(P + r"\tbl_B.md", 'w', encoding='utf-8').write(md(B))
open(P + r"\tbl_C.md", 'w', encoding='utf-8').write(md(C))
print(len(A), len(B), len(C))
rest = E[(E.in_49 == 'no') & ~E.mechanical_step & (E.move_pct.abs() < 20)]
print('rest rows', len(rest), 'of which >=15', (rest.move_pct.abs() >= 15).sum())
