# M12 Stock Brain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** For every idea and holding, spot classic swing setups (pullback, breakout, tight base) and breakdowns, read delivery % and genuine institutional deals, and give a short plain profile of how the stock usually moves — as context lines and a small modifier opinion, never a buy reason alone.

**Architecture:** Three pure files — `setups.py` (bars → setup/breakdown labels with evidence), `signals.py` (delivery rows → delivery signal; deal rows → institutional buy/sell signal), `profile.py` (bars → one plain line) — and a RECOGNISE plug-in (`module.py`, default SHADOW) that writes stock `Situation`s, `StockState.delivery_signal` (gap-filled into M03's record) and a `setup` modifier opinion (+0.2 per confirming signal, max +0.4; −0.2 on breakdown or institutional selling). Reader gains `delivery_rows` and `deal_rows`, as_of-bounded.

**Tech Stack:** Python 3.12, pandas, SQLAlchemy 2, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-trademind-brain-build-book.html` — module sheet "M12 Stock brain".

## Global Constraints

- Plug-in, Wave 3, step 3 Recognise (+ opinions). Reads Snapshot@1, StockState@1, delivery, bulk and block deals. Writes stock Situation@1 (setup), StockState@1 refinements, stock Opinion@1.
- Setups: pullback to the 20-day average in an up-trend; breakout above a 20-day high on 1.5× volume; tight base (10-day range < 1.5 × ATR).
- Delivery signal: delivery % above its 20-day average for 3 of the last 5 days.
- Deals: any bulk or block buy by a known institution in the last 10 days; sells count negatively.
- Profile: typical daily range, gap frequency, average days to +8% historically.
- Opinion: +0.2 per confirming signal (max +0.4), −0.2 on breakdown or institutional selling.
- If switched off: no setup labels or stock opinion. Start in SHADOW, then ON.
- Card lines like "Setup: pullback to the 20-day average in an up-trend" and "Delivery above average 4 of the last 5 days".
- Modifier opinions never speak for a stock (`brain/opinions.py` MODIFIER_SOURCES).

## Review Focus

1. High-frequency trading firms dominate stored deals and buy and sell the same stock the same day — must never count as institutional buying — Task 2 `test_same_day_round_trips_are_ignored`, `test_trading_firms_are_not_institutions`.
2. Too little history (< 60 bars) → no setup, no profile, no crash — Task 1 `test_short_history_gives_nothing`.
3. Zero volume averages (suspended stock) must not divide by zero — Task 1 `test_zero_volume_is_not_a_breakout`.
4. Delivery rows from the BE/BZ series or with missing % are ignored — Task 2 `test_delivery_ignores_missing_values`.
5. A breakdown in SHADOW mode never reaches decisions — covered by the runner's shadow contract; Task 3 asserts the module's default mode.

---

### Task 1: setups.py and profile.py (pure)

**Produces:** `Setup(label: str, line: str, confirming: bool)`; `find_setups(bars: DataFrame) -> list[Setup]` with labels `pullback in up-trend`, `breakout`, `base`, `breakdown` (close below the prior 20-day low on 1.5× volume; confirming=False); `profile_line(bars) -> str | None`.

Rules (exact): SMA20/SMA50 of close; up-trend = SMA20 > SMA50 and SMA50 higher than 10 bars ago; pullback = up-trend and today's low ≤ SMA20 × 1.01 and close ≥ SMA20 × 0.98; breakout = close > max(high of previous 20 bars) and volume ≥ 1.5 × mean(volume of previous 20 bars) > 0; base = (max high − min low of last 10 bars) < 1.5 × ATR14; breakdown = close < min(low of previous 20 bars) and volume ≥ 1.5 × mean volume.

Profile (last 250 bars): median (high − low)/close; share of days with |open / previous close − 1| > 2%; for days with 15 bars after them, share whose high reaches close × 1.08 within 15 bars, and the median days among those.

### Task 2: signals.py (pure)

**Produces:** `delivery_signal(rows: list[tuple[date, float]]) -> tuple[str | None, str | None]` ("high", "Delivery above average 4 of the last 5 days."); `is_institution(name) -> bool`; `DealRow(symbol, day, client, side, quantity)`; `deal_signal(rows, today) -> tuple[int, str | None]` (+1 buy, −1 sell, 0 none; round trips by the same client on the same day are ignored).

### Task 3: reader + module

**Files:** `brain/reader.py` (`delivery_rows(symbols, days=40)`, `deal_rows(symbols, days=10)`), `brain_fakes.FakeReader`, `m12_stock/module.py` (`StockBrain`, M12, RECOGNISE, plugin, SHADOW), `brain/opinions.py` (`"setup"` modifier), `modules/__init__.py`.

### Task 4: Real-data check, notes, memory

Run nightly with M12 ON locally (then back to SHADOW); count setups, delivery signals, deals; full suite + lint; BUILD_NOTES + memory; restart :8001.
