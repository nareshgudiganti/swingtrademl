"""Operational CLI — the setup and maintenance tasks that are awkward over HTTP.

swingtrade init-db
swingtrade create-user --username admin --password secret
swingtrade sync-instruments
swingtrade backfill --days 1825
swingtrade train --algorithm lightgbm --activate
swingtrade scan
swingtrade status
"""

from __future__ import annotations

import argparse
import sys

from swing_trade_ml.core.logging import configure_logging, get_logger

# Windows' console defaults to the system codepage (cp1252/cp437), which
# cannot encode the checkmark/cross glyphs used for CLI feedback below — that
# raises UnicodeEncodeError and makes an otherwise-successful command look
# like it crashed. Force UTF-8 on stdout/stderr regardless of platform.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

configure_logging()
log = get_logger("cli")


def cmd_init_db(args: argparse.Namespace) -> int:
    from swing_trade_ml.db.session import init_database

    init_database()
    print("✅ Database schema is up to date")
    return 0


def cmd_create_user(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from swing_trade_ml.core.security import hash_password
    from swing_trade_ml.db.models.session import User
    from swing_trade_ml.db.session import session_scope

    with session_scope() as db:
        if db.execute(select(User).where(User.username == args.username)).scalar_one_or_none():
            print(f"❌ User '{args.username}' already exists")
            return 1
        db.add(
            User(
                username=args.username,
                email=args.email,
                hashed_password=hash_password(args.password),
                is_active=True,
                is_superuser=True,
            )
        )
    print(f"✅ Created user '{args.username}'")
    return 0


def cmd_sync_instruments(args: argparse.Namespace) -> int:
    from swing_trade_ml.brokers.kite import kite_broker
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.session import session_scope
    from swing_trade_ml.services import ingestion

    with session_scope() as db:
        if not kite_broker.load_session(db):
            print("❌ No active Kite session. Log in at /api/v1/auth/kite/login first.")
            return 1
        count = ingestion.sync_instruments(db, args.exchange)
        matched = ingestion.set_watchlist(db, settings.watchlist, args.exchange)

    print(f"✅ Synced {count} instruments; watchlist set to {len(matched)} symbols")
    print(f"   {', '.join(matched)}")
    return 0


def cmd_backfill(args: argparse.Namespace) -> int:
    from swing_trade_ml.brokers.kite import kite_broker
    from swing_trade_ml.db.session import session_scope
    from swing_trade_ml.services import ingestion

    with session_scope() as db:
        if not kite_broker.load_session(db):
            print("❌ No active Kite session. Log in at /api/v1/auth/kite/login first.")
            return 1
        results = ingestion.backfill_watchlist(
            db, interval=args.interval, days=args.days, incremental=not args.full
        )

    total = sum(results.values())
    print(f"✅ Ingested {total:,} candles across {len(results)} symbols")
    for symbol, count in sorted(results.items()):
        print(f"   {symbol:<14} {count:>7,}")
    return 0


def cmd_train(args: argparse.Namespace) -> int:
    from swing_trade_ml.db.session import session_scope
    from swing_trade_ml.ml.train import train_model

    with session_scope() as db:
        try:
            model = train_model(
                db,
                name=args.name,
                algorithm=args.algorithm,
                interval=args.interval,
                horizon_days=args.horizon_days,
                target_return=args.target_return,
                auto_activate=args.activate,
            )
        except ValueError as exc:
            print(f"❌ {exc}")
            return 1

        print(f"✅ Trained {model.name}:{model.version} ({model.algorithm})")
        print(f"   horizon/target   {model.prediction_horizon_days}d / +{model.target_return_pct:.1%}")
        print(f"   samples          {model.n_samples:,}")
        print(f"   accuracy         {model.accuracy:.4f}")
        print(f"   precision        {model.precision:.4f}")
        print(f"   recall           {model.recall:.4f}")
        print(f"   ROC AUC          {model.roc_auc:.4f}")
        print(
            f"   precision @ {model.metrics.get('threshold', 0):.2f}  "
            f"{model.metrics.get('precision_at_threshold', 0):.4f}"
        )
        print(f"   status           {model.status}")
        if not args.activate:
            print(f"\n   Activate it with: POST /api/v1/ml/models/{model.id}/activate")

        top = list(model.feature_importance.items())[:10]
        if top:
            print("\n   Top features:")
            for name, value in top:
                print(f"     {name:<22} {value:.4f}")
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    from swing_trade_ml.db.session import session_scope
    from swing_trade_ml.services import engine

    with session_scope() as db:
        result = engine.run_all_active(db, interval=args.interval)

    print("✅ Scan complete")
    print(f"   strategies   {result.strategies_run}")
    print(f"   evaluated    {result.instruments_evaluated}")
    print(f"   signals      {result.signals_generated}  (buys {result.buys}, exits {result.exits})")
    print(f"   executed     {result.executed}")
    if result.errors:
        print(f"   errors       {len(result.errors)}")
        for err in result.errors[:10]:
            print(f"     • {err}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    from swing_trade_ml.brokers import get_broker
    from swing_trade_ml.core.config import settings
    from swing_trade_ml.db.session import check_connection, session_scope
    from swing_trade_ml.ml.registry import get_active_model
    from swing_trade_ml.services import portfolio

    print(f"App              {settings.APP_NAME}")
    print(f"Environment      {settings.ENVIRONMENT}")
    print(f"Trading mode     {get_broker().mode.upper()}")
    print(f"Live enabled     {settings.is_live_trading}")
    print(f"Database         {'reachable' if check_connection() else 'UNREACHABLE'}")
    print(f"Kite configured  {settings.kite_configured}")
    print(f"Telegram         {'enabled' if settings.TELEGRAM_ENABLED else 'disabled'}")

    if not check_connection():
        return 1

    with session_scope() as db:
        model = get_active_model(db)
        print(f"Active model     {f'{model.name}:{model.version}' if model else 'none'}")
        stats = portfolio.performance_stats(db)
        print()
        print(f"Portfolio value  ₹{stats['total_value']:,.2f}")
        print(f"Cash             ₹{stats['cash']:,.2f}")
        print(f"Total P&L        ₹{stats['total_pnl']:,.2f}  ({stats['total_return_pct']:+.2%})")
        print(f"Open positions   {stats['open_positions']}")
        print(f"Closed trades    {stats['total_trades']}  (win rate {stats['win_rate']:.1%})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="swingtrade", description="Swing Trade ML operations")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="Create or migrate the database schema").set_defaults(func=cmd_init_db)

    p = sub.add_parser("create-user", help="Create a dashboard login")
    p.add_argument("--username", required=True)
    p.add_argument("--password", required=True)
    p.add_argument("--email", default=None)
    p.set_defaults(func=cmd_create_user)

    p = sub.add_parser("sync-instruments", help="Refresh the instrument master from Kite")
    p.add_argument("--exchange", default="NSE")
    p.set_defaults(func=cmd_sync_instruments)

    p = sub.add_parser("backfill", help="Download historical candles")
    p.add_argument("--interval", default="day")
    p.add_argument("--days", type=int, default=None)
    p.add_argument("--full", action="store_true", help="Re-fetch everything, not just the gap")
    p.set_defaults(func=cmd_backfill)

    p = sub.add_parser("train", help="Train a model")
    p.add_argument("--name", default="swing_classifier")
    p.add_argument(
        "--algorithm",
        default="lightgbm",
        choices=["lightgbm", "random_forest", "gradient_boosting", "logistic_regression"],
    )
    p.add_argument("--interval", default="day")
    p.add_argument(
        "--horizon-days",
        type=int,
        default=None,
        help="Prediction horizon in trading days (default: settings.ML_PREDICTION_HORIZON_DAYS)",
    )
    p.add_argument(
        "--target-return",
        type=float,
        default=None,
        help="Forward return threshold for a positive label, e.g. 0.02 for 2%% "
        "(default: settings.ML_TARGET_RETURN_PCT)",
    )
    p.add_argument("--activate", action="store_true", help="Promote to ACTIVE after training")
    p.set_defaults(func=cmd_train)

    p = sub.add_parser("scan", help="Run all active strategies now")
    p.add_argument("--interval", default="day")
    p.set_defaults(func=cmd_scan)

    sub.add_parser("status", help="Show system and portfolio status").set_defaults(func=cmd_status)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        log.error("cli.failed", command=args.command, error=str(exc))
        print(f"❌ {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
