"""Symbol -> NSE sector index classification, for sector-relative-strength
features (features.py's sector_relative_strength_*/sector_trend_regime).

There is no fundamentals data source wired into this app yet (see
project_understanding.md §7), so sector membership can't be looked up live.
This is a hand-curated mapping instead, built from the tradingsymbols actually
used across the three cap-tier models (`swing_classifier`,
`_midcap`, `_smallcap` — see their `training_symbols` in `ml_models`) against
the NSE sector indices Kite's instrument dump actually carries (confirmed live
against a synced `instruments` table, not guessed). Coverage is deliberately
best-effort, not exhaustive: a handful of symbols with no clean sector fit
(diversified conglomerates, telecom — no dedicated NSE sector index exists for
telecom among Kite's INDICES segment) are left unmapped on purpose rather than
forced into a misleading bucket.

An unmapped symbol falls back to the benchmark index itself in
get_sector_index() — its "sector relative strength" is then always ~0 (neutral)
rather than crashing or silently using a wrong sector, and the fallback is
logged once so gaps stay visible instead of forgotten.
"""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.core.logging import get_logger

log = get_logger(__name__)

# Bucket -> exact Kite tradingsymbol (segment="INDICES"). Verified against a
# live synced instrument dump, September 2026.
_SECTOR_INDEX: dict[str, str] = {
    "BANK": "NIFTY BANK",
    "FIN_SERVICE": "NIFTY FIN SERVICE",
    "CAPITAL_MKT": "NIFTY CAPITAL MKT",
    "IT": "NIFTY IT",
    "AUTO": "NIFTY AUTO",
    "FMCG": "NIFTY FMCG",
    "CONSR_DURBL": "NIFTY CONSR DURBL",
    "CONSUMPTION": "NIFTY CONSUMPTION",
    "PHARMA": "NIFTY PHARMA",
    "HEALTHCARE": "NIFTY HEALTHCARE",
    "METAL": "NIFTY METAL",
    "ENERGY": "NIFTY ENERGY",
    "REALTY": "NIFTY REALTY",
    # Chemicals/fertilizers point at NIFTY COMMODITIES, not the more precise
    # NIFTY CHEMICALS: that index only starts 2025-11-23 (confirmed against a
    # real backfill — 198 bars vs ~1,240 for every other sector index), and
    # since training drops any row with a missing feature, using it would
    # silently discard ~4 of every 5 training rows for the ~20 symbols in this
    # bucket. A broader-but-complete peer group beats a precise-but-empty one.
    "CHEMICALS": "NIFTY COMMODITIES",
    "COMMODITIES": "NIFTY COMMODITIES",
    "INFRA": "NIFTY INFRA",
}

# Every sector index symbol the feature pipeline needs ingested, beyond the
# primary benchmark (settings.BENCHMARK_INDEX_SYMBOL) — see
# ingestion.backfill_context_indices(). INDIA VIX rides along here too since
# it needs the same "ensure instrument exists, never watchlisted" treatment.
CONTEXT_INDEX_SYMBOLS: list[str] = [*sorted(set(_SECTOR_INDEX.values())), "INDIA VIX"]

