"""Display-only: "What would change this?" for a brain idea that is not a TRADE.

For a WATCH, WAIT or AVOID idea, list the concrete conditions that would have to
change for the brain to say TRADE, read ONLY from what is stored on the decision
(its reasons, in order) and the run's banner. Nothing here is read by the brain,
the risk gate or any order path; it never changes a word, a threshold or a pick.

How it works: the brain stores no rule id on a decision, only the reason text each
rule wrote (rules.py, engine.py, constitution.py, the M07 risk gate and version 1's
risk.check_entry). Each pattern below recognises one of those texts and turns it
into a plain "what would have to change" line. tests/test_what_would_change.py
runs the real rules and pins every mapping, so a change to a rule's wording breaks
a test instead of silently showing the wrong line.

Honesty rules:
* A reason that cannot be mapped is never guessed: the first (deciding) reason, if
  unknown, shows "Not known from the stored record."
* The raw model score is a ranking, so the "score below the buy level" gap is shown
  as a position among the stocks the model scored that day, never as a % chance.
* Money amounts are shown only when the stored reason itself states them.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from swing_trade_ml.brain.constitution import BAD_PLAN, DATA_NOT_CHECKED, NO_RISK_GATE, NOT_APPROVED
from swing_trade_ml.brain.modules.m07_risk.module import DEFENSIVE_SIZE_FACTOR
from swing_trade_ml.services.limits import format_inr

UNKNOWN = "Not known from the stored record."
RISK_PREFIX = "Good idea, but the risk check said no: "
NO_DECISION = "No decision was produced for this stock."
EXPLAINED_WORDS = frozenset({"WATCH", "WAIT", "AVOID"})

_INR = r"-?₹[\d,]+"
#: M07's label for a buy that only the careful-market halving pushed below the minimum.
_HALF_SIZE = "half size in a defensive market"


def _rupees(text: str) -> float:
    return float(text.replace("₹", "").replace(",", ""))


_DATE = r"\d{2} [A-Z][a-z]{2}"


@dataclass(frozen=True, slots=True)
class ModelRank:
    """Where one stock's raw model score stood among the stocks the model scored in the run."""

    position: int  # 1 = highest score
    scored: int  # stocks the model scored
    above_buy_level: int  # how many of them were at or above the buy level


# --- the rank of a "score below the buy level" idea ---------------------------------

_BELOW_BUY_LEVEL = re.compile(r"^Model score \d+% is below the buy level \d+%\.$")


def is_below_buy_level(reasons: Iterable[str]) -> bool:
    return any(_BELOW_BUY_LEVEL.match(r) for r in reasons)


def model_ranks(decisions: Iterable[Any]) -> dict[Any, ModelRank]:
    """Position of each idea's raw model score among the ideas the model scored in one run,
    keyed by decision id. Only rows whose score is the raw model score ("model") are
    comparable; others get no rank."""
    scored = [
        d
        for d in decisions
        if d.kind == "idea" and d.confidence is not None and getattr(d, "score_source", None) == "model"
    ]
    scored.sort(key=lambda d: (-float(d.confidence), d.symbol))
    above = sum(1 for d in scored if not is_below_buy_level(d.reasons or ()))
    return {d.id: ModelRank(i + 1, len(scored), above) for i, d in enumerate(scored)}


def _ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _below_buy_level_line(rank: ModelRank | None) -> str:
    base = "The model would need to rank this stock higher (today it is below the buy level)."
    if rank is None:
        return base
    if rank.above_buy_level == 0:
        tail = "none were above the buy level."
    elif rank.above_buy_level == 1:
        tail = "only the top 1 was above the buy level."
    else:
        tail = f"only the top {rank.above_buy_level} were above the buy level."
    return f"{base} Today it ranks {_ordinal(rank.position)} of {rank.scored} stocks the model scored; {tail}"


# --- risk-check refusals (the text after RISK_PREFIX) --------------------------------


