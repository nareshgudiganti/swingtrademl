"""Monthly evidence pack (evidence plan task A5). Read-only.

One report per month with three labelled sections that are never added together: practice (brain ideas),
paper (version 1 account), backtest (frozen verdicts). Each section reuses the code that already owns it
(`evidence.py`): practice is the Observatory's Outcomes (`outcomes.build`) plus the official forward gate,
backtest is the Observatory's verdicts. Practice ideas are compared with the `evidence-defs-v1` baselines at
trade level and at portfolio level, on the same sessions and prices the Outcomes page loads. Built on prod
through `GET /brain/observatory/evidence-pack?month=YYYY-MM`, then committed under
`docs/brain/evidence/packs/`.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime
from typing import Any

from swing_trade_ml.services.brain_observatory import baselines, defs, evidence, fills, outcomes, spot_check
from swing_trade_ml.services.brain_observatory.redact import redact_text

PORTFOLIO_CAPITAL = 1_000_000.0  # every portfolio account in the pack starts with this
CANDIDATE_SETS = ("brain_trade", "brain_top5", "brain_over_80")
SET_NAMES = {
    "brain_trade": "Brain says TRADE",
    "brain_top5": "Brain top 5 by score",
    "brain_over_80": "Score 80 or more (top 5)",
}


def month_bounds(month: str, today: date) -> tuple[date, date]:
    """First day of `month` (YYYY-MM) and its last day, or today if the month is not over."""
    start = date.fromisoformat(f"{month}-01")
    end = date(start.year, start.month, monthrange(start.year, start.month)[1])
    return start, min(end, today)


def practice_baselines(db, start: date, end: date) -> dict[str, Any]:
    """Trade-level and portfolio-level baselines for the three followed sets of the practice sessions.

    Sessions, prices and NIFTY are loaded exactly as the Outcomes page loads them for `category=practice`
    (`outcomes._journal`: live nightly runs, paper book, practice stage, bounded bars), so the "Brain says
    TRADE" trade-level row is the Outcomes page's computed row."""
    from swing_trade_ml.brain.portfolio_sim import Pick
    from swing_trade_ml.brain.trial_journal import picks_for
    from swing_trade_ml.ml.sector_map import get_sector_bucket

    _, ctx, error = outcomes._journal(
        db,
        start,
        end,
        live=True,
        book=outcomes.BOOK,
        stage_filter=outcomes.PRACTICE_STAGE,
        with_journal=False,
    )
    sessions = ctx["sessions"]
    if error is not None:
        return {
            "available": False,
            "sessions": len(sessions),
            "why": f"The baselines could not be computed: {error}",
        }
    if not sessions:
        return {"available": True, "sessions": 0}
    try:
        pool = {s.day: sorted({i.symbol for i in s.ideas}) for s in sessions}
        scores = {(s.day, i.symbol): i.score for s in sessions for i in s.ideas}
        bars = {s: df for s, df in ctx["bars"].items() if len(df)}
        index_bars = ctx["index_bars"]
        buckets = {s: get_sector_bucket(s) for s in bars}
        days = sorted({d for df in bars.values() for d in df["day"] if d >= sessions[0].day})

        out: dict[str, Any] = {
            "available": True,
            "sessions": len(sessions),
            "trade_level": {},
            "portfolio_level": {},
        }
        shared = baselines.portfolio_baselines(
            pool, bars, days, buckets, index_bars, capital=PORTFOLIO_CAPITAL
        )
        for name in CANDIDATE_SETS:
            picks = {s.day: picks_for(s)[name] for s in sessions}
            out["trade_level"][name] = baselines.trade_level(picks, pool, bars, index_bars)
            cand = [
                Pick(d, sym, scores.get((d, sym)) or 0.0, buckets.get(sym))
                for d, syms in picks.items()
                for sym in syms
            ]
            out["portfolio_level"][name] = baselines.portfolio_level(
                cand, pool, bars, days, buckets, index_bars, capital=PORTFOLIO_CAPITAL, shared=shared
            )
        return out
    except Exception as exc:  # noqa: BLE001 — shown to the owner as 'not available', never hidden
        return {
            "available": False,
            "sessions": len(sessions),
            "why": f"The baselines could not be computed: {redact_text(f'{type(exc).__name__}: {exc}')}",
        }


