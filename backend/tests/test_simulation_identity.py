"""#379 synthetic identity boundary: 100 fictional personas, example.com only, mail off, an explicit flag, no
passwords on disk, lookups by synthetic key. Pure: no database, no network."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from swing_trade_ml.simulation import identity
from swing_trade_ml.simulation.identity import (
    OutgoingMailBlocked,
    Policy,
    SyntheticIdentityError,
    SyntheticPersona,
    generate_roster,
    is_synthetic_address,
    new_runtime_password,
    persona_by_key,
    refuse_mail,
)

PACKAGE = Path(identity.__file__).parent


def test_the_roster_is_100_personas_99_compared_and_1_validation():
    roster = generate_roster()
    assert len(roster) == 100
    assert sum(p.counts_in_comparison for p in roster) == 99
    assert [p.key for p in roster if p.is_validation] == ["syn-100"]


def test_each_compared_policy_has_exactly_33_personas():
    counts = Counter(p.policy for p in generate_roster() if p.counts_in_comparison)
    assert counts == {Policy.MOMENTUM: 33, Policy.MODEL_ONLY: 33, Policy.BRAIN_FILTERED: 33}


def test_every_setup_has_one_persona_per_policy():
    by_setup: dict[str, list[Policy]] = {}
    for p in generate_roster():
        if p.counts_in_comparison:
            by_setup.setdefault(p.setup_key, []).append(p.policy)
    assert len(by_setup) == 33
    assert all(sorted(v) == sorted(Policy) for v in by_setup.values())


def test_keys_emails_and_names_are_unique_and_the_roster_is_repeatable():
    roster = generate_roster()
    for field in ("key", "email", "display_name"):
        values = [getattr(p, field) for p in roster]
        assert len(set(values)) == 100, field
    assert generate_roster() == roster  # seeding twice can never add anyone


def test_every_address_is_example_com_and_passes_the_apps_own_validators():
    from swing_trade_ml.api.v1.endpoints.invites import normalise_email, valid_email

    for p in generate_roster():
        assert p.email.endswith("@example.com")
        assert valid_email(p.email) and normalise_email(p.email) == p.email
        assert is_synthetic_address(p.email)


def test_every_persona_is_flagged_synthetic_and_has_all_mail_switches_off():
    for p in generate_roster():
        assert p.synthetic is True
        assert (p.outgoing_mail, p.invitations, p.password_resets, p.marketing) == (False,) * 4


def test_a_persona_cannot_be_built_without_the_flag_or_with_a_mail_switch_on():
    base = generate_roster()[0]
    for change in (
        {"synthetic": False},
        {"outgoing_mail": True},
        {"invitations": True},
        {"password_resets": True},
        {"marketing": True},
    ):
        with pytest.raises(SyntheticIdentityError):
            replace(base, **change)


def test_a_real_looking_address_or_a_bad_key_is_refused():
    base = generate_roster()[0]
    with pytest.raises(SyntheticIdentityError):
        replace(base, email="someone@gmail.com")
    with pytest.raises(SyntheticIdentityError):
        replace(base, key="user-1")
    with pytest.raises(SyntheticIdentityError):
        replace(base, email="not an address@example.com")


def test_the_validation_persona_exercises_the_brain_filtered_path_and_is_excluded():
    validation = persona_by_key(generate_roster(), "syn-100")
    assert validation.is_validation and validation.policy is Policy.BRAIN_FILTERED
    assert not validation.counts_in_comparison
    assert validation.setup_key == identity.VALIDATION_USES_SETUP
    with pytest.raises(SyntheticIdentityError):
        replace(validation, policy=Policy.MOMENTUM)


def test_lookup_is_by_synthetic_key_only():
    roster = generate_roster()
    first = roster[0]
    assert persona_by_key(roster, first.key) is first
    for not_a_key in (first.display_name, first.email, "setup-01"):
        with pytest.raises(KeyError):
            persona_by_key(roster, not_a_key)


def test_mail_to_a_synthetic_address_is_always_refused_and_a_real_one_is_not_this_packages_business():
    for p in generate_roster():
        with pytest.raises(OutgoingMailBlocked):
            refuse_mail(p.email, "invitation")
    refuse_mail("a.real.person@gmail.com", "invitation")  # not synthetic: this gate has no opinion


def test_passwords_are_made_at_run_time_and_never_stored():
    assert new_runtime_password() != new_runtime_password()
    assert len(new_runtime_password()) >= 16
    # No file in the package may hold a password or secret literal.
    pattern = re.compile(r"(?i)(password|passwd|secret|token)\s*[:=]\s*[\"'][^\"']+[\"']")
    for path in PACKAGE.glob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), path.name


def test_the_roster_data_has_no_credential_and_no_real_domain():
    text = (PACKAGE / "roster_data.py").read_text(encoding="utf-8")
    assert "@" in text
    assert set(re.findall(r"@([a-z0-9.-]+)", text)) == {"example.com"}
    assert not re.search(r"(?i)password", text.split('"""', 2)[2])


def test_importing_the_package_loads_no_database_web_mail_or_broker_module():
    """A fresh interpreter imports every module of the package; none of these may end up in sys.modules."""
    import subprocess
    import sys

    src = str(PACKAGE.parents[1])
    code = "\n".join(
        [
            "import sys, importlib, pkgutil",
            f"sys.path.insert(0, {src!r})",
            "import swing_trade_ml.simulation as pkg",
            "for m in pkgutil.iter_modules(pkg.__path__):",
            "    importlib.import_module('swing_trade_ml.simulation.' + m.name)",
            "heavy = ('sqlalchemy', 'fastapi', 'smtplib', 'httpx', 'requests')",
            "inner = ('swing_trade_ml.db', 'swing_trade_ml.api', 'swing_trade_ml.brokers')",
            "bad = [n for n in sys.modules if n.split('.')[0] in heavy or n.startswith(inner)]",
            "print(sorted(bad)[:10])",
            "sys.exit(1 if bad else 0)",
        ]
    )
    done = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        cwd=src,
        check=False,
        env={"PATH": ""},
    )
    assert done.returncode == 0, done.stdout + done.stderr


def test_the_copied_email_rule_agrees_with_the_applications_validators():
    from swing_trade_ml.api.v1.endpoints.invites import normalise_email, valid_email

    odd = [
        "a@b.co",
        "bad@",
        "x y@example.com",
        "Mixed@Example.com",
        "nodot@example",
        "a@b.c",
        "x" * 65 + "@example.com",
    ]
    for email in [p.email for p in generate_roster()] + odd:
        ours = email == email.strip().lower() and len(email) <= 254 and bool(identity._EMAIL_RE.match(email))
        assert ours == (normalise_email(email) == email and valid_email(email)), email


def test_the_persona_type_is_frozen():
    persona = generate_roster()[0]
    assert isinstance(persona, SyntheticPersona)
    with pytest.raises(AttributeError):
        persona.synthetic = False  # type: ignore[misc]
