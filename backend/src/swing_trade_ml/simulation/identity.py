# ruff: noqa: E501  (long plain-English docstrings)
"""The synthetic identity boundary for the 100-portfolio paper trial (#379, #321, #264).

Everything in this package is a SIMULATION: fictional people, example.com addresses, in-memory data, no mail, no
broker, no money. This module draws the line between those personas and real customers:

- every persona carries an explicit `synthetic = True` flag (it cannot be built without it) and a stable synthetic
  key (`syn-001` ... `syn-100`). Lookups use that key, never the display name or the email;
- every persona's mail switches (outgoing mail, invitations, password resets, marketing) are off, and
  `refuse_mail` is the one place a send must pass: it refuses every example.com address;
- the 100 are 99 matched comparison portfolios plus 1 validation persona that is excluded from every comparison;
- passwords are never stored: `new_runtime_password` makes a fresh one at test run time.

Nothing here touches a database (no schema yet) or the network.
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass
from enum import StrEnum

from swing_trade_ml.simulation.roster_data import ROSTER_ROWS

SYNTHETIC_DOMAIN = "example.com"  # reserved by RFC 2606: never a real mailbox
PERSONA_COUNT = 100
COMPARED_COUNT = 99  # the validation persona is not part of any comparison
# #379: the validation persona "exercises the Brain-filtered path using an explicitly selected existing setup".
# The issue does not name which one. This is a placeholder pending the owner's choice (open question), not a rule.
VALIDATION_USES_SETUP = "setup-01"

_KEY_RE = re.compile(r"^syn-\d{3}$")
# A copy of the application's own email rule (api/v1/endpoints/invites.py `valid_email` / `normalise_email`), kept here
# so this package imports nothing from the web layer. tests/test_simulation_identity.py checks the copy against the
# application's validators on every address, so the two cannot drift apart unnoticed.
_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s.]{2,}$")
_SETUP_RE = re.compile(r"^setup-\d{2}$")


class Policy(StrEnum):
    """How a portfolio picks its stocks. The three compared policies of #321."""

    MOMENTUM = "momentum"
    MODEL_ONLY = "model_only"
    BRAIN_FILTERED = "brain_filtered"


_POLICY_LABELS = {
    "Momentum": Policy.MOMENTUM,
    "Model-only": Policy.MODEL_ONLY,
    "Brain-filtered": Policy.BRAIN_FILTERED,
}
VALIDATION_LABEL = "Validation only"


class OutgoingMailBlocked(RuntimeError):  # noqa: N818 - reads as the refusal it is
    """A message to a synthetic address was attempted. It is never sent."""


class SyntheticIdentityError(ValueError):
    """A persona broke a rule of the synthetic boundary."""


def is_synthetic_address(email: str) -> bool:
    return email.strip().lower().rsplit("@", 1)[-1] == SYNTHETIC_DOMAIN


def refuse_mail(email: str, purpose: str = "message") -> None:
    """The one gate a send to a persona must pass. A synthetic address always raises; no message is built, queued
    or sent. (A real address returns: this package never sends mail itself, it only refuses for its own personas.)"""
    if is_synthetic_address(email):
        raise OutgoingMailBlocked(f"{purpose} to a synthetic address is blocked")


def new_runtime_password() -> str:
    """A fresh random password for one test run. Never written to a file, a log or a roster."""
    return secrets.token_urlsafe(18)


@dataclass(frozen=True, slots=True)
class SyntheticPersona:
    key: str  # stable synthetic key, e.g. "syn-007": the only way a persona is looked up
    display_name: str
    email: str
    policy: Policy
    setup_key: str  # the matched setup ("setup-01"); a validation persona names the existing one it exercises
    is_validation: bool = False
    synthetic: bool = True  # explicit flag: a persona cannot be built without it
    # Every outgoing channel is off for a synthetic persona, and cannot be turned on.
    outgoing_mail: bool = False
    invitations: bool = False
    password_resets: bool = False
    marketing: bool = False

    def __post_init__(self) -> None:
        if self.synthetic is not True:
            raise SyntheticIdentityError(f"{self.key}: a persona must carry the synthetic flag")
        if not _KEY_RE.match(self.key):
            raise SyntheticIdentityError(f"{self.key}: not a synthetic key")
        if not _SETUP_RE.match(self.setup_key):
            raise SyntheticIdentityError(f"{self.key}: not a setup key ({self.setup_key})")
        if any((self.outgoing_mail, self.invitations, self.password_resets, self.marketing)):
            raise SyntheticIdentityError(f"{self.key}: every outgoing channel must stay off")
        if not is_synthetic_address(self.email):
            raise SyntheticIdentityError(f"{self.key}: the address must be on {SYNTHETIC_DOMAIN}")
        if self.is_validation and self.policy is not Policy.BRAIN_FILTERED:
            raise SyntheticIdentityError(
                f"{self.key}: the validation persona exercises the Brain-filtered path"
            )
        self._check_email_with_the_apps_validators()

    def _check_email_with_the_apps_validators(self) -> None:
        if (
            self.email != self.email.strip().lower()
            or len(self.email) > 254
            or not _EMAIL_RE.match(self.email)
        ):
            raise SyntheticIdentityError(f"{self.key}: the application would not accept {self.email}")

    @property
    def counts_in_comparison(self) -> bool:
        return not self.is_validation


def generate_roster() -> tuple[SyntheticPersona, ...]:
    """The 100 personas of #379, in the issue's order, with keys syn-001 to syn-100. Deterministic and in memory:
    calling it twice gives equal results, so seeding can never duplicate anyone."""
    personas: list[SyntheticPersona] = []
    for number, (name, email, policy_label, setup_label) in enumerate(ROSTER_ROWS, start=1):
        key = f"syn-{number:03d}"
        if policy_label == VALIDATION_LABEL:
            personas.append(
                SyntheticPersona(
                    key=key,
                    display_name=name,
                    email=email,
                    policy=Policy.BRAIN_FILTERED,
                    setup_key=VALIDATION_USES_SETUP,
                    is_validation=True,
                )
            )
            continue
        personas.append(
            SyntheticPersona(
                key=key,
                display_name=name,
                email=email,
                policy=_POLICY_LABELS[policy_label],
                setup_key=setup_label,
            )
        )
    verify_roster(personas)
    return tuple(personas)


def verify_roster(personas: tuple[SyntheticPersona, ...] | list[SyntheticPersona]) -> None:
    """The structural promises of #379, checked whenever a roster is built."""
    if len(personas) != PERSONA_COUNT:
        raise SyntheticIdentityError(f"expected {PERSONA_COUNT} personas, found {len(personas)}")
    for label, values in (
        ("key", [p.key for p in personas]),
        ("email", [p.email for p in personas]),
        ("display name", [p.display_name for p in personas]),
    ):
        if len(set(values)) != len(values):
            raise SyntheticIdentityError(f"duplicate {label} in the roster")
    compared = [p for p in personas if p.counts_in_comparison]
    if len(compared) != COMPARED_COUNT or len(personas) - len(compared) != 1:
        raise SyntheticIdentityError("expected 99 compared personas and exactly 1 validation persona")


def persona_by_key(personas: tuple[SyntheticPersona, ...], key: str) -> SyntheticPersona:
    """Lookup by the explicit synthetic key only (#379 acceptance 10): never by name or email."""
    for persona in personas:
        if persona.key == key:
            return persona
    raise KeyError(key)
