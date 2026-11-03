"""Historical-price change detector (REPORT ONLY).

Finds two things and tells the owner about them. It never changes any data:

1. A *restatement*: the data vendor (Kite) now returns different old prices than
   we stored (split/bonus restatement, demerger adjustment). Found by comparing
   stored bars with freshly fetched bars over a window.
2. A *price signature*: a suspicious step in stored prices alone (possible
   unadjusted split, or a very large move that needs one announcement lookup).

Hard rules: no database imports, no writes to candle tables, no refetch queue.
The only side effect is returning a report, or (only if the caller passes a
path) appending JSON lines to a file. The online fetch is an injected callable.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Callable, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

RESTATEMENT_THRESHOLD = 0.005  # 0.5% close difference
SCALE_TOLERANCE = 0.002  # ratio constant within 0.2%
OVERLAP_DAYS = 10
OLDER_WINDOW_DAYS = 260
ROTATION_CYCLE = 20  # weekday runs; every stock checked once per cycle
FIELDS = ("open", "high", "low", "close", "volume")

SIGNATURE_MOVE = 0.07
LARGE_MOVE = 0.20
LOW_VOLUME_MULT = 3.0
RATIO_TOL = 0.01
# (numerator, denominator) price ratios close/prev_close that look like splits.
SPLIT_RATIOS = (
    (1, 2),
    (1, 3),
    (1, 4),
    (1, 5),
    (1, 10),
    (2, 3),
    (3, 4),
    (2, 1),
    (3, 1),
    (4, 1),
    (5, 1),
    (10, 1),
    (3, 2),
    (4, 3),
)

ACTION_LOOKUP = "Look up the exchange announcement for this stock and date; do not bulk-scrape NSE."
ACTION_REFETCH = "Consider a refetch of that symbol (owner decision); this tool changes nothing."


# --------------------------------------------------------------------------- bars


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=IST)).astimezone(IST).date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()
        try:
            if len(text) == 10:
                return date.fromisoformat(text)
            return _to_date(datetime.fromisoformat(text.replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def normalize_bars(bars: Iterable[Mapping[str, Any]] | None) -> dict[date, dict[str, float]]:
    """Turn raw bar dicts into {IST date: {open,high,low,close,volume}}. Skips bad rows."""
    out: dict[date, dict[str, float]] = {}
    for bar in bars or []:
        try:
            d = _to_date(bar.get("date", bar.get("ts")))
            if d is None:
                continue
            out[d] = {f: float(bar[f]) for f in FIELDS}
        except (KeyError, TypeError, ValueError, AttributeError):
            continue
    return out


# ------------------------------------------------------------------ (a) comparison


@dataclass(frozen=True)
class DayDiff:
    date: date
    changes: dict[str, tuple[float, float]]  # field -> (stored, fetched)
    close_ratio: float | None  # fetched / stored close


@dataclass(frozen=True)
class ComparisonResult:
    symbol: str
    window_start: date | None
    window_end: date | None
    compared_days: int
    diffs: tuple[DayDiff, ...]
    missing_in_fetched: tuple[date, ...]
    extra_in_fetched: tuple[date, ...]
    restatement: bool
    pattern: str  # empty | unchanged | uniform_scale | scattered | missing_or_extra_dates
    factor: float | None = None
    change_date: date | None = None  # first day the ratio is back to 1 (the ex-date)
    note: str = ""


def _close_ratio(stored: float, fetched: float) -> float | None:
    return fetched / stored if stored else None


def compare_windows(
    symbol: str,
    stored: Iterable[Mapping[str, Any]] | None,
    fetched: Iterable[Mapping[str, Any]] | None,
    *,
    threshold: float = RESTATEMENT_THRESHOLD,
    scale_tolerance: float = SCALE_TOLERANCE,
) -> ComparisonResult:
    """Compare stored vs freshly fetched bars. Never raises on empty/partial data."""
    s = normalize_bars(stored)
    f = normalize_bars(fetched)
    if not s or not f:
        return ComparisonResult(
            symbol,
            None,
            None,
            0,
            (),
            tuple(sorted(s)) if f == {} and s else (),
            tuple(sorted(f)) if s == {} and f else (),
            False,
            "empty",
            note="Nothing to compare (stored or fetched data is empty).",
        )
    # Only judge dates the fetch window covers; stored bars outside it are not "missing".
    lo, hi = min(f), max(f)
    s_in = {d: v for d, v in s.items() if lo <= d <= hi}
    common = sorted(set(s_in) & set(f))
    missing = tuple(sorted(set(s_in) - set(f)))
    extra = tuple(sorted(set(f) - set(s_in)))
    diffs: list[DayDiff] = []
    for d in common:
        changes = {
            k: (s_in[d][k], f[d][k])
            for k in FIELDS
            if abs(f[d][k] - s_in[d][k]) > 1e-9 * max(1.0, abs(s_in[d][k]))
        }
        if changes:
            diffs.append(DayDiff(d, changes, _close_ratio(s_in[d]["close"], f[d]["close"])))
    start, end = (common[0], common[-1]) if common else (lo, hi)

    ratios = {d: _close_ratio(s_in[d]["close"], f[d]["close"]) for d in common}
    big = [d for d in common if ratios[d] is not None and abs(ratios[d] - 1) > threshold]
    restatement = bool(big)
    pattern, factor, change_date, note = "unchanged", None, None, "Stored and fetched prices agree."

    if restatement:
        vals = [ratios[d] for d in big]
        med = statistics.median(vals)
        constant = all(abs(v / med - 1) <= scale_tolerance for v in vals)
        # Old bars on the old scale: contiguous block from the window start,
        # back to ratio 1 after the ex-date.
        contiguous = big == common[: len(big)]
        later = common[len(big) :]
        back_to_one = all(abs(ratios[d] - 1) <= threshold for d in later)
        if constant and contiguous and back_to_one:
            pattern, factor = "uniform_scale", med
            change_date = later[0] if later else None
            note = f"Old prices are on a different scale: fetched/stored = {med:.4f} " + (
                f"before {change_date}, 1.0 from {change_date}."
                if change_date
                else "for the whole window (the change date is older than the window)."
            )
        else:
            pattern = "scattered"
            note = f"{len(big)} close(s) differ by more than {threshold:.1%} with no single scale factor."
    elif missing or extra:
        pattern = "missing_or_extra_dates"
        note = "Closes agree, but the date lists differ."
    if missing or extra:
        note += f" Missing in fetched: {len(missing)}, extra in fetched: {len(extra)}."
        if pattern == "unchanged":
            pattern = "missing_or_extra_dates"
    elif not restatement and diffs:
        note = "Closes agree within threshold; small open/high/low/volume differences only."
    return ComparisonResult(
        symbol,
        start,
        end,
        len(common),
        tuple(diffs),
        missing,
        extra,
        restatement,
        pattern,
        factor,
        change_date,
        note,
    )


# ------------------------------------------------------------------ (b) schedule


def overlap_window(trading_days: Sequence[date], n: int = OVERLAP_DAYS) -> tuple[date, date] | None:
    """Most recent n trading days (every stock, every run)."""
    days = sorted(trading_days)[-n:]
    return (days[0], days[-1]) if days else None


def older_window(trading_days: Sequence[date], n: int = OLDER_WINDOW_DAYS) -> tuple[date, date] | None:
    return overlap_window(trading_days, n)


def _weekday_index(d: date) -> int:
    """Count of weekdays since a fixed origin; consecutive weekdays give consecutive ints."""
    o = d.toordinal()
    return (o // 7) * 5 + min(o % 7, 5)


def _symbol_hash(symbol: str) -> int:
    return int.from_bytes(hashlib.sha256(symbol.encode()).digest()[:8], "big")


def rotating_slice(symbols: Iterable[str], on_date: date, cycle: int = ROTATION_CYCLE) -> list[str]:
    """Stocks to deep-check on `on_date`. Deterministic; each symbol appears once per cycle.

    slot = (hash(symbol) + weekday_index(date)) mod cycle == 0. Exchange
    holidays skip a slot, so a stock can wait a few days longer than the cycle.
    """
    cycle = max(1, cycle)
    idx = _weekday_index(on_date)
    return sorted(s for s in set(symbols) if (_symbol_hash(s) + idx) % cycle == 0)


# ------------------------------------------------------------ (c) passive signature


@dataclass(frozen=True)
class SignatureFinding:
    symbol: str
    date: date
    kind: str  # price_step_low_volume | split_ratio_signature | large_move
    move_pct: float
    price_ratio: float
    volume_multiple: float | None
    factor: str | None = None


def _median_prior_volume(vols: list[float], i: int, n: int = 20) -> float | None:
    prior = vols[max(0, i - n) : i]
    return statistics.median(prior) if len(prior) >= 5 else None


def detect_signatures(
    symbol: str,
    stored: Iterable[Mapping[str, Any]] | None,
    *,
    exclude: Iterable[date] = (),
    step_move: float = SIGNATURE_MOVE,
    large_move: float = LARGE_MOVE,
) -> list[SignatureFinding]:
    """Stored-data-only checks. `exclude` = dates already corrected or verified."""
    bars = normalize_bars(stored)
    days = sorted(bars)
    skip = set(exclude)
    vols = [bars[d]["volume"] for d in days]
    out: list[SignatureFinding] = []
    for i in range(1, len(days)):
        d = days[i]
        if d in skip:
            continue
        prev, cur = bars[days[i - 1]]["close"], bars[d]["close"]
        if prev <= 0 or cur <= 0:
            continue
        ratio = cur / prev
        move = ratio - 1
        med = _median_prior_volume(vols, i)
        vmult = (vols[i] / med) if med else None
        if abs(move) >= step_move and vmult is not None and vmult < LOW_VOLUME_MULT:
            out.append(SignatureFinding(symbol, d, "price_step_low_volume", move, ratio, vmult))
        if vmult is not None:
            for a, b in SPLIT_RATIOS:
                target = a / b
                if abs(ratio / target - 1) <= RATIO_TOL:
                    expected_v = 1 / target  # volume should move the opposite way
                    if abs(vmult / expected_v - 1) <= 0.35:
                        out.append(
                            SignatureFinding(
                                symbol, d, "split_ratio_signature", move, ratio, vmult, f"{a}/{b}"
                            )
                        )
                    break
        if abs(move) >= large_move:
            out.append(SignatureFinding(symbol, d, "large_move", move, ratio, vmult))
    return out


# ------------------------------------------------------------------ (d) report


@dataclass
class DetectorReport:
    generated_for: str
    symbols_checked: int
    restatements: list[dict] = field(default_factory=list)
    other_differences: list[dict] = field(default_factory=list)
    signatures: list[dict] = field(default_factory=list)
    text: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _restatement_row(r: ComparisonResult) -> dict:
    size = (
        (r.factor - 1)
        if r.factor
        else (max((abs(x.close_ratio - 1) for x in r.diffs if x.close_ratio), default=0.0))
    )
    return {
        "symbol": r.symbol,
        "date": (r.change_date or r.window_end or "").__str__(),
        "kind": f"restatement/{r.pattern}",
        "factor": r.factor,
        "size_pct": round(size * 100, 2),
        "window": f"{r.window_start}..{r.window_end}",
        "differing_days": len(r.diffs),
        "note": r.note,
        "action": ACTION_REFETCH + " " + ACTION_LOOKUP,
    }


def _signature_row(s: SignatureFinding) -> dict:
    kind = {
        "large_move": "large move, needs a single-announcement lookup",
        "price_step_low_volume": "price step without a volume spike (possible unadjusted event)",
        "split_ratio_signature": f"split-like ratio {s.factor} with opposite volume step",
    }[s.kind]
    return {
        "symbol": s.symbol,
        "date": s.date.isoformat(),
        "kind": kind,
        "factor": s.factor,
        "size_pct": round(s.move_pct * 100, 2),
        "volume_multiple": None if s.volume_multiple is None else round(s.volume_multiple, 2),
        "action": ACTION_LOOKUP if s.kind == "large_move" else ACTION_LOOKUP + " " + ACTION_REFETCH,
    }


def build_report(
    label: str,
    comparisons: Sequence[ComparisonResult] = (),
    signatures: Sequence[SignatureFinding] = (),
    symbols_checked: int | None = None,
) -> DetectorReport:
    rep = DetectorReport(
        label,
        symbols_checked
        if symbols_checked is not None
        else len({c.symbol for c in comparisons} | {s.symbol for s in signatures}),
    )
    for c in comparisons:
        if c.restatement:
            rep.restatements.append(_restatement_row(c))
        elif c.pattern in ("missing_or_extra_dates",):
            rep.other_differences.append(
                {
                    "symbol": c.symbol,
                    "date": str(c.window_end or ""),
                    "kind": c.pattern,
                    "note": c.note,
                    "action": ACTION_LOOKUP,
                }
            )
    rep.signatures = [_signature_row(s) for s in signatures]
    lines = [
        f"Price change check: {label}",
        f"Stocks checked: {rep.symbols_checked}",
        "This report only reports. No data was changed and nothing was queued.",
        "",
    ]
    if not (rep.restatements or rep.other_differences or rep.signatures):
        lines.append("No differences or suspicious steps found.")
    for title, rows in (
        ("Restated history (vendor now shows different old prices)", rep.restatements),
        ("Missing or extra dates", rep.other_differences),
        ("Suspicious steps in stored prices", rep.signatures),
    ):
        if rows:
            lines.append(f"{title}: {len(rows)}")
            for r in rows:
                fac = (
                    f", factor {r['factor']:.4f}"
                    if r.get("factor") and isinstance(r["factor"], float)
                    else (f", ratio {r['factor']}" if r.get("factor") else "")
                )
                size = f", size {r['size_pct']}%" if "size_pct" in r else ""
                lines.append(f"  - {r['symbol']} {r['date']}: {r['kind']}{fac}{size}")
                if r.get("note"):
                    lines.append(f"      {r['note']}")
                lines.append(f"      What to do: {r['action']}")
            lines.append("")
    rep.text = "\n".join(lines).rstrip() + "\n"
    return rep


def append_jsonl(report: DetectorReport, path: str) -> None:
    """Optional audit log (caller passes a gitignored path under backend/data/)."""
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(report.to_dict(), default=str) + "\n")


# ------------------------------------------------------------------ (f) job


Fetcher = Callable[[str, date, date], Sequence[Mapping[str, Any]]]
Loader = Callable[[str, date, date], Sequence[Mapping[str, Any]]]


def run_detection_job(
    symbols: Sequence[str],
    run_date: date,
    trading_days: Sequence[date],
    load_stored: Loader,
    fetch_fresh: Fetcher,
    *,
    known_events: Mapping[str, Iterable[date]] | None = None,
    overlap_n: int = OVERLAP_DAYS,
    older_n: int = OLDER_WINDOW_DAYS,
    cycle: int = ROTATION_CYCLE,
    threshold: float = RESTATEMENT_THRESHOLD,
) -> DetectorReport:
    """Nightly job body. NOT registered in workers/scheduler.py (needs owner approval).

    `load_stored` is a read-only loader; `fetch_fresh` is the injected vendor
    call. Per-symbol failures are skipped, never raised, and nothing is written.
    """
    comps: list[ComparisonResult] = []
    sigs: list[SignatureFinding] = []
    deep = set(rotating_slice(symbols, run_date, cycle))
    recent, older = overlap_window(trading_days, overlap_n), older_window(trading_days, older_n)
    for sym in symbols:
        win = older if sym in deep else recent
        if win is None:
            continue
        try:
            stored = load_stored(sym, *win)
            fresh = fetch_fresh(sym, *win)
        except Exception:  # noqa: BLE001 - one bad symbol must not stop the run
            continue
        comps.append(compare_windows(sym, stored, fresh, threshold=threshold))
        if sym in deep:
            sigs += detect_signatures(sym, stored, exclude=(known_events or {}).get(sym, ()))
    return build_report(f"{run_date.isoformat()} ({len(deep)} deep)", comps, sigs, len(symbols))


# ------------------------------------------------------------------ (e) CLI


def _load_file(path: str) -> dict[str, list[dict]]:
    """JSON {symbol: [bars]} or CSV with symbol,date,open,high,low,close,volume."""
    if path.lower().endswith(".csv"):
        import csv

        out: dict[str, list[dict]] = {}
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out.setdefault(row["symbol"], []).append(row)
        return out
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run_offline(
    stored_path: str,
    fetched_path: str,
    *,
    signatures: bool = True,
    exclude: Mapping[str, Iterable[date]] | None = None,
    threshold: float = RESTATEMENT_THRESHOLD,
) -> DetectorReport:
    stored, fetched = _load_file(stored_path), _load_file(fetched_path)
    comps, sigs = [], []
    for sym in sorted(set(stored) | set(fetched)):
        comps.append(compare_windows(sym, stored.get(sym), fetched.get(sym), threshold=threshold))
        if signatures:
            sigs += detect_signatures(sym, stored.get(sym), exclude=(exclude or {}).get(sym, ()))
    return build_report("offline files", comps, sigs)


def run_online(
    symbols: Sequence[str],
    run_date: date,
    trading_days: Sequence[date],
    load_stored: Loader,
    fetch_fresh: Fetcher,
    **kw: Any,
) -> DetectorReport:
    """Online mode: the caller injects `fetch_fresh`.

    The one-line injection point (do NOT wire it here): pass a function that
    calls kite_broker.get_historical_data(token, from, to, "day", db) and
    returns bars with date/open/high/low/close/volume. Kite logins go to prod
    only, never local, so the real call is deliberately not implemented.
    """
    return run_detection_job(symbols, run_date, trading_days, load_stored, fetch_fresh, **kw)


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    p = argparse.ArgumentParser(description="Report historical price changes (changes nothing).")
    p.add_argument(
        "--offline",
        nargs=2,
        metavar=("STORED", "FETCHED"),
        required=True,
        help="two JSON/CSV files: stored bars and freshly fetched bars",
    )
    p.add_argument("--threshold", type=float, default=RESTATEMENT_THRESHOLD)
    p.add_argument("--no-signatures", action="store_true")
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="SYMBOL:YYYY-MM-DD",
        help="already corrected/verified day to skip (repeatable)",
    )
    p.add_argument("--log", help="optional JSONL file to append to (e.g. backend/data/price_change.jsonl)")
    args = p.parse_args(argv)
    ex: dict[str, list[date]] = {}
    for item in args.exclude:
        sym, _, day = item.partition(":")
        d = _to_date(day)
        if d:
            ex.setdefault(sym, []).append(d)
    rep = run_offline(*args.offline, signatures=not args.no_signatures, exclude=ex, threshold=args.threshold)
    print(rep.text)
    if args.log:
        append_jsonl(rep, args.log)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
