# Model evidence screen — content spec (DRAFT, 2026-11-11)

**Status: DRAFT. Nothing built. Layout comes from the "Design preview" mock-up; this note fixes the content.**
**Audience: owner (decisions) and whoever builds it.** Owner-only screen (`require_owner`), like `/research/h05/*`.

## Rules for every number on this screen

1. Every figure is read from stored records (`GET /research/h05/report`), never typed in.
2. Three kinds of evidence are **never** combined, never in one card, never in one total:
   earlier historical test, h05 forward test, paper trading.
3. Say "forward evidence", never "proof". Say what is collected and what is still needed.
4. Plain English first; the technical name goes behind "details".
5. Honest small-sample wording: under 40 matured days, show **"Collecting evidence"**, not a verdict.

## Section 1 — three summary cards (top)

| Card | Title | Status chip | Body | Source |
|---|---|---|---|---|
| 1 | Earlier 5-day test (26 Oct) | **Failed** (history) | "Tested on 21 past periods. The picks beat the average stock in 10." Detail: lower bound −0.155%. | `earlier_evidence` |
| 2 | Earlier 5-day test, money | **Failed** (history) | "Made money in 3 of 17 past periods. Average −0.42% per trade after costs." | `earlier_evidence` |
| 3 | Brain WATCH filter | **Proposed, not started** | "Not tested yet. The question: do WATCH stocks do better than the model alone?" No numbers. | none until a signed protocol exists |

Remove the mock-up's "60% required" line. h05 has no such rule, and the earlier test's rule has not been verified.

## Section 2 — "5-day forward test (h05)" table

Columns: Model · Days collected · Days with a result · Status. One row each for Model 2 (large), 16 (mid), 17 (small).

| Field | Meaning in plain words | Source |
|---|---|---|
| Days collected | "Day 6 of 60" | `runs[0].days_recorded`, run length 60 |
| Days with a result | Days whose 5-day outcome is known (today 2 to 4) | `groups.*.shadow_trade.daily_edge_vs_baseline.days` |
| Status | **Collecting evidence** until 40 matured days; then PASS / FAIL / INCONCLUSIVE from `verdict` | `verdict.<group>.runs.1` |

Status chip wording: "Collecting evidence" (grey) · "Inconclusive" (amber) · "Passed" (green) · "Failed" (red).
Never "Pending verification".

## Section 3 — expanded row (per model)

- **Test window:** 2 Nov 2026 to 28 Jan 2027 (run 1 of 3).
- **The question it answers:** "Do the model's top 5 picks beat the average stock in its group, and do they make money after costs?" Two answers, shown separately.
- **What counts as a pass:** "The picks must beat the average stock with the whole uncertainty range above zero, in at least 2 of the 3 runs, and never fail a run."
- **Needed before any verdict:** 40 days with results. Today: N.
- **So far (not a verdict):** finished picks, average return per trade, versus the every-stock baseline and random picks. Always with the note "too few days to judge".
- **Details (tap):** protocol code and hash, model id and version, exits (target/stop/expiry), same-candle and gap counts.
- **Assumptions line (always visible):** "Hypothetical fixed-rule picks. No position limits, no real money. Slippage is estimated from daily candles."

## Section 4 — "Things that could weaken this test" (shown, not hidden)

Read from the report each time; do not hard-code.
- Missed sessions (today: 1 — signal day 8 Nov, job did not run; not replaced).
- Stocks not scored (today: TMCV invalid features; ICICIPRULI, HEG not found).
- Stocks excluded for belonging to two groups (today: JYOTHYLAB, BLUESTARCO).
- Input difference: "The app's live score uses a different `obv_slope` than the models were trained on (since 5 Oct). This test scores the models as trained; the live score is shown as a diagnostic only."

## Open items before building

- [ ] Owner confirms what is signed: report says "DRAFT-4" and accepted, but U1–U13 still read PROPOSED.
- [ ] Check why the 8 Nov session was missed (job did not run; 8 Nov 2026 is a Sunday, so it may have been a special session).
- [ ] Decide if the WATCH-filter card appears before its protocol is signed (proposed: yes, as "not started").
- [ ] Build only after the owner approves; dev freeze is 30 Nov.
