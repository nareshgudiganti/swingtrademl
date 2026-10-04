# Brain M16 · Alerts and Cards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tell the owner what changed after each live brain run — one grouped Telegram message for a new market mode, new TRADE ideas, and holdings that got worse (MONITOR / REDUCE / EXIT, "Stop hit") — without repeats, and show the brain's market mode on every page as a small badge.

**Architecture:** A pure alert package compares the current run with the previous comparable run (same kind, live, finished) through a pluggable detector list (`brain/alerts/detectors.py`, same pattern as M08's rules: add one function, or switch one off by id) and composes one plain-English HTML message. The service drops items already sent today (new `brain_alerts` table, unique per key and day), sends through v1's `notifier.send_sync` as a `signal` event, and records only what was actually sent. The scheduled jobs send after live nightly and intraday runs when `BRAIN_ALERTS_ENABLED` is true (default false). The console gains an alert preview and "Send now"; decision windows gain "Copy plan"; the sidebar status strip gains a market-mode badge.

**Spec:** build book module sheet M16; owner preferences: plain words, no banner repeated on every page (it pushed tables down), Telegram is the alert channel.

## Global Constraints

- Alerts only for live runs; never for replays or "why" runs.
- Effective word = owner's overrule if any, else the brain's word.
- One message per run, grouped; nothing sent when nothing changed.
- De-duplicate by key and IST day: `banner:<MODE>`, `trade:<SYMBOL>`, `holding:<SYMBOL>:<WORD>`.
- Telegram HTML: every dynamic string escaped.
- No order buttons. "Copy plan" copies text only.

## Review Focus

1. The first run ever (no previous run) announces the banner, TRADE ideas and non-HOLD holdings, not every WAIT.
2. A holding going HOLD → MONITOR alerts; MONITOR → MONITOR next run does not.
3. The same TRADE idea is announced once per day even across intraday runs.
4. Telegram disabled → nothing recorded, so enabling it later still sends.
5. A stock name with `<` or `&` cannot break the message.

### Task 1: Pure detectors and message
Files: `brain/alerts/__init__.py`, `detectors.py`, `compose.py`; tests `test_brain_alerts.py`.

### Task 2: Storage, service, API, jobs
Files: `db/models/brain.py` (`BrainAlert`), migration, `brain/alerts/service.py`, `api/v1/endpoints/brain.py`, `workers/jobs.py`, `core/config.py`; tests `test_brain_alerts_service.py`.

### Task 3: Frontend
Files: `api/client.ts`, `api/types.ts`, `pages/Brain.tsx`, `App.tsx`; typecheck, build, browser check.