def _risk_line(why: str, banner_mode: str | None = None) -> tuple[str, str]:
    """(key, line) for one risk-check refusal. Unrecognised refusals fall back to the
    general limits line — the stored record says only that the limits said no.

    In a careful (DEFENSIVE) market M07 fits a buy to the free room first and halves it
    after, but still compares it with the full minimum, so the room needed is the minimum
    divided by the halving factor (about twice the minimum), not the minimum itself."""
    w = why.strip()
    if w.startswith("The market mode is NO NEW TRADES"):
        return "market_no_new_trades", "The market mode would need to leave NO NEW TRADES."
    m = re.match(r"^The market is defensive, so only the (\d+) strongest new ideas", w)
    if m:
        return "defensive_limit", (
            "The market mode would need to return to NORMAL, or this idea would need to be "
            f"among the {m.group(1)} strongest of the day."
        )
    if w.startswith("Every free position slot went to a stronger idea"):
        return "slots_taken_by_stronger", (
            "A position slot would need to be free for it (today the free slots went to stronger ideas)."
        )
    if (
        w.startswith("All position slots are already in use")
        or re.match(r"^You already hold \d+ positions", w)
        or re.search(r"already holds \d+ of its \d+ positions", w)
    ):
        return "slots_full", "A position slot would need to free up (today every slot is in use)."
    if w.startswith("A stronger idea in the same sector was approved first"):
        return "one_per_sector_run", (
            "No stronger idea from the same sector that day (at this account size the bot buys "
            "one stock per sector)."
        )
    m = re.match(r"^You already hold (\S+) in (.+?)\. At this account size", w)
    if m:
        return "one_per_sector_held", (
            f"The account would need to no longer hold {m.group(1)} in {m.group(2)} (at this "
            "account size the bot keeps to one stock per sector)."
        )
    m = re.match(r"^(.+?) would go to \d+% of your money — over your (\d+%) limit for one sector", w)
    if m:
        return "sector_cap", f"There would need to be room under your {m.group(2)} limit for {m.group(1)}."
    m = re.match(
        rf"^After stronger ideas in this run, the (.+?) leaves room for only ({_INR}) "
        rf"— below the ({_INR}) minimum",
        w,
    )
    if m:
        limit, today, minimum = m.group(1), m.group(2), m.group(3)
        if limit == _HALF_SIZE:
            return "defensive_half_size", (
                "The market would need to return to NORMAL: in a careful market each buy is cut to half "
                f"size, and half of this one ({today}) is below the {minimum} minimum."
            )
        if banner_mode == "DEFENSIVE":
            need = format_inr(_rupees(minimum) / DEFENSIVE_SIZE_FACTOR)
            return "room_after_stronger", (
                f"Needs about {need} of free room under the {limit}: in a careful market each buy is cut "
                f"to half size, so the room must be about twice the {minimum} minimum "
                f"(today a half-size buy would be {today})."
            )
        return "room_after_stronger", f"Needs about {minimum} of free room under the {limit} (today {today})."
    m = re.search(rf"leaving ({_INR}) — less than the ({_INR}) minimum position", w)
    if m:
        return "deployable_room", (
            f"Needs about {m.group(2)} of free room under the market-conditions limit (today {m.group(1)})."
        )
    m = re.match(
        rf"^The position would only be ({_INR}) \(limited by the (.+?)\) — below the ({_INR}) minimum", w
    )
    if m:
        return (
            "min_position",
            f"Needs about {m.group(3)} of room under the {m.group(2)} (today {m.group(1)}).",
        )
    m = re.match(rf"^Buying would leave less than ({_INR}) in cash.*You have ({_INR}) in cash", w)
    if m:
        return "cash_reserve", (
            f"Needs more free cash: buying must still leave {m.group(1)} in reserve "
            f"(today the cash is {m.group(2)})."
        )
    m = re.match(rf"^Not enough cash: buying costs ({_INR}) including charges, and you have ({_INR})", w)
    if m:
        return "cash", f"Needs about {m.group(1)} of free cash (today {m.group(2)})."
    m = re.match(r"^Your account is (\d+%) below its peak — past the (\d+%) safety limit", w)
    if m:
        return "drawdown", (
            f"The account would need to recover to less than {m.group(2)} below its peak "
            f"(today it is {m.group(1)} below)."
        )
    if w.startswith("New buys are paused"):
        return "owner_paused", "The owner would need to switch new buys back on."
    m = re.match(r"^Stopped out within the last (\d+) days", w)
    if m:
        return (
            "cooldown",
            f"The {m.group(1)}-day cooling-off after a recent stop-loss in this stock would need to end.",
        )
    if w.startswith("Position already open in this instrument"):
        return "already_open", "The account would need to not already hold this stock."
    if "on its extra-watch list" in w:
        return "exchange_watch_list", "Only if the exchange removes it from its watch list."
    if "is in delivery-only trading right now" in w:
        return "delivery_only", "Only once the stock is out of delivery-only trading."
    m = re.search(rf"announces its results on ({_DATE})", w)
    if m:
        return "results", f"After the results on {m.group(1)}."
    m = re.search(rf"has a corporate action on ({_DATE}) \((.+?)\) that resets its share price", w)
    if m:
        return "corporate_action", f"After the {m.group(2)} on {m.group(1)} has taken effect."
    m = re.match(rf"^One share costs ({_INR}) — at this account size the bot skips shares above ({_INR})", w)
    if m:
        return "share_price", (
            f"The account would need to be larger (at its size the bot skips shares above {m.group(2)}; "
            f"one share costs {m.group(1)})."
        )
    m = re.match(r"^(.+?) stocks are switched off for an account of", w)
    if m:
        return "cap_tier_off", f"The account would need to grow before {m.group(1).lower()} stocks unlock."
    if w.startswith("Small-company stocks already take"):
        return "small_company_budget", "There would need to be room in the small-company budget."
    m = re.search(rf"trades only about ({_INR}) a day", w)
    if m:
        return "liquidity", (
            f"The stock would need to trade more each day (today about {m.group(1)} a day — "
            "too thin for a position)."
        )
    if w.startswith("No price for this stock"):
        return "no_price", "Price data for this stock would need to come in."
    if w.startswith("Data is not reliable today"):
        return "data_not_reliable", "The stock's price data would need to be complete and up to date."
    if w.startswith("This stock is not in the instrument list"):
        return "no_instrument", "The stock would need to be in the app's list of tradable stocks."
    if w.startswith("Risk checks use today's account, so a replay"):
        return "replay", "Does not apply to a replay of a past date: replays never approve a trade."
    if w.startswith("The risk check failed for this stock"):
        return "risk_error", "The risk check would need to run without an error for this stock."
    return "account_limits", "The account's limits would need to allow a new trade."