def build_pack(db, month: str, today: date) -> dict[str, Any]:
    start, end = month_bounds(month, today)
    practice = evidence.practice(db, start, end)
    paper = evidence.paper(db)
    backtest = evidence.backtest()
    return {
        "month": month,
        "from": start.isoformat(),
        "to": end.isoformat(),
        "complete_month": end == date(start.year, start.month, monthrange(start.year, start.month)[1]),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "defs": defs.EVIDENCE_DEFS_VERSION,
        "label": defs.OBSERVED_NOT_PROOF,
        "sections": {
            evidence.Category.PRACTICE.value: practice.as_dict()
            | {
                # The whole trial cohort, never this month alone (as /brain/observatory/forward-gate).
                "forward_gate": outcomes.official_forward_gate(db, today),
                "baselines": practice_baselines(db, start, end),
            },
            evidence.Category.PAPER.value: paper.as_dict(),
            evidence.Category.BACKTEST.value: backtest.as_dict(),
        },
        # Not a fourth kind of evidence: how realistic the recorded fill prices were (ps4).
        "fills": fills.fill_quality(db, start, end)["summary"],
        # Are the stated reasons true? 20 random decisions rechecked from raw prices (ps9).
        "spot_check": {k: v for k, v in spot_check.spot_check(db, start, end).items() if k != "rows"},
    }


# --- plain report ------------------------------------------------------------------------------


def _pct(x: float | None, digits: int = 2) -> str:
    return "n/a" if x is None else f"{x * 100:+.{digits}f}%"


