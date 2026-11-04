"""RESEARCH-ONLY path for the sector-only candidates SX5 (5-day) and SX10 (10-day).

NOT production. Nothing in the app imports this module (a test enforces it): not ml/predict.py, not the
workers, the strategies, the brain, the h05 lane or any scheduler. It reads the EXISTING feature code
(ml/features.py, imported read-only, never edited) and the ONE sector builder (ml/sector_features.py).

What it offers
  (a) `assemble_training_matrix`: existing FEATURE_COLUMNS + the three sector inputs, labelled, with the
      warm-up rows, the exclusion-report rows and the rows whose outcome was unknown at the data cut-off removed.
  (b) `train_research_candidate`: DRY-RUN by default. It REFUSES to fit anything unless an approval file for
      this exact configuration exists (SECTOR_RESEARCH_APPROVAL_FILE, or the `approval_path` argument). The
      model recipe is NOT defined here: the signed protocol supplies it as `fit_fn`. Output goes only under
      backend/data/research_models/ (gitignored); it refuses the production model directory and `ml_models`.
      Nothing is ever written to the database.
  (c) `assemble_asof_row`: the serving-side input for one stock on one decision day, built by the SAME
      assembler code path (same existing features, same sector builder), cut at the decision day.

The ASIANPAINT / BHARTIARTL mappings stay missing: `include_unverified` is not exposed here at all.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

import pandas as pd

from swing_trade_ml.ml import sector_features as sf
from swing_trade_ml.ml.features import FEATURE_COLUMNS, build_features, build_label  # read-only use
from swing_trade_ml.ml.sector_map import get_sector_index  # read-only use

RESEARCH_VERSION = "sector_research_v0"
SECTOR_COLUMNS: tuple[str, ...] = (
    sf.RESEARCH_FEATURE_NAMES
)  # three: sector_ret_20d_vs_nifty is redundant (C_56)
RESEARCH_COLUMNS: tuple[str, ...] = (*FEATURE_COLUMNS, *SECTOR_COLUMNS)
CANDIDATE_HORIZON = {"SX5": 5, "SX10": 10}
LABEL_KINDS = ("barrier", "endpoint")
# The label each candidate is defined with in its DRAFT protocol (docs/superpowers/specs/2026-11-05-sx*-DRAFT.md):
# SX5 = brain/five_day_train.endpoint_target (close 5 bars later >= +2%); SX10 = td-protocol-v1 barrier label
# (+6% before -3.5% within 10 bars; ten_day.TARGET / STOP / HORIZON_BARS). (label_kind, target, stop)
PROTOCOL_LABELS: dict[str, tuple[str, float, float | None]] = {
    "SX5": ("endpoint", 0.02, None),
    "SX10": ("barrier", 0.06, 0.035),
}
_ENDPOINT_PLACEHOLDER_STOP = (
    0.04  # five_day_train passes this to build_label; it only shapes the replaced column
)
APPROVAL_ENV = "SECTOR_RESEARCH_APPROVAL_FILE"
BACKEND_ROOT = Path(__file__).resolve().parents[3]
RESEARCH_ROOT = BACKEND_ROOT / "data" / "research_models"
_IST = "Asia/Kolkata"


class ResearchApprovalRequired(RuntimeError):
    """No valid approved-protocol token for this exact configuration: nothing is trained or written."""


class ResearchPathRefused(RuntimeError):
    """The output location is the production model directory (or `ml_models`)."""


@dataclass(frozen=True)
class DatasetSpec:
    candidate: str  # "SX5" or "SX10"
    symbols: tuple[str, ...]
    horizon_days: int  # 5 or 10
    target_return: float  # the label rule is part of the protocol: no default on purpose
    stop_return: float | None  # None for an endpoint label (there is no stop)
    data_cutoff: date  # rows whose outcome was not known by the end of this IST day are dropped
    exclusions: frozenset[tuple[str, str]] = field(default_factory=frozenset)  # (SYMBOL, YYYY-MM-DD)
    min_history: int = 252  # warm-up sessions skipped per stock (as in the exclusion report)
    # "barrier": +target before -stop within the horizon (ml/features.build_label). "endpoint": close `horizon`
    # bars later >= +target (brain/five_day_train.endpoint_target). Added 2026-11-05 for SX5; the default keeps
    # every earlier call site on the barrier rule it always used.
    label_kind: str = "barrier"

    def __post_init__(self):
        if self.label_kind not in LABEL_KINDS:
            raise ValueError(f"label_kind must be one of {list(LABEL_KINDS)}")
        if self.label_kind == "barrier" and self.stop_return is None:
            raise ValueError("a barrier label needs stop_return")
        if self.label_kind == "endpoint" and self.stop_return is not None:
            raise ValueError("an endpoint label has no stop: stop_return must be None")
        if self.candidate not in CANDIDATE_HORIZON:
            raise ValueError(f"candidate must be one of {sorted(CANDIDATE_HORIZON)}")
        if CANDIDATE_HORIZON[self.candidate] != self.horizon_days:
            raise ValueError(f"{self.candidate} is a {CANDIDATE_HORIZON[self.candidate]}-day candidate")

    def to_config(self) -> dict:
        d = asdict(self)
        d["symbols"] = sorted(self.symbols)
        d["exclusions"] = sorted(f"{s}|{x}" for s, x in self.exclusions)
        d["data_cutoff"] = self.data_cutoff.isoformat()
        d["sector_rule"] = "official NSE sector index; include_unverified=False"
        d["columns"] = list(RESEARCH_COLUMNS)
        d["version"] = RESEARCH_VERSION
        return d

    def config_sha256(self) -> str:
        return hashlib.sha256(json.dumps(self.to_config(), sort_keys=True).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ResearchInputs:
    """Everything the assembler reads, already loaded (pure data; the assembler touches no database)."""

    raw: Mapping[str, pd.DataFrame]  # symbol -> ts, open, high, low, close, volume (ts tz-aware)
    index_df: pd.DataFrame  # NIFTY 50 OHLCV
    index_frames: Mapping[str, pd.DataFrame]  # sector index name -> OHLCV
    vix_df: pd.DataFrame
    breadth_df: pd.DataFrame  # ts, breadth_pct_above_sma50, breadth_advance_pct
    source: str = (
        "unknown"  # "database" when loaded by load_inputs_readonly (real data); used by the harness guard
    )


def exclusions_from_hits(hits: Iterable[Mapping[str, str]]) -> frozenset[tuple[str, str]]:
    """From exclusion_report.excluded_rows() output."""
    return frozenset((h["symbol"], h["decision_date"]) for h in hits)


def load_exclusions_csv(path: str | Path) -> frozenset[tuple[str, str]]:
    with open(path, encoding="utf-8", newline="") as fh:
        return frozenset((r["symbol"], r["decision_date"]) for r in csv.DictReader(fh))


# ---------------------------------------------------------------------------------------------------------
def _ist_date(ts: pd.Series) -> pd.Series:
    return pd.to_datetime(ts, utc=True).dt.tz_convert(_IST).dt.tz_localize(None).dt.normalize()


def _cut(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    if df is None or len(df) == 0:
        return df
    return df[_ist_date(df["ts"]) <= as_of].reset_index(drop=True)


def _closes(inputs: ResearchInputs) -> tuple[pd.Series, dict[str, pd.Series]]:
    nifty = sf.close_series_from_candles(inputs.index_df[["ts", "close"]])
    secs = {k: sf.close_series_from_candles(v[["ts", "close"]]) for k, v in inputs.index_frames.items()}
    return nifty, secs


def _sector_frame(inputs: ResearchInputs, symbol: str) -> pd.DataFrame:
    name = get_sector_index(symbol)  # the EXISTING mapping, exactly as ml/dataset.py uses it
    return inputs.index_frames.get(name, inputs.index_df)


def _existing_features(raw: pd.DataFrame, inputs: ResearchInputs, symbol: str) -> pd.DataFrame:
    return build_features(
        raw, inputs.index_df, _sector_frame(inputs, symbol), inputs.vix_df, inputs.breadth_df
    )


def _attach_sector(
    frame: pd.DataFrame, raw: pd.DataFrame, nifty, secs, symbol: str, as_of=None
) -> pd.DataFrame:
    stock_close = sf.close_series_from_candles(raw[["ts", "close"]])
    sec = sf.build_sector_features(stock_close, nifty, secs, sf.resolve_sector_index(symbol), as_of=as_of)
    out = frame.copy()
    out["decision_date"] = _ist_date(out["ts"])
    for c in SECTOR_COLUMNS:
        out[c] = out["decision_date"].map(sec[c])
    return out


def _label(feat: pd.DataFrame, spec: DatasetSpec) -> pd.DataFrame:
    """The label of `spec.label_kind`. Endpoint = five_day_train.endpoint_target applied to build_label's
    forward_return (rows, features, label_end_ts identical to the barrier build; only `target` is replaced).
    A missing forward_return gives a missing target (the row is then dropped), never a silent 0."""
    if spec.label_kind == "barrier":
        return build_label(feat, spec.horizon_days, spec.target_return, spec.stop_return)
    lab = build_label(feat, spec.horizon_days, spec.target_return, _ENDPOINT_PLACEHOLDER_STOP)
    fr = lab["forward_return"]
    lab["target"] = (fr >= spec.target_return).astype("float64").where(fr.notna())
    return lab


def assemble_training_matrix(spec: DatasetSpec, inputs: ResearchInputs) -> pd.DataFrame:
    """(a) existing FEATURE_COLUMNS + three sector inputs + label, one row per (stock, decision day)."""
    nifty, secs = _closes(inputs)
    cutoff_end = pd.Timestamp(f"{spec.data_cutoff.isoformat()} 23:59", tz=_IST)
    frames = []
    for sym in sorted({s.upper() for s in spec.symbols}):
        raw = inputs.raw.get(sym)
        if raw is None or len(raw) < spec.min_history + spec.horizon_days + 1:
            continue
        raw = raw.sort_values("ts").reset_index(drop=True)
        feat = _existing_features(raw, inputs, sym)
        lab = _label(feat, spec)
        lab = lab.iloc[spec.min_history :]  # warm-up: first min_history sessions skipped
        lab = _attach_sector(lab, raw, nifty, secs, sym)
        lab["symbol"] = sym
        lab = lab.dropna(subset=[*RESEARCH_COLUMNS, "target"])
        keep = [
            *RESEARCH_COLUMNS,
            "target",
            "forward_return",
            "label_end_ts",
            "symbol",
            "ts",
            "decision_date",
        ]
        frames.append(lab[keep])
    if not frames:
        empty = pd.DataFrame(
            columns=[
                *RESEARCH_COLUMNS,
                "target",
                "forward_return",
                "label_end_ts",
                "symbol",
                "ts",
                "decision_date",
            ]
        )
        empty.attrs["inputs_source"] = inputs.source
        return empty
    m = pd.concat(frames, ignore_index=True)
    if spec.exclusions:
        key = m["symbol"] + "|" + m["decision_date"].dt.strftime("%Y-%m-%d")
        m = m[~key.isin({f"{s}|{d}" for s, d in spec.exclusions})]
    ends = pd.to_datetime(m["label_end_ts"], utc=True)
    m = m[ends <= cutoff_end]
    m = m.sort_values(["ts", "symbol"]).reset_index(drop=True)
    m["target"] = m["target"].astype(int)
    m.attrs["inputs_source"] = inputs.source
    return m


def _has_bar_on(df: pd.DataFrame | None, day: pd.Timestamp) -> bool:
    return df is not None and len(df) > 0 and _ist_date(df["ts"]).iloc[-1] == day


def assemble_asof_row(
    inputs: ResearchInputs, symbol: str, as_of: date | pd.Timestamp, *, now=None
) -> pd.DataFrame | None:
    """(c) The one input row for `symbol` on decision day `as_of`, using only data dated <= as_of.

    Availability rules (no guessing): the stock, NIFTY 50 and the stock's own sector index must each have a bar
    dated exactly `as_of` (a missing index bar would otherwise be a stale carry-forward). If a clock `now` is
    given, `as_of` must be a day whose bar can no longer change (`core.market_session.last_closed_trading_day`,
    15:40 IST on a trading day): a bar stored while the market is open may be partial.

    Same existing feature code and the same sector builder as the training assembler. Returns None when the
    stock has no bar that day or any input is missing (never a guess)."""
    day = pd.Timestamp(as_of).normalize()
    sym = symbol.upper()
    if now is not None:
        from swing_trade_ml.core.market_session import last_closed_trading_day

        if day.date() > last_closed_trading_day(now):
            return None
    raw = inputs.raw.get(sym)
    if raw is None or len(raw) == 0:
        return None
    raw = _cut(raw.sort_values("ts"), day)
    if len(raw) == 0 or _ist_date(raw["ts"]).iloc[-1] != day:
        return None
    if not _has_bar_on(_cut(inputs.index_df, day), day):
        return None
    sec_name = sf.resolve_sector_index(sym)
    if sec_name is not None and not _has_bar_on(_cut(inputs.index_frames.get(sec_name), day), day):
        return None
    cut = ResearchInputs(
        raw={sym: raw},
        index_df=_cut(inputs.index_df, day),
        index_frames={k: _cut(v, day) for k, v in inputs.index_frames.items()},
        vix_df=_cut(inputs.vix_df, day),
        breadth_df=inputs.breadth_df[_ist_date(inputs.breadth_df["ts"]) <= day].reset_index(drop=True),
    )
    feat = _existing_features(raw, cut, sym)
    nifty, secs = _closes(cut)
    feat = _attach_sector(feat.iloc[[-1]], raw, nifty, secs, sym, as_of=day)
    row = feat[list(RESEARCH_COLUMNS)]
    if row.isna().to_numpy().any():
        return None
    return row.reset_index(drop=True)


# ---------------------------------------------------------------------------------------------------------
def matrix_sha256(matrix: pd.DataFrame) -> str:
    h = hashlib.sha256()
    cols = [*RESEARCH_COLUMNS, "target", "symbol", "decision_date"]
    h.update(
        pd.util.hash_pandas_object(matrix[cols].astype({"decision_date": "string"}), index=False)
        .to_numpy()
        .tobytes()
    )
    return h.hexdigest()


def _approval_valid(spec: DatasetSpec, approval_path: str | Path | None) -> tuple[bool, str]:
    p = approval_path or os.environ.get(APPROVAL_ENV)
    if not p:
        return False, "no approval file given (set SECTOR_RESEARCH_APPROVAL_FILE or pass approval_path)"
    path = Path(p)
    if not path.is_file():
        return False, f"approval file does not exist: {path.name}"
    try:
        tok = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False, "approval file is not valid JSON"
    need = {"protocol_id", "approved_by", "candidate", "config_sha256"}
    if not need <= set(tok):
        return False, f"approval file lacks {sorted(need - set(tok))}"
    if tok["candidate"] != spec.candidate or tok["config_sha256"] != spec.config_sha256():
        return False, "approval does not match this candidate/configuration"
    return True, f"approved by {tok['approved_by']} under {tok['protocol_id']}"


def _check_out_root(out_root: Path) -> Path:
    resolved = out_root.resolve()
    from swing_trade_ml.core.config import settings

    prod = Path(settings.MODEL_ARTIFACT_DIR).resolve()
    if resolved == prod or prod in resolved.parents or "ml_models" in {p.lower() for p in resolved.parts}:
        raise ResearchPathRefused(f"{resolved} is a production model location")
    return resolved


def train_research_candidate(
    spec: DatasetSpec,
    matrix: pd.DataFrame,
    *,
    dry_run: bool = True,
    approval_path: str | Path | None = None,
    out_root: str | Path | None = None,
    fit_fn: Callable[[pd.DataFrame, pd.Series], bytes] | None = None,
) -> dict:
    """(b) DRY-RUN by default: returns the plan, writes nothing, fits nothing.

    A real run needs (1) dry_run=False, (2) an approval file naming this candidate and this exact
    configuration hash, (3) a `fit_fn` supplied by the signed protocol that returns the artifact bytes.
    The manifest and artifact go only under `out_root` (default backend/data/research_models/)."""
    plan = {
        "version": RESEARCH_VERSION,
        "candidate": spec.candidate,
        "config": spec.to_config(),
        "config_sha256": spec.config_sha256(),
        "data_cutoff": spec.data_cutoff.isoformat(),
        "rows": int(len(matrix)),
        "matrix_sha256": matrix_sha256(matrix) if len(matrix) else None,
        "dry_run": dry_run,
    }
    ok, why = _approval_valid(spec, approval_path)
    plan["approval"] = why
    root = _check_out_root(Path(out_root) if out_root else RESEARCH_ROOT)
    plan["would_write_under"] = str(root)
    if dry_run:
        return plan
    if not ok:
        raise ResearchApprovalRequired(why)
    if fit_fn is None:
        raise NotImplementedError("the model recipe comes from the signed protocol: pass fit_fn")
    if matrix.empty:
        raise ValueError("empty training matrix")
    artifact = fit_fn(matrix[list(RESEARCH_COLUMNS)], matrix["target"])
    art_sha = hashlib.sha256(artifact).hexdigest()
    run_dir = root / spec.candidate / f"{RESEARCH_VERSION}_{art_sha[:12]}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "artifact.bin").write_bytes(artifact)
    manifest = {**plan, "dry_run": False, "artifact_sha256": art_sha, "artifact_file": "artifact.bin"}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True), encoding="utf-8")
    return manifest


# ---------------------------------------------------------------------------------------------------------
def load_inputs_readonly(symbols: Iterable[str], conn=None) -> ResearchInputs:
    """Load OHLCV for the stocks, NIFTY 50, the sector indices and INDIA VIX with SELECT only; breadth over
    the watchlisted stocks exactly as ml/market_context.compute_breadth does."""
    from swing_trade_ml.ml.market_context import compute_breadth
    from swing_trade_ml.ml.sector_features_loader import connect_readonly

    sql = (
        "select c.ts, c.open, c.high, c.low, c.close, c.volume from candles c join instruments i on "
        "i.id = c.instrument_id where i.tradingsymbol = %s and i.segment = %s and c.interval = 'day' order by c.ts"
    )

    def load(c, sym, seg):
        rows = c.execute(sql, (sym, seg)).fetchall()
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        for col in ("open", "high", "low", "close", "volume"):
            df[col] = df[col].astype("float64")
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df

    own = conn is None
    c = conn or connect_readonly(timeout=15)
    try:
        raw = {s.upper(): load(c, s.upper(), "NSE") for s in symbols}
        nifty = load(c, "NIFTY 50", "INDICES")
        frames = {u: load(c, u, "INDICES") for u in sf.DEFAULT_RANK_UNIVERSE}
        vix = load(c, "INDIA VIX", "INDICES")
        watch = [
            r[0] for r in c.execute("select tradingsymbol from instruments where is_watchlisted").fetchall()
        ]
        closes = {}
        for s in watch:
            d = raw[s] if s in raw else load(c, s, "NSE")
            if len(d):
                closes[s] = d.set_index("ts")["close"]
        breadth = (
            compute_breadth(pd.DataFrame(closes).sort_index())
            if closes
            else pd.DataFrame(columns=["ts", "breadth_pct_above_sma50", "breadth_advance_pct"])
        )
    finally:
        if own:
            c.close()
    return ResearchInputs(
        raw=raw, index_df=nifty, index_frames=frames, vix_df=vix, breadth_df=breadth, source="database"
    )


__all__ = [
    "RESEARCH_COLUMNS",
    "DatasetSpec",
    "LABEL_KINDS",
    "PROTOCOL_LABELS",
    "ResearchInputs",
    "ResearchApprovalRequired",
    "ResearchPathRefused",
    "assemble_training_matrix",
    "assemble_asof_row",
    "train_research_candidate",
    "load_inputs_readonly",
    "load_exclusions_csv",
    "exclusions_from_hits",
]
