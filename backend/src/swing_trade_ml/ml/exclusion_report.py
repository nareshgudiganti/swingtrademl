"""Dataset eligibility and exclusion report (PREPARATION ONLY: reads, counts, writes a report; changes no data).

Which training rows would a model have to drop because a price window crosses a corporate-action price step?

Rule (all parameters are recorded in the report header):
  * An event sits on session index e (the first session on or after its date).
  * FEATURE window: a decision row at session p uses up to `feature_lookback` sessions of history, so every row
    with e <= p <= e + feature_lookback is excluded (its inputs straddle the step).
  * LABEL window: a row looks `horizon` sessions ahead, so every row with e - horizon <= p <= e - 1 is excluded
    (its outcome straddles the step).
  * Only events classified EXCLUDE are removed in the base policy (a mechanical, verified price step).
    Genuine market moves are RETAINED (owner decision). The "24-move rule" is only an anomaly screen: events it
    flagged and nobody verified stay PROVISIONAL (listed, counted in the sensitivity table, NOT removed in the
    base policy). Events awaiting a fresh-fetch comparison are PENDING and are kept in the base exclusion list,
    marked as such.
  * Structural rows that are not "excluded" but simply cannot be built: the first `min_history` sessions
    (warm-up) and the last `horizon` sessions (label not yet known).

Pure functions take dates and events. The CLI (`python -m swing_trade_ml.ml.exclusion_report`) reads dates from the
local database with SELECT only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

EXCLUDE = "EXCLUDE"  # verified mechanical price step: rows dropped in the base policy
RETAIN_GENUINE = "RETAIN_GENUINE"  # genuine market move (owner decision): rows kept
PROVISIONAL = "PROVISIONAL"  # flagged by the screen, not verified: kept in base, shown in sensitivity
PENDING = "PENDING_FRESH_FETCH"  # waiting for a fresh-fetch comparison: kept in the exclusion list, flagged

# Owner decisions (2026-11-04): these stocks' big moves are genuine and are retained.
OWNER_GENUINE_STOCKS = frozenset(
    {"ADANIENT", "GABRIEL", "PAYTM", "IREDA", "GALAXYSURF", "WHIRLPOOL", "POWERINDIA"}
)
# (stock, ISO date) pairs waiting for a fresh-fetch comparison.
PENDING_EVENTS = frozenset({("HINDUNILVR", "2025-12-05"), ("BAJAJELEC", "2023-09-14")})


@dataclass(frozen=True)
class Policy:
    horizon: int
    feature_lookback: int = 252
    min_history: int = 252
    include_provisional: bool = False  # sensitivity only


@dataclass(frozen=True)
class Event:
    event_id: str
    stock: str
    date: str
    event_type: str
    status: str
    in_49: bool
    mechanical: bool
    category: str


def classify(row: Mapping[str, str]) -> str:
    key = (row["stock"], row["date"])
    status = row.get("status", "")
    mech = str(row.get("mechanical_step", "")).strip().lower() == "true"
    if key in PENDING_EVENTS:
        return PENDING
    if mech:
        return EXCLUDE
    if status.upper().startswith("GENUINE") or row["stock"] in OWNER_GENUINE_STOCKS:
        return RETAIN_GENUINE
    return PROVISIONAL


def load_events(path: str | Path) -> list[Event]:
    out = []
    with open(path, encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            out.append(
                Event(
                    event_id=f"{row['stock']}:{row['date']}",
                    stock=row["stock"],
                    date=row["date"],
                    event_type=row["event_type"],
                    status=row["status"],
                    in_49=row["in_49"].strip().lower() == "yes",
                    mechanical=str(row["mechanical_step"]).strip().lower() == "true",
                    category=classify(row),
                )
            )
    return out


def _removed_categories(policy: Policy) -> set[str]:
    cats = {EXCLUDE, PENDING}
    if policy.include_provisional:
        cats.add(PROVISIONAL)
    return cats


def base_rows(dates: Sequence[date], policy: Policy) -> range:
    """Positions of sessions that can be built at all (enough history, label known)."""
    return range(policy.min_history, max(len(dates) - policy.horizon, policy.min_history))


def excluded_rows(
    dates_by_symbol: Mapping[str, Sequence[date]], events: Iterable[Event], policy: Policy
) -> list[dict]:
    """Every (row, event, window) hit. A row hit by several events/windows appears several times."""
    cats = _removed_categories(policy)
    by_stock: dict[str, list[Event]] = defaultdict(list)
    for ev in events:
        if ev.category in cats and ev.stock in dates_by_symbol:
            by_stock[ev.stock].append(ev)
    hits: list[dict] = []
    for sym, evs in by_stock.items():
        dates = list(dates_by_symbol[sym])
        arr = np.array([d.toordinal() for d in dates])
        rows = base_rows(dates, policy)
        for ev in evs:
            e = int(np.searchsorted(arr, date.fromisoformat(ev.date).toordinal(), side="left"))
            if e >= len(dates):
                continue
            feat = range(e, e + policy.feature_lookback + 1)
            lab = range(e - policy.horizon, e)
            for kind, rng in (("feature", feat), ("label", lab)):
                for p in rng:
                    if p in rows:
                        hits.append(
                            {
                                "symbol": sym,
                                "decision_date": dates[p].isoformat(),
                                "window_type": kind,
                                "reason": f"{ev.category}: {ev.event_type} ({ev.status[:40]})",
                                "event_id": ev.event_id,
                            }
                        )
    hits.sort(key=lambda h: (h["symbol"], h["decision_date"], h["window_type"], h["event_id"]))
    return hits


def retained_row_keys(
    dates_by_symbol: Mapping[str, Sequence[date]], hits: Sequence[dict], policy: Policy
) -> list[str]:
    bad = {(h["symbol"], h["decision_date"]) for h in hits}
    keys = []
    for sym in sorted(dates_by_symbol):
        dates = dates_by_symbol[sym]
        for p in base_rows(dates, policy):
            k = (sym, dates[p].isoformat())
            if k not in bad:
                keys.append(f"{k[0]}|{k[1]}")
    return keys


def dataset_hash(row_keys: Iterable[str]) -> str:
    """sha256 over the canonical, sorted 'SYMBOL|YYYY-MM-DD' row list, newline separated."""
    return hashlib.sha256("\n".join(sorted(row_keys)).encode("utf-8")).hexdigest()


def summarise(dates_by_symbol: Mapping[str, Sequence[date]], events: Sequence[Event], policy: Policy) -> dict:
    hits = excluded_rows(dates_by_symbol, events, policy)
    total = sum(len(base_rows(d, policy)) for d in dates_by_symbol.values())
    uniq = {(h["symbol"], h["decision_date"]) for h in hits}
    kept = retained_row_keys(dates_by_symbol, hits, policy)
    per_type = Counter()
    for k in {(h["symbol"], h["decision_date"], h["window_type"]) for h in hits}:
        per_type[k[2]] += 1
    return {
        "buildable_rows": total,
        "excluded_unique_rows": len(uniq),
        "excluded_by_window_type_row_counts": dict(per_type),
        "retained_rows": len(kept),
        "dataset_sha256": dataset_hash(kept),
        "excluded_list_sha256": dataset_hash(
            f"{h['symbol']}|{h['decision_date']}|{h['window_type']}|{h['event_id']}" for h in hits
        ),
        "hits": hits,
    }


def sensitivity(
    dates_by_symbol: Mapping[str, Sequence[date]],
    events: Sequence[Event],
    horizons: Sequence[int],
    lookbacks: Sequence[int] = (63, 126, 252),
) -> list[dict]:
    """Rows lost per policy variant. Never changes any data."""
    table = []
    for h in horizons:
        for lb in lookbacks:
            for prov in (False, True):
                pol = Policy(horizon=h, feature_lookback=lb, include_provisional=prov)
                s = summarise(dates_by_symbol, events, pol)
                table.append(
                    {
                        "horizon": h,
                        "feature_lookback": lb,
                        "removes": "verified+pending+provisional" if prov else "verified+pending (base)",
                        "buildable_rows": s["buildable_rows"],
                        "rows_lost": s["excluded_unique_rows"],
                        "share_lost_pct": round(
                            100.0 * s["excluded_unique_rows"] / max(s["buildable_rows"], 1), 2
                        ),
                    }
                )
    return table


def render_markdown(
    title: str,
    universe: Sequence[str],
    dates_by_symbol: Mapping[str, Sequence[date]],
    events: Sequence[Event],
    policy: Policy,
    events_path: str,
    horizons_for_table: Sequence[int],
) -> str:
    s = summarise(dates_by_symbol, events, policy)
    in_u = [e for e in events if e.stock in set(universe)]
    not_in = [
        e.event_id for e in events if e.event_id.split(":")[0] not in set(universe) and e.category == PENDING
    ]
    cnt = Counter(e.category for e in in_u)
    lines = [
        f"# {title}",
        "",
        "PREPARATION REPORT. No data was modified. Not signed evidence. Recomputes nothing from sealed trials.",
        "",
        "## Header: rule parameters",
        f"- Universe: {len(universe)} symbols; {len(dates_by_symbol)} had local daily candles.",
        f"- Label horizon (sessions): {policy.horizon}; feature lookback after an event (sessions): {policy.feature_lookback}",
        f"- Warm-up (rows skipped at the start): {policy.min_history} sessions; last {policy.horizon} sessions skipped (label unknown)",
        f"- Feature window excluded: decision rows p with e <= p <= e + {policy.feature_lookback}",
        f"- Label window excluded: decision rows p with e - {policy.horizon} <= p <= e - 1",
        f"- Events file: {events_path} ({len(events)} events; {len(in_u)} on universe stocks)",
        "- Base policy removes categories: EXCLUDE (verified mechanical step) and PENDING_FRESH_FETCH. "
        "RETAIN_GENUINE and PROVISIONAL are kept.",
        "- Owner-retained genuine moves: " + ", ".join(sorted(OWNER_GENUINE_STOCKS)),
        "- The 24-move rule is an anomaly screen only; unverified events stay PROVISIONAL.",
        "- Pending fresh-fetch comparison: " + ", ".join(f"{a} {b}" for a, b in sorted(PENDING_EVENTS)),
        ("- Pending but NOT in this universe (no effect here): " + ", ".join(not_in)) if not_in else "",
        "",
        "## Event classes on universe stocks",
        *(f"- {k}: {v}" for k, v in sorted(cnt.items())),
        "",
        "## Counts (base policy)",
        f"- Buildable rows (after warm-up and label cut-off): {s['buildable_rows']}",
        f"- Excluded unique rows: {s['excluded_unique_rows']}  (by window type: {s['excluded_by_window_type_row_counts']})",
        f"- Retained rows: {s['retained_rows']}",
        f"- Dataset hash (sha256 of sorted SYMBOL|DATE retained rows): {s['dataset_sha256']}",
        f"- Excluded-list hash: {s['excluded_list_sha256']}",
        "",
        "## Events driving exclusions or flagged",
        "| event id | category | type | status |",
        "|---|---|---|---|",
        *(
            f"| {e.event_id} | {e.category} | {e.event_type[:50]} | {e.status[:50]} |"
            for e in sorted(in_u, key=lambda x: (x.category, x.event_id))
            if e.category != RETAIN_GENUINE
        ),
        "",
        "## Sensitivity: rows lost",
        "| horizon | feature lookback | removes | buildable | lost | lost % |",
        "|---|---|---|---|---|---|",
        *(
            f"| {r['horizon']} | {r['feature_lookback']} | {r['removes']} | {r['buildable_rows']} | {r['rows_lost']} | {r['share_lost_pct']} |"
            for r in sensitivity(dates_by_symbol, events, horizons_for_table)
        ),
        "",
        "## Exact excluded rows (base policy)",
        "| symbol | decision date | window | reason | event id |",
        "|---|---|---|---|---|",
        *(
            f"| {h['symbol']} | {h['decision_date']} | {h['window_type']} | {h['reason']} | {h['event_id']} |"
            for h in s["hits"]
        ),
    ]
    return "\n".join(x for x in lines if x is not None)


def load_dates_readonly(symbols: Sequence[str]) -> dict[str, list[date]]:
    """Session dates (IST) of each stock from the local database. SELECT only."""
    from swing_trade_ml.ml.sector_features_loader import connect_readonly, load_stock_close

    out: dict[str, list[date]] = {}
    with connect_readonly(timeout=15) as conn:
        for s in symbols:
            ser = load_stock_close(conn, s)
            if len(ser):
                out[s] = [d.date() for d in ser.index]
    return out


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--events", required=True, help="events.csv (verified-event list)")
    ap.add_argument("--universe-json", required=True, help="JSON file holding the symbol list")
    ap.add_argument("--universe-key", default="used_49")
    ap.add_argument("--horizon", type=int, required=True, choices=[5, 10, 15])
    ap.add_argument("--feature-lookback", type=int, default=252)
    ap.add_argument("--title", default="Dataset eligibility and exclusion report")
    ap.add_argument("--out", required=True, help="markdown output path")
    ap.add_argument("--csv-out", help="optional CSV of the exact excluded rows")
    a = ap.parse_args(argv)

    universe = json.loads(Path(a.universe_json).read_text(encoding="utf-8"))[a.universe_key]
    events = load_events(a.events)
    dates = load_dates_readonly(universe)
    pol = Policy(horizon=a.horizon, feature_lookback=a.feature_lookback)
    md = render_markdown(a.title, universe, dates, events, pol, a.events, (5, 10))
    Path(a.out).write_text(md + "\n", encoding="utf-8")
    if a.csv_out:
        hits = excluded_rows(dates, events, pol)
        with open(a.csv_out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(
                fh, fieldnames=["symbol", "decision_date", "window_type", "reason", "event_id"]
            )
            w.writeheader()
            w.writerows(hits)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
