# Scoreboard: independent check (2026-11-03)

Tests: `backend/tests/test_scoreboard_independent.py` (pure, no database). Reference maths in the test file is written
from the protocol definitions, not copied from production code. Nothing in production was changed.

## Where each measure is computed, and shown

| Measure | 5-day (h05) | 10-day | 15-day |
|---|---|---|---|
| Ranking quality | none forward. Only the endpoint-label hit rate (`h05_report._endpoint`, `label_edge`) | history only: none (td_v1 has edge, no IC) | history: `selection_lab.daily_ic/r1/top5_measures`, read by `lanes.history_for` (mean IC, lower bound) |
| Excess vs every stock | `h05_report._daily_edge` / `group_series` (per signal day), UI "Better than every eligible stock by" | forward: `lane_service` excess per pick, pooled in `lanes.forward_view`; history `ten_day.evaluate` pooled `model_edge_per_day` | same as 10-day forward; history: no excess stored in sl_v1 |
| Excess vs random-5 | `h05_report.summarise_group` random range (report only, not on the horizon page) | history only: `phase_b.random5_trade` | none |
| Excess vs NIFTY 50 | NIFTY mean return shown, never subtracted | same | none (history_for has none) |
| Net after costs | `h05_rules.simulate_trade` -> `trade.mean_net_return` | `ten_day.score_trade` / `lane_service.score_window` -> `forward.mean_net_return` | `replay_scoring.strict_score` |
| Consistency (share of months) | none (days, not months) | none (td-protocol asks for it; not built) | `selection_lab.r3` folds share (history only) |
| Portfolio drawdown | none | history: `ten_day._account` -> best_5 `max_drawdown`; forward: pick-level only | forward: pick-level only |

See the final report of the session for file:line references and the findings list.
