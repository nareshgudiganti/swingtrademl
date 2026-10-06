# Manual QA — Vijay (and other testers)

This folder is the **single place** for human testing of Swing Trade ML / TradeMind.

| File | Purpose |
|------|---------|
| [MANUAL_TEST_PLAN.md](MANUAL_TEST_PLAN.md) | All test cases (IDs, steps, pass/fail rules) |
| [DAILY_REPORT_TEMPLATE.md](DAILY_REPORT_TEMPLATE.md) | Copy this each day for your report |
| [reports/](reports/) | One file per day: `YYYY-MM-DD-vijay.md` |

**Brain-only deep checks:** also use [../brain/TESTING.md](../brain/TESTING.md) (Levels 1–2 daily, Level 3 when debugging).

**Rules (non‑negotiable):**

- Test only **`TRADING_MODE=paper`** on local. Never enable live trading.
- Manual paper trades are section **P**: **Discover → Watchlist** to buy, **Portfolio → Positions** to see and sell. Owner only. Free and Pro do not see Watchlist. Needs `PAPER_TESTER_ENABLED=true`.
- Do **not** click **Approve** on brain ideas in production unless the owner asks.
- Do **not** paste secrets (`.env`, API keys, tokens) into reports or chat.
- Kite login on local **invalidates** the same API key’s prod session — use owner guidance before Kite tests.

## Daily workflow (pattern)

1. **Start** — Note environment (local URL or prod), git commit (`git rev-parse --short HEAD`), Docker healthy.
2. **Smoke (~15 min)** — Run section **S** in the test plan.
3. **Focus (~45–90 min)** — Rotate one area per day (Auth → Classic app → TradeMind → Brain → Settings/API).
4. **Report** — Copy `DAILY_REPORT_TEMPLATE.md` → `reports/YYYY-MM-DD-vijay.md`, fill in, commit on your branch or send to owner.

## Where to put reports

```text
docs/qa/reports/2026-10-06-vijay.md
```

Commit on branch `vijay/qa-reports` (or as the owner prefers) so history is visible in git.
