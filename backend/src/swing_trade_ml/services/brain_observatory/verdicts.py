"""Effectiveness verdicts (spec section 6; R5, C1).

The numerical verdict (from the protocol's own numbers and pass rule) and the independence status (was the
sample untouched, with a committed audit?) are kept apart and combined by one fixed precedence. Which
claims a protocol may feed, and its minimums, are fixed here in code; the registry is checked, never
trusted. Integrity of the registry against git (tags, file hashes, report numbers) is checked in CI by
tests/test_brain_observatory_verdicts_ci.py; a registry that fails those checks cannot be deployed.
"""

from __future__ import annotations

import copy

from swing_trade_ml.services.brain_observatory.validation_verdicts import REGISTRY

INVALID = "Verdict record invalid"
NO_PROTOCOL = "No frozen protocol yet"
INSUFFICIENT = "Insufficient evidence"
NOT_PROVEN = "Not proven"
PASSED_NOT_PROVEN = "Passed, not proven: independence not established"
PROVEN = "Proven"
INDEPENDENCE = ("untouched", "exposure_disclosed", "audit_uncommitted", "unaudited")
CLAIMS = (
    ("model_ranking_predictive", "Model top-5 ranking: picks better than a random pick"),
    ("model_ranking_economic", "Model top-5 ranking: profit after costs"),
    ("full_brain", "Full brain decisions"),
    ("learning_changes", "Changes proposed by learning (M09)"),
)
# Frozen protocols known to this code. Only these can produce a verdict, only for the claims listed, and
# only with these minimums. Changing a claim name or a minimum in the registry makes the record invalid; it
# can never move a model-ranking result onto the full-brain claim.
FROZEN_PROTOCOLS = {
    "wf-protocol-v1": {
        "tag": "wf-protocol-v1",
        "parts": {"predictive": "model_ranking_predictive", "economic": "model_ranking_economic"},
        "minimums": {"eligible_folds": 12, "finished_ideas": 100, "share": 0.6},
    },
}
NUMBER_KEYS = ("eligible_folds", "folds_won", "share", "finished_ideas", "extra_check", "extra_check_value")


def load_registry() -> dict:
    return copy.deepcopy(REGISTRY)


def numeric_verdict(part: dict, minimums: dict) -> tuple[str, list[str]]:
    eligible, won = part["eligible_folds"], part["folds_won"]
    if not 0 <= won <= eligible:
        return "invalid", ["folds won is outside 0 to eligible folds"]
    if eligible and abs(part["share"] - won / eligible) > 1e-9:
        return "invalid", ["share does not equal folds won / eligible folds"]
    if eligible < minimums["eligible_folds"] or part["finished_ideas"] < minimums["finished_ideas"]:
        return "insufficient", ["below the protocol's minimum folds or finished ideas"]
    word = "pass" if part["share"] >= minimums["share"] and part["extra_check_value"] > 0 else "fail"
    if part["recorded_word"] != word:
        return "invalid", [f"report says '{part['recorded_word']}' but its numbers give '{word}'"]
    return word, []


def display_word(numeric: str, independence: str | None) -> str:
    if numeric == "invalid" or independence not in INDEPENDENCE:
        return INVALID
    if numeric == "insufficient":
        return INSUFFICIENT
    if numeric == "fail":
        return NOT_PROVEN
    return PROVEN if independence == "untouched" else PASSED_NOT_PROVEN


def _entry_problems(entry: dict, frozen: dict) -> list[str]:
    problems = []
    if entry.get("tag") != frozen["tag"]:
        problems.append("tag differs from the frozen protocol's tag")
    if entry.get("minimums") != frozen["minimums"]:
        problems.append("minimums differ from the frozen protocol's")
    if set(entry.get("parts", {})) != set(frozen["parts"]):
        problems.append("parts differ from the frozen protocol's")
    for name, part in entry.get("parts", {}).items():
        if frozen["parts"].get(name) != part.get("claim"):
            problems.append(f"part '{name}' is bound to a claim the protocol does not test")
    sample = entry.get("sample", {})
    if sample.get("kind") != "confirmation":
        problems.append("sample is not the protocol's confirmation sample")
    if sample.get("independence") in ("untouched", "exposure_disclosed") and not (
        sample.get("audit_path") and sample.get("audit_sha256")
    ):
        problems.append("independence is claimed without a committed audit (path and hash)")
    return problems


def evaluate(registry: dict) -> list[dict]:
    found: dict[str, dict] = {}
    for entry in registry.get("entries", []):
        frozen = FROZEN_PROTOCOLS.get(entry.get("protocol_id"))
        if frozen is None:
            continue  # reported by rejected_entries; binds no claim
        problems = _entry_problems(entry, frozen)
        sample = entry.get("sample", {})
        for name, claim in frozen["parts"].items():  # the claim comes from code, never from the registry
            part = entry.get("parts", {}).get(name)
            if problems or part is None:
                numeric, why = "invalid", problems or [f"part '{name}' is missing"]
            else:
                numeric, why = numeric_verdict(part, frozen["minimums"])
            found[claim] = {
                "word": display_word(numeric, sample.get("independence")),
                "numeric": numeric,
                "independence": sample.get("independence"),
                "independence_note": sample.get("independence_note", ""),
                "protocol_id": entry["protocol_id"],
                "tested_subject": entry.get("tested_subject"),
                "numbers": None if part is None else {k: part.get(k) for k in NUMBER_KEYS},
                "problems": why,
            }
    out = []
    for claim, label in CLAIMS:
        item = found.get(claim) or {
            "word": NO_PROTOCOL,
            "numeric": None,
            "independence": None,
            "independence_note": "",
            "protocol_id": None,
            "tested_subject": None,
            "numbers": None,
            "problems": [],
        }
        out.append({"claim": claim, "label": label, **item})
    return out


def rejected_entries(registry: dict) -> list[dict]:
    return [
        {"protocol_id": e.get("protocol_id"), "why": "not a frozen protocol known to this code"}
        for e in registry.get("entries", [])
        if e.get("protocol_id") not in FROZEN_PROTOCOLS
    ]
