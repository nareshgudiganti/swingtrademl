"""Pure password rules (task 1.2). Not wired into signup yet."""

from __future__ import annotations

from swing_trade_ml.core.password_policy import check_password, load_common_passwords

NONE: set[str] = set()


def test_14_chars_rejected_15_accepted():
    assert check_password("xK9vQ2mLp7Rt4Wz", common_passwords=NONE) == []  # 15
    assert check_password("xK9vQ2mLp7Rt4W", common_passwords=NONE)  # 14


def test_long_passphrase_with_spaces_accepted():
    assert check_password("purple tractor eats seven cold noodles", common_passwords=NONE) == []


def test_no_composition_rules():
    assert check_password("onlylowercaseletters", common_passwords=NONE) == []


def test_common_password_rejected_with_injected_set():
    assert check_password("correct-pony-staple", common_passwords={"correct-pony-staple"})
    assert check_password("Correct-Pony-Staple", common_passwords={"correct-pony-staple"})


def test_bundled_list_loads_and_rejects_long_common_one():
    common = load_common_passwords()
    assert len(common) >= 300 and "password" in common
    assert check_password("passwordpassword")


def test_contains_email_local_part_rejected():
    assert check_password("my-asha.rao-secret-phrase", email="asha.rao@example.com", common_passwords=NONE)
    assert check_password("ASHAxrandomwordsxhere", email="asha@example.com", common_passwords=NONE)
    assert check_password("blue-fox-jumps-high-now", email="asha@example.com", common_passwords=NONE) == []


def test_contains_name_token_rejected():
    assert check_password("lovely-rao-family-trip", name="Asha Rao", common_passwords=NONE)
    assert check_password("blue-fox-jumps-high-now", name="Asha Rao", common_passwords=NONE) == []


def test_empty_rejected():
    assert check_password("", common_passwords=NONE)
    assert check_password(None, common_passwords=NONE)  # type: ignore[arg-type]


def test_257_chars_rejected_256_accepted():
    assert check_password("ab" * 128, common_passwords=NONE) == []
    assert check_password("a" * 257, common_passwords=NONE)


def test_unicode_counted_by_characters():
    assert check_password("అ" * 15, common_passwords=NONE) == []
    assert check_password("అ" * 14, common_passwords=NONE)
    assert check_password("\U0001f600" * 15, common_passwords=NONE) == []  # one character each, not bytes


def test_bundled_common_password_list_is_loaded():
    """If this file is missing at runtime the loader returns an empty set and the check silently turns off."""
    from swing_trade_ml.core.password_policy import load_common_passwords

    assert len(load_common_passwords()) > 400


def test_common_password_file_is_shipped_in_the_built_package():
    """The production image installs a built wheel, so the data file must be listed as package data."""
    import tomllib
    from pathlib import Path

    cfg = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    shipped = cfg["tool"]["setuptools"]["package-data"]["swing_trade_ml"]
    assert "core/common_passwords.txt" in shipped