def _share(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def _trade_table(name: str, t: dict) -> list[str]:
    c, e, r, m, n = t["candidate"], t["every_stock"], t["random_5"], t["momentum_5"], t["nifty_matched"]
    edge = t["edge"]
    return [
        f"**{SET_NAMES[name]}**: {c['picked']} picked, {c['finished']} finished, {c['open']} still open, "
        f"on {t['coverage']['days_with_ideas']} of {t['coverage']['days_available']} sessions.",
        "",
        "| Compared with (same days, entry, exit rule and costs) | Finished | Average per idea "
        "| Hit target |",
        "|---|---|---|---|",
        f"| {SET_NAMES[name]} | {c['finished']} | {_pct(c['avg_net'])} | {_share(c['hit_rate'])} |",
        f"| Every stock (random average) | {e['finished']} | {_pct(e['avg_net'])} "
        f"| {_share(e['hit_rate'])} |",
        f"| Random 5 ({r['draws']} draws) | - | {_pct(r['avg_net_mean'])} (5th-95th: {_pct(r['p5'])} to "
        f"{_pct(r['p95'])}); beaten in {_share(r['beaten_share'])} of draws | - |",
        f"| Momentum 5 (strongest 20-day risers) | {m['finished']} | {_pct(m['avg_net'])} "
        f"| {_share(m['hit_rate'])} |",
        f"| NIFTY, matched holding period* | {n['finished']} | {_pct(n['avg_net'])} | - |",
        "| Cash | - | +0.00% | - |",
        "",
        f"Daily edge over every stock: {_pct(edge['mean'])} over {edge['days']} days; "
        f"confidence: **{edge['word']}**"
        + ("" if edge["lower_bound"] is None else f" (lower bound {_pct(edge['lower_bound'])})")
        + ".",
        "",
    ]


def _fall(x: float | None) -> str:
    """A fall from the peak, shown as a negative percentage (a zero fall is 0.0%, not -0.0%)."""
    return "n/a" if x is None else ("0.0%" if x <= 0 else f"{-x * 100:.1f}%")


def _risk_row(label: str, r: dict | None) -> str:
    if r is None:
        return f"| {label} | no data | | | |"
    halt = "n/a" if r["halt_triggered"] is None else ("yes" if r["halt_triggered"] else "no")
    halted = "n/a" if r["halted_days"] is None else str(r["halted_days"])
    return f"| {label} | {_fall(r['max_drawdown'])} | {halt} | {halted} | {_pct(r['final_net_return'])} |"


def _portfolio_table(name: str, p: dict) -> list[str]:
    rnd = p["random_5"]

    if p["first_day"] is None:
        return [
            f"**{SET_NAMES[name]}**: no prices after these sessions yet, so no account can be replayed.",
            "",
        ]

    def spread(key: str) -> str:
        s = rnd[key]
        if s["median"] is None:
            return "n/a"
        if key == "halted_days":
            return f"{s['median']:.0f} ({s['p5']:.0f} to {s['p95']:.0f})"
        if key == "max_drawdown":
            return f"{_fall(s['median'])} ({_fall(s['p5'])} to {_fall(s['p95'])})"
        return f"{_pct(s['median'])} ({_pct(s['p5'])} to {_pct(s['p95'])})"

    return [
        f"**{SET_NAMES[name]}**, account of ₹{p['capital']:,.0f}, {p['first_day']} to {p['last_day']}:",
        "",
        "| Account | Worst fall | 15% halt triggered | Days halted | Final net return |",
        "|---|---|---|---|---|",
        _risk_row(SET_NAMES[name], p["candidate"]),
        f"| Random 5, {rnd['runs']} accounts: median (5th-95th) | {spread('max_drawdown')} | "
        f"in {_share(rnd['halt_triggered_share'])} of accounts | {spread('halted_days')} "
        f"| {spread('final_net_return')} |",
        _risk_row("Momentum 5", p["momentum_5"]),
        _risk_row("NIFTY bought and held", p["nifty_hold"]),
        _risk_row("Cash", p["cash"]),
        "",
    ]


def _practice_lines(pr: dict) -> list[str]:
    b, g, grades = pr["baselines"], pr["forward_gate"], pr["data"]["stored_grades"]
    lines = [
        f"Forward gate over the whole trial ({g['cohort_from']} to {g['cohort_to']}; a working-order check, "
        f"not proof): **{g['word']}**. {g['why']}",
        "",
    ]
    if not b["available"]:
        return [*lines, b["why"], ""]
    if not b["sessions"]:
        return [*lines, "No live nightly brain runs in the practice stage in this month.", ""]
    trade = grades["trade"]
    lines += [
        f"{b['sessions']} sessions. Stored M09 grades of TRADE ideas (gross, no costs): "
        + (
            f"{trade['count']} finished, average {_pct(trade['avg_gross_return'])}."
            if trade["available"]
            else trade["why"]
        ),
        "",
        "### Trade level (matched)",
        "",
    ]
    for name in CANDIDATE_SETS:
        lines += _trade_table(name, b["trade_level"][name])
    lines += [
        "*NIFTY, matched holding period: " + baselines.NIFTY_MATCHED_NOTE,
        "",
        "### Portfolio level (equal capital, each account on its own rules)",
        "",
    ]
    for name in CANDIDATE_SETS:
        lines += _portfolio_table(name, b["portfolio_level"][name])
    return [*lines, "NIFTY bought and held: " + baselines.NIFTY_HOLD_NOTE, ""]


def _bps(x: float | None) -> str:
    """Basis points shown as a percentage: plainer for the owner (100 bps = 1%)."""
    return "-" if x is None else f"{x / 100:+.2f}%"


def _fill_lines(summary: dict[str, Any]) -> list[str]:
    lines = [
        "## 4. How realistic were the fill prices?",
        "",
        "Every filled order this month against what the market really offered: in market hours the day's "
        "typical price (and whether the price was inside the day's low-high range at all), outside market "
        "hours the next session's open. **Better by** above zero means the recorded price flatters the "
        "result. Paper and real orders are shown apart.",
        "",
    ]
    if not summary:
        return [*lines, "No filled orders this month."]
    lines += [
        "| Orders | When | Fills | Better by (average) | Better by (median) | Outside the day's range "
        "| No price data |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode, parts in summary.items():
        for when, label in (("in_hours", "in market hours"), ("after_hours", "outside market hours")):
            st = parts[when]
            if not st["fills"]:
                continue
            outside = st["outside_day_range"] if when == "in_hours" else "-"
            lines.append(
                f"| {mode} | {label} | {st['fills']} | {_bps(st['avg_better_by_bps'])} | "
                f"{_bps(st['median_better_by_bps'])} | {outside} | {st['no_price_data']} |"
            )
    return lines


def _spot_lines(sc: dict[str, Any]) -> list[str]:
    lines = [
        "## 5. Are the brain's reasons true? (spot check)",
        "",
        "Decisions picked at random from this month's nightly runs (the same ones every time), with every "
        "reason that makes a claim about prices recomputed from the raw daily prices the run could see.",
        "",
    ]
    if not sc.get("decisions"):
        return [*lines, "No nightly decisions this month."]
    lines += [
        f"- Decisions checked: {sc['decisions']}; all their price claims true: {sc['decisions_all_true']}.",
        f"- Price claims checked: {sc['claims_checked']}; true: {sc['claims_true']}.",
        f"- Reasons with no price claim (scores, similar cases, news): {sc['reasons_not_checkable']}.",
    ]
    if sc["mismatches"]:
        lines += ["", "| Stock | Day | Claim | What the prices say |", "|---|---|---|---|"]
        lines += [f"| {m['symbol']} | {m['day']} | {m['claim']} | {m['detail']} |" for m in sc["mismatches"]]
    else:
        lines.append("- No mismatches.")
    return lines


def plain_report(pack: dict[str, Any]) -> str:
    s = pack["sections"]
    pr, pa, bt = s["practice"], s["paper"], s["backtest"]
    lines = [
        f"# Evidence pack — {pack['month']}",
        "",
        f"{pack['from']} to {pack['to']}"
        + ("" if pack["complete_month"] else " (month not over yet)")
        + f". Definitions: `{pack['defs']}`. Generated {pack['generated_at']}.",
        "",
        f"**{pack['label']}.** The three sections below are different kinds of evidence and are never added "
        "together.",
        "",
        f"## 1. {pr['category_name']}",
        "",
        *_practice_lines(pr),
    ]
    d = pa["data"]
    lines += [
        f"## 2. {pa['category_name']}",
        "",
        "Same figures as the Performance screen (`/portfolio/summary`), "
        f"measured since {d.get('measured_since')}: the whole trial so far, not only this month.",
        "",
        "| Figure | Value |",
        "|---|---|",
        f"| Starting capital | ₹{d['starting_capital']:,.0f} |",
        f"| Total value | ₹{d['total_value']:,.0f} |",
        f"| Return | {_pct(d['total_return_pct'])} |",
        f"| Worst fall (max drawdown) | {_fall(d['max_drawdown_pct'])} |",
        f"| Current fall from peak | {_fall(d['current_drawdown_pct'])} |",
        f"| Closed trades | {d['total_trades']} |",
        f"| Win rate | {_share(d['win_rate'] if d['total_trades'] else None)} |",
        f"| Charges paid on closed trades | ₹{d['total_charges']:,.0f} |",
        f"| Open positions | {d['open_positions']} |",
        "",
        f"## 3. {bt['category_name']}",
        "",
        "| Claim | Answer | Why |",
        "|---|---|---|",
    ]
    for c in bt["data"]["claims"]:
        why = "; ".join(c["problems"]) or c["independence_note"] or "-"
        lines.append(f"| {c['label']} | **{c['word']}** | {why} |")
    lines += ["", *_fill_lines(pack.get("fills") or {})]
    lines += ["", *_spot_lines(pack.get("spot_check") or {})]
    lines += [
        "",
        "## Read this before drawing a conclusion",
        "- A month is a small sample. No row here is a verdict; verdicts come only from a frozen protocol.",
        "- Ideas from the same day share one market, so a few good or bad weeks can decide a month.",
        "- Ideas from the last sessions of the month are still open; the next pack scores them.",
        "- Practice ideas were never bought. Paper figures are the version 1 account's simulated trades.",
        "- The pool is the stocks the brain looked at each day (today's watchlist), "
        "so dropped stocks are missing.",
    ]
    return "\n".join(lines) + "\n"
