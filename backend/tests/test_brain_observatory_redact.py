"""Spec 3.4 and R9: redact secrets in free text only; ids, symbols, numbers and cursors are never altered."""

from __future__ import annotations

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.brain_observatory.redact import FREE_TEXT_KEYS, redact_response, redact_text

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJvd25lciJ9.c2lnbmF0dXJlLXZhbHVlLWhlcmU"
HEX40 = "0123456789abcdef0123456789abcdef01234567"


def test_each_secret_kind_in_free_text_is_replaced(monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_BOT_TOKEN", "123456:obs-telegram-token-value", raising=False)
    text = (
        "boom postgresql://swing:hunter2@db:5432/x mail naresh@example.com jwt "
        f"{JWT} api_key=abcd1234 token: zzz999 blob {HEX40} tg 123456:obs-telegram-token-value end"
    )
    out = redact_text(text)
    for secret in (
        "hunter2",
        "naresh@example.com",
        JWT,
        "abcd1234",
        "zzz999",
        HEX40,
        "obs-telegram-token-value",
    ):
        assert secret not in out
    assert out.startswith("boom ") and out.endswith(" end")
    assert "postgresql://[redacted]@db:5432/x" in out


def test_the_test_database_password_is_redacted():
    assert "swingtrade_local_pw" not in redact_text("could not connect with swingtrade_local_pw")


def test_text_without_secrets_is_byte_identical():
    s = "Model score 41% is below the buy level 60%. Results on 08 Oct."
    assert redact_text(s) == s


def test_ids_and_cursors_are_never_altered():
    payload = {
        "run_id": "nightly-20261015T155000-ab12cd",
        "decision_id": 912345,
        "symbol": "BAJAJ-AUTO",
        "next_cursor": {"after_id": 912345, "after_started_at": "2026-10-15T10:20:00+00:00"},
        "word": "WAIT",
        "error": f"failed with {HEX40}",
    }
    out = redact_response(payload)
    for key in ("run_id", "decision_id", "symbol", "next_cursor", "word"):
        assert out[key] == payload[key]
    assert HEX40 not in out["error"]
    assert out["redacted_fields"] == ["error"]


def test_a_run_id_and_symbol_inside_free_text_are_kept():
    s = "superseded by nightly-20261015T155000-ab12cd at 15:52 for BAJAJ-AUTO"
    assert redact_text(s) == s


def test_nested_lists_and_paths_are_reported():
    payload = {"runs": [{"id": "x", "trace": [{"module_id": "M06", "reason": "error: token=abc123"}]}]}
    out = redact_response(payload)
    assert "abc123" not in out["runs"][0]["trace"][0]["reason"]
    assert out["redacted_fields"] == ["runs[0].trace[0].reason"]


def test_only_named_keys_are_free_text():
    assert {
        "error",
        "reason",
        "reasons",
        "evidence_text",
        "downgrade_reason",
        "overrule_reason",
    } <= FREE_TEXT_KEYS
    assert not {"id", "run_id", "decision_id", "symbol", "next_cursor", "after_id", "word"} & FREE_TEXT_KEYS
