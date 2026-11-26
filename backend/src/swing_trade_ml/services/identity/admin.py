"""Owner/admin command line for the identity writers that have no job (#389):

    python -m swing_trade_ml.services.identity.admin backfill-instruments [--exchange NSE] [--dry-run]
    python -m swing_trade_ml.services.identity.admin backfill-scores [--since YYYY-MM-DD] [--dry-run]
    python -m swing_trade_ml.services.identity.admin brain-run RUN_ID [--dry-run]

What each does: `backfill-instruments` gives every equity instrument a security (idempotent);
`backfill-scores` copies the old one-row-a-day score history into the ledger as `backfill` rows;
`brain-run` records one finished brain run's decisions in the ledger with the run id as provenance.

Safety, in plain words:
* It refuses to run unless the database is a local `*_test` database, OR the command carries
  `--owner-approved` (the owner's explicit say-so for any other database). The refusal never prints the URL.
* It is never scheduled and no job calls it. It prints counts only.
* `--dry-run` does the work and then rolls it back, so the counts can be seen first.
* It writes only identity and ledger rows; it never touches orders, positions, signals or the brain.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from datetime import date

REFUSED = 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m swing_trade_ml.services.identity.admin", description=__doc__
    )
    parser.add_argument(
        "--owner-approved",
        action="store_true",
        help="run against a database that is not a local *_test one (the owner's explicit approval)",
    )
    parser.add_argument("--dry-run", action="store_true", help="do the work, print the counts, roll it back")
    sub = parser.add_subparsers(dest="command", required=True)
    inst = sub.add_parser("backfill-instruments", help="give every equity instrument a security")
    inst.add_argument("--exchange", default="NSE")
    scores = sub.add_parser("backfill-scores", help="copy stock_score_history into the ledger (backfill)")
    scores.add_argument("--since", type=date.fromisoformat, default=None)
    brain = sub.add_parser("brain-run", help="record one finished brain run in the ledger")
    brain.add_argument("run_id")
    return parser


def check_database(url: str, environ: dict[str, str], owner_approved: bool) -> None:
    """Raise RuntimeError (never showing the URL) unless this database may be written."""
    from swing_trade_ml.core import db_guard

    if owner_approved:
        return
    db_guard.assert_local_test_database(url)
    db_guard.assert_no_connection_overrides(environ)


def _run(args: argparse.Namespace) -> dict[str, int]:
    from swing_trade_ml.db.session import SessionLocal
    from swing_trade_ml.services.identity import ledger, writer

    db = SessionLocal()
    try:
        if args.command == "backfill-instruments":
            counts = writer.backfill_instruments(db, exchange=args.exchange)
        elif args.command == "backfill-scores":
            counts = ledger.backfill_from_stock_scores(db, since=args.since)
        else:
            counts = {"written": ledger.append_from_brain_run(db, args.run_id)}
        if args.dry_run:
            db.rollback()
        else:
            db.commit()
        return counts
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main(
    argv: Sequence[str] | None = None,
    *,
    database_url: str | None = None,
    environ: dict[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if database_url is None:
        from swing_trade_ml.core.config import settings

        database_url = settings.DATABASE_URL
    try:
        check_database(database_url, dict(os.environ if environ is None else environ), args.owner_approved)
    except RuntimeError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return REFUSED
    counts = _run(args)
    if counts.get("skipped"):
        print(
            f"warning: {counts['skipped']} row(s) were skipped because the stock's symbol belongs to a "
            "different company; nothing was guessed. They need a manual look."
        )
    suffix = " (dry run: nothing was saved)" if args.dry_run else ""
    print(f"{args.command}: " + ", ".join(f"{k}={v}" for k, v in counts.items()) + suffix)
    return 0


if __name__ == "__main__":
    sys.exit(main())
