# M15 Trade Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Follow each open trade day by day against the band of similar past trades: on track, drifting or breaking down, with a plain reason; "Stop hit" with no choice offered; at +5% the evidence for trailing the rest; stops only move up.

**Architecture:** Pure `track.py` (entry, closes since, stop, band → `TrackPoint`; first-target evidence from similar cases' paths). The band comes from M05's memory with the key the stock had **on its entry day** (`m05_memory.recall.similar_cases`), or the overall path of all known cases. A STATE plug-in (so it also runs in intraday runs) writes `TrackPoint@1` per holding; M08's holding rules turn drift/breakdown into MONITOR with what changed, and add the first-target evidence to REDUCE. `brain_track` table (stop never lower than the last stored one), `GET /brain/track/{symbol}`, a small chart in the console.

**Spec:** build book, module sheet "M15 Trade tracker and exit intelligence"; constitution C6 (stops only move up), C7 (stop hit → no choice).

## Global Constraints
- Band = 25th–75th percentile path of similar trades (M05), else the overall path. On track inside the band; drift below the band but above the stop; breakdown below the band's lower bound minus 1 ATR.
- Explain drift in plain words (market mode, stock trend, sector). Stop hit: "Stop hit…", never a choice. At +5%: how much further similar trades went toward +8%.
- Time stop is 30 CALENDAR days (do not change); past 15 trading days the card says so.
- Runs nightly and intraday; replays and why-runs never write `brain_track`.

## Review Focus
1. A stop that would move down is kept at its previous level — Task 4 `test_a_stored_stop_never_goes_down`.
2. Day 0 (bought today) has no band yet — Task 1 `test_bought_today_is_on_track_without_a_band`.
3. A holding without an entry date (old data) gets no track, not a crash — Task 3 `test_a_holding_without_entry_date_is_skipped`.
4. No similar cases at all → overall path used and said — Task 3 `test_without_similar_cases_the_overall_path_is_used`.
5. Past 15 trading days → says the time stop still applies, never "breakdown" — Task 1 `test_past_the_horizon_says_so`.

Tasks: (1) track.py; (2) similar_cases refactor in M05 + first-target evidence; (3) contracts/context, Holding.opened_on, module; (4) M08 holding rules, brain_track + migration `6e1b4d8a2c73`, storage, API, console chart; (5) real check, notes, memory, fold into brain/integration.