# --- one reason ----------------------------------------------------------------------


def _line(reason: str, rank: ModelRank | None, banner_mode: str | None, banner_headline: str | None):
    """(key, line) for a reason that holds the idea back, or None for an informational line
    (the plan, the model's own reasons, context notes) or a reason not recognised."""
    r = reason.strip()
    if r.startswith(RISK_PREFIX):
        return _risk_line(r[len(RISK_PREFIX) :], banner_mode)

    # rules.py
    m = re.match(r"^On the exchange's watch list \((.+)\), so the brain stays away\.$", r)
    if m:
        return "exchange_watch_list", f"Only if the exchange removes it from its watch list ({m.group(1)})."
    m = re.match(rf"^Results on ({_DATE}): the brain avoids new trades", r)
    if m:
        return "results", f"After the results on {m.group(1)}."
    m = re.match(
        rf"^(.+?) on ({_DATE}) resets the share price — the brain avoids new trades around this\.$", r
    )
    if m:
        return "corporate_action", f"After the {m.group(1)} on {m.group(2)} has taken effect."
    if r.endswith("— the brain avoids new trades around this."):
        return "event", "After the coming event has passed."
    if r.startswith("The signals are weak or disagree"):
        return "weak_signals", "The stock's signals would need to agree more clearly that it is worth buying."
    if r == "The risk check has not approved this trade." or r == NOT_APPROVED:
        return "not_approved", "The risk check would need to approve a trade in this stock."
    if r.startswith("Similar cases lost money on average"):
        return "similar_cases_lost", (
            "Past situations like this one would need to have made money on average after costs "
            "(today they lost money)."
        )
    if r == "The market is careful and this stock is falling, so the brain waits for it to turn up.":
        return "careful_market_falling", (
            "The stock would need to start rising, or the market mode return to NORMAL."
        )
    m = re.match(r"^Its sector ranks (\d+) of (\d+) — outside the top (\d+) for new ideas\.$", r)
    if m:
        return "sector_rank", (
            f"Its sector would need to climb into the top {m.group(3)} "
            f"(today it ranks {m.group(1)} of {m.group(2)})."
        )
    if r == "No classic setup (pullback or breakout on volume) today.":
        return "no_setup", (
            "A classic setup would need to appear: a pull-back in an up-trend, "
            "or a breakout on strong volume."
        )

    # engine.py drafts
    if _BELOW_BUY_LEVEL.match(r):
        return "below_buy_level", _below_buy_level_line(rank)
    if re.match(r"^Calibrated chance \d+% is below the \d+% needed to pay after costs\.$", r):
        return "chance_too_low", (
            "The brain's estimated chance of reaching the target would need to rise enough to pay for costs."
        )
    if r == "The signals do not favour buying this stock today.":
        return "signals_not_favourable", "The signals would need to turn in favour of buying."
    if r == "No price data for this stock yet.":
        return "no_price", "Price data for this stock would need to come in."
    if r.startswith("No opinion about this stock today"):
        return "no_opinion", "The model would need to score this stock."

    # constitution.py
    if r == NO_RISK_GATE:
        return "no_risk_gate", "The risk check would need to run normally (it did not run today)."
    if r == DATA_NOT_CHECKED:
        return "data_not_checked", "The day's data would need to pass the data check."
    if r.startswith("Data is not reliable today"):
        return "data_not_reliable", "The stock's price data would need to be complete and up to date."
    if r == BAD_PLAN:
        return "bad_plan", "The trade plan would need usable prices (buy range, stop and target)."
    if r.startswith("Owner paused new buys"):
        return "owner_paused", "The owner would need to switch new buys back on."
    if r.startswith("Market data is not reliable today"):
        return "market_data_not_reliable", "Market-wide data would need to be up to date."
    if r == NO_DECISION:
        return (
            "no_decision",
            "The brain would need to finish its check on this stock (today it produced no decision).",
        )
    if banner_mode == "NO_NEW_TRADES" and banner_headline and r == banner_headline.strip():
        return "market_no_new_trades", "The market mode would need to leave NO NEW TRADES."
    return None


