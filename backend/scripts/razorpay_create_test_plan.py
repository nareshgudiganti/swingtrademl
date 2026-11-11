"""Create the monthly Pro plan in the Razorpay TEST dashboard (one-off, owner runs it by hand).

DRY-RUN BY DEFAULT: prints the request it would send and sends nothing.
    python backend/scripts/razorpay_create_test_plan.py            # dry run
    python backend/scripts/razorpay_create_test_plan.py --execute  # really calls Razorpay (test mode)

Keys come from the environment (RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET), never from the command line
and never printed. A key id that does not start with `rzp_test_` is refused, always: this script
has no way to touch live mode. The amount is PRO_PRICE_MONTHLY_PAISE (default is a placeholder).
On success it prints the plan id to put in RAZORPAY_PLAN_ID_PRO_MONTHLY in the deployment .env.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

URL = "https://api.razorpay.com/v1/plans"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--execute", action="store_true", help="really send the request (default: dry run)")
    parser.add_argument(
        "--amount-paise", type=int, default=int(os.environ.get("PRO_PRICE_MONTHLY_PAISE", "49900"))
    )
    parser.add_argument("--name", default="TradeMind Pro (monthly, test)")
    args = parser.parse_args()

    key_id = os.environ.get("RAZORPAY_KEY_ID", "")
    key_secret = os.environ.get("RAZORPAY_KEY_SECRET", "")
    if not key_id.startswith("rzp_test_"):
        print(
            "Refusing: RAZORPAY_KEY_ID must be set and start with rzp_test_ (test mode only).",
            file=sys.stderr,
        )
        return 2
    if args.amount_paise < 100:
        print("Refusing: amount must be at least 100 paise (Rs 1).", file=sys.stderr)
        return 2

    payload = {
        "period": "monthly",
        "interval": 1,
        "item": {"name": args.name, "amount": args.amount_paise, "currency": "INR"},
    }
    print(f"POST {URL}")
    print(json.dumps(payload, indent=2))
    if not args.execute:
        print("\nDRY RUN: nothing was sent. Add --execute to create the plan in the Razorpay test dashboard.")
        return 0
    if not key_secret:
        print("Refusing: RAZORPAY_KEY_SECRET is not set.", file=sys.stderr)
        return 2
    resp = httpx.post(URL, json=payload, auth=(key_id, key_secret), timeout=20)
    if resp.status_code >= 400:
        print(f"Razorpay answered HTTP {resp.status_code}. Check the test keys and amount.", file=sys.stderr)
        return 1
    print(
        f"\nCreated. Put this in the deployment .env only: RAZORPAY_PLAN_ID_PRO_MONTHLY={resp.json()['id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
