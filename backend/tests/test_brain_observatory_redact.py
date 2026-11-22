"""Spec 3.4 and R9: redact secrets in free text only; ids, symbols, numbers and cursors are never altered."""

from __future__ import annotations

import os
from urllib.parse import unquote, urlsplit

import pytest

from swing_trade_ml.core.config import settings
from swing_trade_ml.services.brain_observatory import redact as redact_mod
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


MIN_LISTED = 4  # the redactor only puts passwords of at least this length on its redaction list
UNCHECKABLE = "unable to check"  # the answer when the URL cannot be parsed or the check itself failed


def _check_database_password(url: str) -> bool | None:
    raw = urlsplit(url).password
    if not raw:
        return None
    decoded = unquote(raw)
    if len(decoded) < MIN_LISTED:
        return None
    listed = decoded in redact_mod._secret_values()
    # Judged on the bare value, not on a sentence around it: a password that equals a word of the sentence or
    # of the mask ("[redacted]") would otherwise look unredacted. Redaction must change the value itself.
    hidden = redact_text(decoded) != decoded
    return listed and hidden


def _database_password_redacted(url: str) -> bool | str | None:
    """Whether the DECODED password of `url` is on the redaction list AND removed from free text.

    None when there is nothing to check: no password, or one shorter than the redactor lists.
    The credential a database driver actually uses is the percent-decoded one, so that is what is checked.
    The list is read directly because the generic long-token mask also hides a long alphanumeric
    password, which would let a regression in the password-specific redaction pass unnoticed.
    Only a bool, None or the fixed UNCHECKABLE text ever leaves this function, and it never raises: a parse
    failure or any other error is answered, not propagated, because a propagating exception would carry
    this frame (the URL, the raw and the decoded password) into the traceback and `pytest --showlocals`.
    """
    try:
        return _check_database_password(url)
    except Exception:  # noqa: BLE001 - nothing secret may travel with an exception
        return UNCHECKABLE


def test_the_test_database_password_is_redacted():
    # Whichever test role is in use (shared or an isolated per-developer one). The URL goes straight into the
    # helper, so no password sits in this test's locals.
    result = _database_password_redacted(os.environ["DATABASE_URL"])
    if result is None:
        pytest.skip("this test database URL has no password the redactor lists, nothing to check")
    assert result != UNCHECKABLE, "the test database URL could not be checked"
    assert result is True, "the test database password is not redacted"


def _use_url(monkeypatch, url: str) -> None:
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(settings, "DATABASE_URL", url, raising=False)


# A short password, and a 42-character one that the generic long-token mask would also hide.
@pytest.mark.parametrize("password", ["Syn7hetic-pw", "Ab1" * 14])
def test_a_database_password_is_redacted_and_the_check_can_fail(monkeypatch, password):
    url = f"postgresql+psycopg://synthuser:{password}@localhost:5433/synth_test"
    _use_url(monkeypatch, url)
    assert _database_password_redacted(url) is True, "redaction missed a database password"
    # The same check must fail when the password-specific redaction is removed (in memory only).
    real = redact_mod._secret_values
    monkeypatch.setattr(redact_mod, "_secret_values", lambda: [v for v in real() if password not in v])
    assert _database_password_redacted(url) is False, "the check did not notice the redaction being removed"


def test_a_password_shorter_than_the_redaction_minimum_is_not_a_failure(monkeypatch):
    url = "postgresql+psycopg://synthuser:abc@localhost:5433/synth_test"  # 3 characters
    _use_url(monkeypatch, url)
    assert len("abc") < MIN_LISTED
    assert _database_password_redacted(url) is None


def test_a_password_with_special_characters_is_redacted_in_both_forms(monkeypatch):
    # Decoded, the password is Syn@th3tic-pw: the form a driver uses and an error message can contain.
    url = "postgresql+psycopg://synthuser:Syn%40th3tic-pw@localhost:5433/synth_test"
    _use_url(monkeypatch, url)
    assert _database_password_redacted(url) is True
    # The encoded form (as written in the URL) stays redacted too.
    assert "Syn%40th3tic-pw" not in redact_text("could not connect with Syn%40th3tic-pw")


@pytest.mark.parametrize("password", ["redacted", "connect", "with"])
def test_a_password_that_is_a_word_of_the_replacement_text_is_not_a_false_failure(monkeypatch, password):
    """The check must not be fooled by the mask `[redacted]` or by the words of its own sample sentence."""
    url = f"postgresql+psycopg://synthuser:{password}@localhost:5433/synth_test"
    _use_url(monkeypatch, url)
    assert _database_password_redacted(url) is True


def test_a_url_that_cannot_be_parsed_is_reported_without_raising_or_exposing_it(monkeypatch):
    """urlsplit raises on this URL (invalid IPv6 host). An exception would put the URL, with its password,
    into the traceback and into `pytest --showlocals`, so the helper must answer instead of raising."""
    url = "postgresql+psycopg://synthuser:Syn7hetic-pw@[::1/synth_test"
    _use_url(monkeypatch, url)
    with pytest.raises(ValueError):
        urlsplit(url)  # the premise: this really is unparseable
    result = _database_password_redacted(url)
    assert result == UNCHECKABLE
    assert "Syn7hetic-pw" not in repr(result)


def test_a_failure_inside_the_check_is_reported_without_raising(monkeypatch):
    def boom():
        raise RuntimeError("synthetic failure carrying Syn7hetic-pw")

    monkeypatch.setattr(redact_mod, "_secret_values", boom)
    url = "postgresql+psycopg://synthuser:Syn7hetic-pw@localhost:5433/synth_test"
    assert _database_password_redacted(url) == UNCHECKABLE


def test_a_database_url_without_a_password_is_handled(monkeypatch):
    url = "postgresql+psycopg://synthuser@localhost:5433/synth_test"
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setattr(settings, "DATABASE_URL", url, raising=False)
    assert urlsplit(url).password is None
    assert redact_text("plain text, no secrets") == "plain text, no secrets"


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


def test_a_long_file_path_is_not_masked():
    """ob15: a traceback path is not a secret; masking it hid where the error happened."""
    s = "boom in /app/src/swing_trade_ml/services/brain_observatory/outcomes.py line 12"
    assert redact_text(s) == s


def test_a_long_mixed_case_token_with_slashes_is_still_masked():
    token = "Ab3dE/fG7hIjK9lMnO/pQrStUvWxYz0123456789ABcd"
    assert token not in redact_text(f"value {token} end")


def test_dicts_nested_under_a_free_text_key_are_redacted():
    """ob15: free text stays free text however deep it is nested under a free-text key."""
    out = redact_response({"detail": {"inner": {"deep": f"jwt {JWT}"}}, "run_id": "x"})
    assert JWT not in out["detail"]["inner"]["deep"]
    assert out["redacted_fields"] == ["detail.inner.deep"]