def what_would_change(
    decision: Any,
    *,
    rank: ModelRank | None = None,
    banner_mode: str | None = None,
    banner_headline: str | None = None,
) -> list[dict[str, str]]:
    """The conditions, most important first, for a WATCH / WAIT / AVOID idea; [] otherwise.

    Most important first = the stored order: the brain puts the reason that set the final
    word first. Each item is {"key": stable id, "text": plain line}."""
    if getattr(decision, "kind", None) != "idea" or getattr(decision, "word", None) not in EXPLAINED_WORDS:
        return []
    reasons = [r for r in (decision.reasons or []) if isinstance(r, str) and r.strip()]
    deciding = (decision.downgrade_reason or "").strip() or (reasons[0] if reasons else "")
    items: list[dict[str, str]] = []
    seen: set[str] = set()

    def add(key: str, text: str) -> None:
        if text not in seen:
            seen.add(text)
            items.append({"key": key, "text": text})

    if not deciding or _line(deciding, rank, banner_mode, banner_headline) is None:
        add("unknown", UNKNOWN)
    for r in reasons:
        found = _line(r, rank, banner_mode, banner_headline)
        if found is not None:
            add(*found)
    return items


__all__ = [
    "UNKNOWN",
    "ModelRank",
    "is_below_buy_level",
    "model_ranks",
    "what_would_change",
]
