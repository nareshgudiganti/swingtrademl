"""R5, C1 and spec 6: the numerical verdict and the independence status are separate, combined by a fixed
precedence; claims and minimums are bound by code. Nothing can show Proven without passing numbers AND an
untouched, committed audit."""

from __future__ import annotations

import pytest

from swing_trade_ml.services.brain_observatory import verdicts as v

MIN = {"eligible_folds": 12, "finished_ideas": 100, "share": 0.6}


def part(**kw):
    p = {
        "claim": "x",
        "recorded_word": "pass",
        "eligible_folds": 20,
        "folds_won": 14,
        "share": 0.7,
        "finished_ideas": 500,
        "extra_check": "e",
        "extra_check_value": 0.01,
    }
    p.update(kw)
    return p


def claims(reg):
    return {c["claim"]: c for c in v.evaluate(reg)}


def committed_audit(reg):
    reg["entries"][0]["sample"].update(
        independence="untouched", audit_path="docs/x.md", audit_sha256="0" * 64
    )
    return reg


def test_both_halves_of_the_pass_rule_are_required():
    assert v.numeric_verdict(part(), MIN) == ("pass", [])
    assert v.numeric_verdict(part(recorded_word="fail", extra_check_value=-0.01), MIN)[0] == "fail"
    assert v.numeric_verdict(part(recorded_word="fail", folds_won=11, share=0.55), MIN)[0] == "fail"


def test_below_minimums_is_insufficient():
    assert v.numeric_verdict(part(eligible_folds=11, folds_won=8, share=8 / 11), MIN)[0] == "insufficient"
    assert v.numeric_verdict(part(finished_ideas=99), MIN)[0] == "insufficient"


def test_inconsistent_numbers_are_invalid():
    assert v.numeric_verdict(part(share=0.9), MIN)[0] == "invalid"
    assert v.numeric_verdict(part(folds_won=30), MIN)[0] == "invalid"
    assert v.numeric_verdict(part(recorded_word="fail"), MIN)[0] == "invalid"


@pytest.mark.parametrize(
    ("numeric", "independence", "word"),
    [
        ("invalid", "untouched", v.INVALID),
        ("pass", "nonsense", v.INVALID),
        ("insufficient", "untouched", v.INSUFFICIENT),
        ("fail", "untouched", v.NOT_PROVEN),
        ("fail", "unaudited", v.NOT_PROVEN),
        ("pass", "unaudited", v.PASSED_NOT_PROVEN),
        ("pass", "audit_uncommitted", v.PASSED_NOT_PROVEN),
        ("pass", "exposure_disclosed", v.PASSED_NOT_PROVEN),
        ("pass", "untouched", v.PROVEN),
    ],
)
def test_precedence(numeric, independence, word):
    assert v.display_word(numeric, independence) == word


def test_real_registry_gives_not_proven_with_uncommitted_audit():
    out = claims(v.load_registry())
    for claim in ("model_ranking_predictive", "model_ranking_economic"):
        assert out[claim]["word"] == v.NOT_PROVEN
        assert out[claim]["numeric"] == "fail"
        assert out[claim]["independence"] == "audit_uncommitted"
    assert out["model_ranking_predictive"]["numbers"]["folds_won"] == 7
    assert out["model_ranking_economic"]["numbers"]["folds_won"] == 9


def test_claims_without_a_protocol():
    out = claims(v.load_registry())
    assert out["full_brain"]["word"] == v.NO_PROTOCOL
    assert out["learning_changes"]["word"] == v.NO_PROTOCOL


def test_untouched_requires_a_committed_audit():
    reg = v.load_registry()
    reg["entries"][0]["sample"]["independence"] = "untouched"
    assert claims(reg)["model_ranking_predictive"]["word"] == v.INVALID


def test_a_passing_entry_shows_proven_only_for_its_own_claim():
    reg = committed_audit(v.load_registry())
    reg["entries"][0]["parts"]["predictive"].update(
        recorded_word="pass", folds_won=14, share=14 / 21, extra_check_value=0.001
    )
    out = claims(reg)
    assert out["model_ranking_predictive"]["word"] == v.PROVEN
    assert out["model_ranking_economic"]["word"] == v.NOT_PROVEN
    assert out["full_brain"]["word"] == v.NO_PROTOCOL


def test_a_seen_sample_is_invalid():
    reg = v.load_registry()
    reg["entries"][0]["sample"]["kind"] = "seen"
    assert claims(reg)["model_ranking_predictive"]["word"] == v.INVALID


def test_renaming_a_claim_cannot_create_full_brain_proof():
    reg = committed_audit(v.load_registry())
    reg["entries"][0]["parts"]["predictive"].update(
        claim="full_brain", recorded_word="pass", folds_won=14, share=14 / 21, extra_check_value=0.001
    )
    out = claims(reg)
    assert out["full_brain"]["word"] == v.NO_PROTOCOL
    assert out["model_ranking_predictive"]["word"] == v.INVALID


def test_minimums_come_from_code_not_json():
    reg = v.load_registry()
    reg["entries"][0]["minimums"] = {"eligible_folds": 1, "finished_ideas": 1, "share": 0.1}
    assert claims(reg)["model_ranking_predictive"]["word"] == v.INVALID


def test_an_unknown_protocol_binds_nothing():
    reg = v.load_registry()
    reg["entries"][0]["protocol_id"] = "my-own-protocol"
    assert all(c["word"] == v.NO_PROTOCOL for c in claims(reg).values())
    assert v.rejected_entries(reg)[0]["protocol_id"] == "my-own-protocol"


def test_load_registry_returns_a_copy():
    a = v.load_registry()
    a["entries"][0]["protocol_id"] = "changed"
    assert v.load_registry()["entries"][0]["protocol_id"] == "wf-protocol-v1"


def test_registry_ships_as_python_package_code():
    from importlib.resources import files

    assert files("swing_trade_ml.services.brain_observatory").joinpath("validation_verdicts.py").is_file()