# tradingsymbol -> bucket key. Grouped by bucket for readability/auditing —
# flattened into SECTOR_INDEX_MAP below.
_SYMBOL_SECTOR: dict[str, str] = {
    # --- BANK -------------------------------------------------------------
    **dict.fromkeys(
        [
            "AXISBANK", "HDFCBANK", "ICICIBANK", "INDUSINDBK", "KOTAKBANK", "SBIN",
            "AUBANK", "BANDHANBNK", "BANKINDIA", "CANBK", "CUB", "FEDERALBNK",
            "IDBI", "IDFCFIRSTB", "INDIANB", "J&KBANK", "PNB", "RBLBANK",
            "UNIONBANK", "YESBANK",
        ],
        "BANK",
    ),
    # --- FIN_SERVICE (NBFC / insurance / lending, non-exchange) ------------
    **dict.fromkeys(
        [
            "BAJAJFINSV", "BAJFINANCE", "HDFCLIFE", "SBILIFE", "SHRIRAMFIN",
            "ABCAPITAL", "AAVAS", "CANFINHOME", "CHOLAFIN", "CREDITACC",
            "GICRE", "HDFCAMC", "HOMEFIRST", "HUDCO", "ICICIGI", "ICICIPRULI",
            "IIFL", "IREDA", "IRFC", "LICHSGFIN", "MANAPPURAM", "MFSL",
            "MUTHOOTFIN", "NIACL", "PAYTM", "PFC", "PNBHOUSING", "POLICYBZR",
            "POONAWALLA", "RECLTD", "SBICARD", "STARHEALTH", "SUNDARMFIN",
        ],
        "FIN_SERVICE",
    ),
    # --- CAPITAL_MKT (exchanges / brokers / RTAs / AMCs) -------------------
    **dict.fromkeys(
        [
            "5PAISA", "ANGELONE", "BSE", "CAMS", "CDSL", "GEOJITFSL", "IEX",
            "KFINTECH", "MCX", "MOTILALOFS", "NUVAMA",
        ],
        "CAPITAL_MKT",
    ),
    # --- IT -----------------------------------------------------------------
    **dict.fromkeys(
        [
            "HCLTECH", "INFY", "TCS", "TECHM", "WIPRO", "COFORGE", "CYIENT",
            "HAPPSTMNDS", "KPITTECH", "LATENTVIEW", "LTTS", "MPHASIS", "NAUKRI",
            "OFSS", "PERSISTENT", "ROUTE", "TATAELXSI",
        ],
        "IT",
    ),
    # --- AUTO (OEMs + auto components/ancillaries) -------------------------
    **dict.fromkeys(
        [
            "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO", "M&M", "MARUTI", "TVSMOTOR",
            "APOLLOTYRE", "ASHOKLEY", "BALKRISIND", "BHARATFORG", "BOSCHLTD",
            "ENDURANCE", "ESCORTS", "EXIDEIND", "FIEMIND", "GABRIEL", "JAMNAAUTO",
            "LUMAXTECH", "MINDACORP", "MOTHERSON", "MRF", "RAJRATAN", "RKFORGE",
            "SANDHAR", "SCHAEFFLER", "SKFINDIA", "SONACOMS", "SUBROS", "SUPRAJIT",
            "TIINDIA", "TIMKEN", "ZFCVINDIA",
        ],
        "AUTO",
    ),
    # --- FMCG ---------------------------------------------------------------
    **dict.fromkeys(
        [
            "BRITANNIA", "HINDUNILVR", "ITC", "NESTLEIND", "TATACONSUM",
            "COLPAL", "DABUR", "EMAMILTD", "GILLETTE", "GODREJCP", "JYOTHYLAB",
            "MARICO", "PGHH", "RADICO", "UBL", "VBL",
        ],
        "FMCG",
    ),
    # --- CONSR_DURBL (consumer electricals/electronics) --------------------
    **dict.fromkeys(
        [
            "HAVELLS", "VOLTAS", "CROMPTON", "VGUARD", "WHIRLPOOL", "SYMPHONY",
            "TTKPRESTIG", "BAJAJELEC", "ORIENTELEC", "DIXON", "BLUESTARCO",
        ],
        "CONSR_DURBL",
    ),
    # --- CONSUMPTION (discretionary retail/lifestyle/travel) ---------------
    **dict.fromkeys(
        [
            "TITAN", "TRENT", "PAGEIND", "METROBRAND", "VIPIND", "RELAXO",
            "SAFARI", "CAMPUS", "INDIGO", "IRCTC", "ABFRL",
        ],
        "CONSUMPTION",
    ),
    # --- PHARMA (manufacturers/biotech) -------------------------------------
    **dict.fromkeys(
        [
            "CIPLA", "DIVISLAB", "DRREDDY", "SUNPHARMA", "AJANTPHARM", "ALKEM",
            "AUROPHARMA", "BIOCON", "CAPLIPOINT", "ERIS", "GLAXO", "GLENMARK",
            "GRANULES", "IPCALAB", "JUBLPHARMA", "LAURUSLABS", "LUPIN",
            "NATCOPHARM", "NEULANDLAB", "POLYMED", "SANOFI", "SUPRIYA", "SUVEN",
            "TORNTPHARM", "ABBOTINDIA",
        ],
        "PHARMA",
    ),
    # --- HEALTHCARE (hospitals/diagnostics/health insurance) ---------------
    **dict.fromkeys(
        ["APOLLOHOSP", "FORTIS", "LALPATHLAB", "MAXHEALTH", "METROPOLIS"],
        "HEALTHCARE",
    ),
    # --- METAL ---------------------------------------------------------------
    **dict.fromkeys(
        [
            "HINDALCO", "JSWSTEEL", "TATASTEEL", "VEDL", "APLAPOLLO", "GRAPHITE",
            "HEG", "HINDCOPPER", "HINDZINC", "JINDALSTEL", "NATIONALUM", "NMDC",
            "RATNAMANI", "SAIL", "SHYAMMETL", "WELCORP",
        ],
        "METAL",
    ),
    # --- ENERGY (oil & gas, power generation/transmission) ------------------
    **dict.fromkeys(
        [
            "BPCL", "COALINDIA", "NTPC", "ONGC", "POWERGRID", "RELIANCE",
            "ADANIENSOL", "ADANIGREEN", "ADANIPOWER", "GAIL", "HINDPETRO",
            "NHPC", "PETRONET", "SJVN", "SUZLON", "TATAPOWER", "TORNTPOWER",
        ],
        "ENERGY",
    ),
    # --- REALTY ---------------------------------------------------------------
    **dict.fromkeys(
        ["DLF", "BRIGADE", "GODREJPROP", "OBEROIRLTY", "PHOENIXLTD", "PRESTIGE"],
        "REALTY",
    ),
    # --- CHEMICALS (specialty/agro chemicals, fertilizers) ------------------
    **dict.fromkeys(
        [
            "UPL", "GRASIM", "BASF", "BAYERCROP", "CHAMBLFERT", "CLEAN",
            "COROMANDEL", "DEEPAKFERT", "DEEPAKNTR", "DHANUKA", "FACT",
            "FINEORG", "GALAXYSURF", "GHCL", "GNFC", "NAVINFLUOR", "PIIND",
            "RALLIS", "RCF", "SRF", "TATACHEM",
        ],
        "CHEMICALS",
    ),
    # --- COMMODITIES (diversified trading/agri-commodity) -------------------
    **dict.fromkeys(["ADANIENT", "TRIVENI"], "COMMODITIES"),
    # --- INFRA (capital goods, construction materials, logistics, PSU infra) -
    **dict.fromkeys(
        [
            "LT", "ULTRACEMCO", "ADANIPORTS",
            "ABB", "AIAENG", "ASTRAL", "BHEL", "CARBORUNIV", "CGPOWER",
            "CUMMINSIND", "FINCABLES", "FINPIPE", "GRINDWELL", "GVT&D",
            "HONAUT", "KEC", "KEI", "KIRLOSBROS", "KIRLOSENG", "POLYCAB",
            "POWERINDIA", "SIEMENS", "SUPREMEIND", "THERMAX", "WABAG",
            "ACC", "AMBUJACEM", "CENTURYPLY", "CERA", "DALBHARAT", "GREENPANEL",
            "HEIDELBERG", "INDIACEM", "JKCEMENT", "JKLAKSHMI", "KAJARIACER",
            "NBCC", "ORIENTCEM", "RAMCOCEM", "SHREECEM", "SOMANYCERA",
            "ALLCARGO", "CONCOR", "GESHIP", "GMRAIRPORT", "IRCON", "RAILTEL",
            "RITES", "RVNL", "SCI", "TCIEXP", "TITAGARH", "TRITURBINE",
        ],
        "INFRA",
    ),
}

