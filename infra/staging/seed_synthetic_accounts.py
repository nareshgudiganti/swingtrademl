"""Create the synthetic STAGING test accounts through the application's own code.

Runs INSIDE the staging api container only (the host has no app code or database access):

    read -r -s -p "Owner password: " SEED_OWNER_PASSWORD; echo
    read -r -s -p "Test-account password: " SEED_TEST_PASSWORD; echo
    read -r -p  "Your own inbox (for real emails): " SEED_OWNER_EMAIL
    export SEED_OWNER_PASSWORD SEED_TEST_PASSWORD SEED_OWNER_EMAIL
    docker compose -f docker-compose.yml -f docker-compose.staging.yml exec -T \
        -e SEED_OWNER_PASSWORD -e SEED_TEST_PASSWORD -e SEED_OWNER_EMAIL \
        api python - < infra/staging/seed_synthetic_accounts.py

Passwords and the owner's address are read from the environment at run time; nothing is stored
in the repo. Re-running is safe: accounts are updated in place (password reset to the supplied one).

Accounts made:
  staging-owner      role owner,  email <you>+stg-owner@<your domain>  (real inbox via a +tag alias)
  free.test          role member, plan free, free.test@example.test
  pro.test           role member, plan pro,  pro.test@example.test     (plan set the way the owner's
                                                                      Plans Manager does it)
  member.test        role member, plan free, member.test@example.test  (second ordinary member, for
                                                                      "can A see B's data?" checks)

The *.example.test addresses cannot receive mail (the .test domain is reserved) - good: staging can
never email a real stranger. Use +tag aliases of your own address for tests that need a real email.
Never put a real person's email here other than your own.

On this base the app has no email-verified flag. Branches that add one (email/billing work) set it
below only if the attribute exists; for those branches also re-check what "verified" means.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime

from sqlalchemy import select
from swing_trade_ml.core.config import settings
from swing_trade_ml.core.plans import PLAN_KEYS
from swing_trade_ml.core.security import hash_password
from swing_trade_ml.db.models.session import User
from swing_trade_ml.db.session import session_scope

if settings.ENVIRONMENT != "staging":
    sys.exit(f"Refusing: ENVIRONMENT is {settings.ENVIRONMENT!r}, not 'staging'. Nothing was touched.")


def _need(name: str, minimum: int = 0) -> str:
    value = os.environ.get(name, "")
    if not value or len(value) < minimum:
        sys.exit(f"Missing {name} (need at least {minimum} characters). Nothing was touched.")
    return value


owner_password = _need("SEED_OWNER_PASSWORD", 12)
test_password = _need("SEED_TEST_PASSWORD", 12)
inbox = _need("SEED_OWNER_EMAIL")
if inbox.count("@") != 1 or "+" in inbox.split("@")[0] or inbox.lower().endswith("@example.test"):
    sys.exit("SEED_OWNER_EMAIL must be your own plain address, e.g. you@gmail.com (no +tag).")
local, domain = inbox.split("@")

ACCOUNTS = [
    # username, email, role, plan, password
    ("staging-owner", f"{local}+stg-owner@{domain}", "owner", "free", owner_password),
    ("free.test", "free.test@example.test", "member", "free", test_password),
    ("pro.test", "pro.test@example.test", "member", "pro", test_password),
    ("member.test", "member.test@example.test", "member", "free", test_password),
]

with session_scope() as db:
    for username, email, role, plan, password in ACCOUNTS:
        assert plan in PLAN_KEYS, plan
        user = db.execute(select(User).where(User.username == username)).scalar_one_or_none()
        created = user is None
        if user is None:
            user = User(username=username, auth_provider="local")
            db.add(user)
        user.email = email
        user.hashed_password = hash_password(password)
        user.is_active = True
        user.role = role
        user.is_superuser = role == "owner"
        user.plan = plan
        user.failed_login_count = 0
        user.locked_until = None
        # Added by the email-verification branch, if present on this checkout.
        if hasattr(User, "email_verified"):
            user.email_verified = True
        if hasattr(User, "email_verified_at"):
            user.email_verified_at = datetime.now(UTC)
        print(f"{'created' if created else 'updated'}: {username} ({role}, {plan}) {email}")
print("Done. Passwords were not printed.")
