"""Free / Plus / Pro plans: the feature catalogue, the limits, and which
API routes each feature opens.

One catalogue drives three things — the backend gate (`api/deps.py`), the
owner's Plans Manager screen, and the frontend nav — so a feature can never
be "hidden in the menu but still served by the API".

The owner (a superuser, or a caller with the shared X-API-Key) is never
limited by a plan. Everything not listed in ROUTE_RULES is owner-only: the
real Zerodha holdings, capital, safety switches, orders, finance, settings
and every write. Those are the owner's personal account, not a product
feature, so the Plans Manager cannot hand them to a plan.
"""

from __future__ import annotations

from typing import Any

PLAN_KEYS: tuple[str, ...] = ("free", "plus", "pro")
DEFAULT_PLAN = "free"

# The one model Free users see. ml_swing strategies with no model_name in
# their params run this model too (see strategies/ml_swing.py defaults).
BASE_MODEL = "swing_classifier"

CAP_TIERS: tuple[str, ...] = ("large", "midcap", "smallcap")

# key -> label, plain-English description, group. Order is the order the
# Plans Manager shows them in.
FEATURES: dict[str, dict[str, str]] = {
    "picks": {
        "label": "Today's picks",
        "group": "Picks",
        "description": "BUY recommendations with entry, target, stop-loss and confidence.",
    },
    "all_models": {
        "label": "Picks from every model",
        "group": "Picks",
        "description": "Off = only the base Large Cap model's picks. On = every model's picks.",
    },
    "sizing": {
        "label": "Suggested quantity and ₹ amount",
        "group": "Picks",
        "description": "Splits a budget the user types in across today's picks.",
    },
    "regime": {
        "label": "Market mood",
        "group": "Market",
        "description": "Is the overall market rising, falling or choppy today.",
    },
    "track_record": {
        "label": "Past picks and results",
        "group": "Results",
        "description": "Every past pick and whether it hit its target or its stop-loss (Scan Results page).",
    },
    "bot_performance": {
        "label": "Bot's closed trades",
        "group": "Results",
        "description": "The bot's own closed trades and profit or loss (Reports page).",
    },
    "bot_portfolio": {
        "label": "Bot's open positions",
        "group": "Results",
        "description": "What the bot holds right now and its summary (Portfolio page).",
    },
    "model_lab": {
        "label": "Model Lab",
        "group": "Models",
        "description": "How accurate each model's confidence really is (Model Lab page).",
    },
}

# key -> label, description, kind ("int" | "tiers"), and what "no limit" is.
LIMITS: dict[str, dict[str, Any]] = {
    "picks_per_day": {
        "label": "Picks shown per day",
        "description": "Most picks shown at once. 0 = no limit.",
        "kind": "int",
    },
    "allowed_cap_tiers": {
        "label": "Company sizes shown",
        "description": "Which company sizes the picks and results may include.",
        "kind": "tiers",
    },
    "history_days": {
        "label": "Days of history",
        "description": "How far back past picks and trades go. 0 = no limit.",
        "kind": "int",
    },
}

DEFAULT_PLANS: dict[str, dict[str, Any]] = {
    "free": {
        "name": "Free",
        "features": {"picks": True, "regime": True, "track_record": True},
        "limits": {"picks_per_day": 5, "allowed_cap_tiers": ["large"], "history_days": 30},
    },
    "plus": {
        "name": "Plus",
        "features": {
            "picks": True,
            "all_models": True,
            "sizing": True,
            "regime": True,
            "track_record": True,
            "bot_performance": True,
        },
        "limits": {"picks_per_day": 0, "allowed_cap_tiers": list(CAP_TIERS), "history_days": 365},
    },
    "pro": {
        "name": "Pro",
        "features": dict.fromkeys(FEATURES, True),
        "limits": {"picks_per_day": 0, "allowed_cap_tiers": list(CAP_TIERS), "history_days": 0},
    },
}

# (method, route path as FastAPI declares it, without the /api/v1 prefix)
# -> (feature, required query values). A route not listed here is
# owner-only. Query constraints keep the bot's own book apart from the
# owner's real one on endpoints that serve both.
ROUTE_RULES: dict[tuple[str, str], tuple[str, dict[str, str]]] = {
    ("GET", "/signals/picks"): ("picks", {}),
    ("GET", "/signals/top-picks"): ("sizing", {}),
    ("GET", "/market-data/regime"): ("regime", {}),
    ("GET", "/signals/track-record"): ("track_record", {}),
    ("GET", "/portfolio/trades"): ("bot_performance", {"book": "bot"}),
    ("GET", "/portfolio/positions/detailed"): ("bot_portfolio", {"book": "bot"}),
    ("GET", "/portfolio/summary"): ("bot_portfolio", {"book": "bot"}),
    ("GET", "/signals/buy-list"): ("bot_portfolio", {}),
    ("GET", "/ml/models"): ("model_lab", {}),
    ("GET", "/ml/calibration"): ("model_lab", {}),
}


def clean_plan(features: dict[str, Any] | None, limits: dict[str, Any] | None) -> tuple[dict, dict]:
    """Validate and normalise a plan edit. Unknown keys are refused rather
    than stored, so a typo can't silently do nothing."""
    features = features or {}
    limits = limits or {}
    unknown = (set(features) - set(FEATURES)) | (set(limits) - set(LIMITS))
    if unknown:
        raise ValueError(f"Unknown plan keys: {', '.join(sorted(unknown))}")

    clean_features = {key: bool(features.get(key, False)) for key in FEATURES}
    clean_limits: dict[str, Any] = {}
    for key, spec in LIMITS.items():
        value = limits.get(key)
        if spec["kind"] == "int":
            number = int(value or 0)
            if number < 0:
                raise ValueError(f"{spec['label']} can't be negative")
            clean_limits[key] = number
        else:
            tiers = list(value) if value is not None else list(CAP_TIERS)
            bad = set(tiers) - set(CAP_TIERS)
            if bad:
                raise ValueError(f"Unknown company sizes: {', '.join(sorted(bad))}")
            clean_limits[key] = [t for t in CAP_TIERS if t in tiers]
    return clean_features, clean_limits


def default_plan(key: str) -> dict[str, Any]:
    spec = DEFAULT_PLANS[key]
    features, limits = clean_plan(spec["features"], spec["limits"])
    return {"key": key, "name": spec["name"], "features": features, "limits": limits}