SECTOR_INDEX_MAP: dict[str, str] = {
    symbol: _SECTOR_INDEX[bucket] for symbol, bucket in _SYMBOL_SECTOR.items()
}

_warned_unmapped: set[str] = set()

# Bucket -> the plain name the owner reads in a rejection reason.
SECTOR_DISPLAY_NAMES: dict[str, str] = {
    "BANK": "Banking",
    "FIN_SERVICE": "Financial services",
    "CAPITAL_MKT": "Capital markets",
    "IT": "IT",
    "AUTO": "Auto",
    "FMCG": "Everyday consumer goods",
    "CONSR_DURBL": "Consumer durables",
    "CONSUMPTION": "Consumption",
    "PHARMA": "Pharma",
    "HEALTHCARE": "Healthcare",
    "METAL": "Metals",
    "ENERGY": "Energy",
    "REALTY": "Real estate",
    "CHEMICALS": "Chemicals",
    "COMMODITIES": "Commodities",
    "INFRA": "Infrastructure",
}


def get_sector_bucket(tradingsymbol: str) -> str | None:
    """The sector bucket this symbol belongs to, or None if it is unmapped.

    This — not get_sector_index() — is what portfolio-level sector limits
    group by, for two reasons that both silently mis-group positions
    otherwise:

    * get_sector_index() falls back to the benchmark for every unmapped
      symbol, so grouping by its result would lump every unmapped stock
      together into one pseudo-sector and block them against each other.
    * Two buckets share one index (CHEMICALS and COMMODITIES both point at
      NIFTY COMMODITIES — see _SECTOR_INDEX), so grouping by index would
      treat a chemicals stock and a commodities stock as the same sector.
    """
    return _SYMBOL_SECTOR.get(tradingsymbol.upper())


def sector_display_name(bucket: str) -> str:
    return SECTOR_DISPLAY_NAMES.get(bucket, bucket.replace("_", " ").title())


def get_sector_index(tradingsymbol: str) -> str:
    """The sector-index tradingsymbol to use as this symbol's peer group.

    Falls back to the primary benchmark for anything not in the map (a
    diversified conglomerate, telecom — no dedicated sector index exists for
    it — or a future watchlist addition this map hasn't caught up with yet):
    that makes sector_relative_strength_* neutral (~0) for it rather than
    raising or silently guessing wrong. Logged once per symbol so gaps are
    visible without spamming the log on every scan/training row.
    """
    symbol = tradingsymbol.upper()
    sector = SECTOR_INDEX_MAP.get(symbol)
    if sector is None:
        if symbol not in _warned_unmapped:
            _warned_unmapped.add(symbol)
            log.warning("sector_map.unmapped", symbol=symbol)
        return settings.BENCHMARK_INDEX_SYMBOL
    return sector
