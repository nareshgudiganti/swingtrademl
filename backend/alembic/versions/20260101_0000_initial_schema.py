"""Initial schema — instruments, market data, trading, ML registry.

Revision ID: 0001_initial
Revises:
Create Date: 2026-01-01 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ---------------------------------------------------------- instruments --
    op.create_table(
        "instruments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_token", sa.BigInteger(), nullable=False),
        sa.Column("exchange_token", sa.BigInteger(), nullable=True),
        sa.Column("tradingsymbol", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=True),
        sa.Column("exchange", sa.String(length=16), nullable=False),
        sa.Column("segment", sa.String(length=32), nullable=True),
        sa.Column("instrument_type", sa.String(length=16), nullable=True),
        sa.Column("lot_size", sa.Integer(), nullable=False),
        sa.Column("tick_size", sa.Float(), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=True),
        sa.Column("is_watchlisted", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_instruments")),
        sa.UniqueConstraint("exchange", "tradingsymbol", name="uq_instruments_exchange_symbol"),
    )
    op.create_index(op.f("ix_instruments_instrument_token"), "instruments", ["instrument_token"], unique=True)
    op.create_index(op.f("ix_instruments_tradingsymbol"), "instruments", ["tradingsymbol"])
    op.create_index(op.f("ix_instruments_exchange"), "instruments", ["exchange"])
    op.create_index(op.f("ix_instruments_is_watchlisted"), "instruments", ["is_watchlisted"])

    # -------------------------------------------------------------- candles --
    # The primary key is the natural key and deliberately includes `ts`:
    # TimescaleDB refuses to promote a table whose unique indexes do not contain
    # the partitioning column. A surrogate `id` PK here would make the
    # hypertable impossible. It also serves the dominant read pattern
    # ("last N bars of one interval for one instrument"), so no separate
    # composite index is needed.
    op.create_table(
        "candles",
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("interval", sa.Text(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.ForeignKeyConstraint(
            ["instrument_id"],
            ["instruments.id"],
            name=op.f("fk_candles_instrument_id_instruments"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("instrument_id", "interval", "ts", name=op.f("pk_candles")),
    )
    op.create_index("ix_candles_ts", "candles", ["ts"])

    # Promote `candles` to a TimescaleDB hypertable. This is the one table that
    # grows without bound — a 10-symbol watchlist at 15-minute bars is ~250k
    # rows a year, and adding instruments or intervals multiplies that fast.
    # Chunking by time keeps range queries reading only the relevant partitions.
    #
    # Only a missing extension is tolerated (stock Postgres works fine, just
    # unpartitioned). Any other failure is re-raised: a silently skipped
    # promotion looks exactly like success and is not discovered until the table
    # is far too large to convert conveniently.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
                RAISE NOTICE 'TimescaleDB not installed — candles stays a plain table.';
                RETURN;
            END IF;

            PERFORM create_hypertable(
                'candles', 'ts',
                chunk_time_interval => INTERVAL '1 month',
                if_not_exists => TRUE,
                migrate_data => TRUE
            );
        END $$;
        """
    )

    # --------------------------------------------------------------- quotes --
    op.create_table(
        "quotes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("last_price", sa.Float(), nullable=False),
        sa.Column("open", sa.Float(), nullable=True),
        sa.Column("high", sa.Float(), nullable=True),
        sa.Column("low", sa.Float(), nullable=True),
        sa.Column("close", sa.Float(), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("change_pct", sa.Float(), nullable=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name=op.f("fk_quotes_instrument_id_instruments"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_quotes")),
    )
    op.create_index(op.f("ix_quotes_instrument_id"), "quotes", ["instrument_id"], unique=True)

    # ---------------------------------------------------------------- users --
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("is_superuser", sa.Boolean(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_username"), "users", ["username"], unique=True)

    # ------------------------------------------------------- broker_sessions --
    op.create_table(
        "broker_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("broker", sa.String(length=32), nullable=False),
        sa.Column("kite_user_id", sa.String(length=64), nullable=True),
        sa.Column("user_name", sa.String(length=128), nullable=True),
        sa.Column("access_token", sa.String(length=512), nullable=False),
        sa.Column("public_token", sa.String(length=512), nullable=True),
        sa.Column("refresh_token", sa.String(length=512), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_broker_sessions")),
    )
    op.create_index(op.f("ix_broker_sessions_broker"), "broker_sessions", ["broker"])
    op.create_index(op.f("ix_broker_sessions_is_active"), "broker_sessions", ["is_active"])

    # ----------------------------------------------------------- strategies --
    op.create_table(
        "strategies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("strategy_type", sa.String(length=64), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("symbols", sa.JSON(), nullable=True),
        sa.Column("max_positions", sa.Integer(), nullable=True),
        sa.Column("capital_allocation", sa.Float(), nullable=True),
        sa.Column("stop_loss_pct", sa.Float(), nullable=True),
        sa.Column("take_profit_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_strategies")),
    )
    op.create_index(op.f("ix_strategies_name"), "strategies", ["name"], unique=True)
    op.create_index(op.f("ix_strategies_strategy_type"), "strategies", ["strategy_type"])
    op.create_index(op.f("ix_strategies_is_active"), "strategies", ["is_active"])
    op.create_index(op.f("ix_strategies_mode"), "strategies", ["mode"])

    # -------------------------------------------------------------- signals --
    op.create_table(
        "signals",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("signal_type", sa.String(length=8), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("suggested_quantity", sa.Integer(), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("was_executed", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], name=op.f("fk_signals_strategy_id_strategies"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name=op.f("fk_signals_instrument_id_instruments"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_signals")),
    )
    op.create_index(op.f("ix_signals_strategy_id"), "signals", ["strategy_id"])
    op.create_index(op.f("ix_signals_instrument_id"), "signals", ["instrument_id"])
    op.create_index(op.f("ix_signals_signal_type"), "signals", ["signal_type"])
    op.create_index(op.f("ix_signals_mode"), "signals", ["mode"])
    op.create_index(op.f("ix_signals_was_executed"), "signals", ["was_executed"])
    op.create_index(op.f("ix_signals_generated_at"), "signals", ["generated_at"])
    op.create_index("ix_signals_scan", "signals", ["mode", "signal_type", "generated_at"])

    # ------------------------------------------------------------ positions --
    op.create_table(
        "positions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=True),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_reason", sa.String(length=24), nullable=True),
        sa.Column("stop_loss", sa.Float(), nullable=True),
        sa.Column("take_profit", sa.Float(), nullable=True),
        sa.Column("highest_price", sa.Float(), nullable=True),
        sa.Column("current_price", sa.Float(), nullable=True),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=True),
        sa.Column("total_charges", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], name=op.f("fk_positions_strategy_id_strategies"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name=op.f("fk_positions_instrument_id_instruments"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_positions")),
    )
    op.create_index(op.f("ix_positions_strategy_id"), "positions", ["strategy_id"])
    op.create_index(op.f("ix_positions_instrument_id"), "positions", ["instrument_id"])
    op.create_index(op.f("ix_positions_mode"), "positions", ["mode"])
    op.create_index(op.f("ix_positions_status"), "positions", ["status"])
    op.create_index(op.f("ix_positions_entry_at"), "positions", ["entry_at"])
    op.create_index("ix_positions_open", "positions", ["mode", "status", "instrument_id"])

    # --------------------------------------------------------------- orders --
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("signal_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("position_id", sa.BigInteger(), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("broker_order_id", sa.String(length=64), nullable=True),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("transaction_type", sa.String(length=8), nullable=False),
        sa.Column("order_type", sa.String(length=8), nullable=False),
        sa.Column("product", sa.String(length=8), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("filled_quantity", sa.Integer(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("trigger_price", sa.Float(), nullable=True),
        sa.Column("average_price", sa.Float(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("status_message", sa.Text(), nullable=True),
        sa.Column("brokerage", sa.Float(), nullable=False),
        sa.Column("taxes", sa.Float(), nullable=False),
        sa.Column("slippage", sa.Float(), nullable=False),
        sa.Column("placed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["signal_id"], ["signals.id"], name=op.f("fk_orders_signal_id_signals"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], name=op.f("fk_orders_strategy_id_strategies"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"], name=op.f("fk_orders_position_id_positions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name=op.f("fk_orders_instrument_id_instruments"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
    )
    op.create_index(op.f("ix_orders_signal_id"), "orders", ["signal_id"])
    op.create_index(op.f("ix_orders_strategy_id"), "orders", ["strategy_id"])
    op.create_index(op.f("ix_orders_position_id"), "orders", ["position_id"])
    op.create_index(op.f("ix_orders_instrument_id"), "orders", ["instrument_id"])
    op.create_index(op.f("ix_orders_broker_order_id"), "orders", ["broker_order_id"])
    op.create_index(op.f("ix_orders_mode"), "orders", ["mode"])
    op.create_index(op.f("ix_orders_status"), "orders", ["status"])
    op.create_index(op.f("ix_orders_placed_at"), "orders", ["placed_at"])

    # --------------------------------------------------------------- trades --
    op.create_table(
        "trades",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("position_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy_id", sa.Integer(), nullable=True),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("symbol", sa.String(length=64), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price", sa.Float(), nullable=False),
        sa.Column("exit_price", sa.Float(), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("holding_days", sa.Integer(), nullable=False),
        sa.Column("gross_pnl", sa.Float(), nullable=False),
        sa.Column("charges", sa.Float(), nullable=False),
        sa.Column("net_pnl", sa.Float(), nullable=False),
        sa.Column("return_pct", sa.Float(), nullable=False),
        sa.Column("exit_reason", sa.String(length=24), nullable=True),
        sa.Column("is_win", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"], name=op.f("fk_trades_position_id_positions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["strategy_id"], ["strategies.id"], name=op.f("fk_trades_strategy_id_strategies"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name=op.f("fk_trades_instrument_id_instruments"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_trades")),
    )
    op.create_index(op.f("ix_trades_position_id"), "trades", ["position_id"])
    op.create_index(op.f("ix_trades_strategy_id"), "trades", ["strategy_id"])
    op.create_index(op.f("ix_trades_instrument_id"), "trades", ["instrument_id"])
    op.create_index(op.f("ix_trades_mode"), "trades", ["mode"])
    op.create_index(op.f("ix_trades_symbol"), "trades", ["symbol"])
    op.create_index(op.f("ix_trades_entry_at"), "trades", ["entry_at"])
    op.create_index(op.f("ix_trades_exit_at"), "trades", ["exit_at"])
    op.create_index(op.f("ix_trades_is_win"), "trades", ["is_win"])

    # --------------------------------------------------- portfolio_snapshots --
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("mode", sa.String(length=8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cash", sa.Float(), nullable=False),
        sa.Column("holdings_value", sa.Float(), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=False),
        sa.Column("realized_pnl", sa.Float(), nullable=False),
        sa.Column("unrealized_pnl", sa.Float(), nullable=False),
        sa.Column("day_pnl", sa.Float(), nullable=False),
        sa.Column("open_positions", sa.Integer(), nullable=False),
        sa.Column("peak_value", sa.Float(), nullable=False),
        sa.Column("drawdown_pct", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_portfolio_snapshots")),
    )
    op.create_index(op.f("ix_portfolio_snapshots_mode"), "portfolio_snapshots", ["mode"])
    op.create_index(op.f("ix_portfolio_snapshots_ts"), "portfolio_snapshots", ["ts"])
    op.create_index("ix_snapshots_mode_ts", "portfolio_snapshots", ["mode", "ts"])

    # ------------------------------------------------------------ ml_models --
    op.create_table(
        "ml_models",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("algorithm", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("artifact_path", sa.String(length=512), nullable=True),
        sa.Column("feature_names", sa.JSON(), nullable=True),
        sa.Column("hyperparameters", sa.JSON(), nullable=True),
        sa.Column("training_symbols", sa.JSON(), nullable=True),
        sa.Column("train_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("train_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("n_samples", sa.Integer(), nullable=True),
        sa.Column("prediction_horizon_days", sa.Integer(), nullable=False),
        sa.Column("target_return_pct", sa.Float(), nullable=False),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("precision", sa.Float(), nullable=True),
        sa.Column("recall", sa.Float(), nullable=True),
        sa.Column("f1_score", sa.Float(), nullable=True),
        sa.Column("roc_auc", sa.Float(), nullable=True),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("feature_importance", sa.JSON(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("trained_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ml_models")),
        sa.UniqueConstraint("name", "version", name="uq_ml_models_name_version"),
    )
    op.create_index(op.f("ix_ml_models_name"), "ml_models", ["name"])
    op.create_index(op.f("ix_ml_models_status"), "ml_models", ["status"])

    # ---------------------------------------------------------- predictions --
    op.create_table(
        "predictions",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("instrument_id", sa.Integer(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("predicted_class", sa.Integer(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("price_at_prediction", sa.Float(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=True),
        sa.Column("actual_return", sa.Float(), nullable=True),
        sa.Column("was_correct", sa.Boolean(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["model_id"], ["ml_models.id"], name=op.f("fk_predictions_model_id_ml_models"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["instrument_id"], ["instruments.id"], name=op.f("fk_predictions_instrument_id_instruments"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_predictions")),
        sa.UniqueConstraint("model_id", "instrument_id", "ts", name="uq_predictions_model_inst_ts"),
    )
    op.create_index(op.f("ix_predictions_model_id"), "predictions", ["model_id"])
    op.create_index(op.f("ix_predictions_instrument_id"), "predictions", ["instrument_id"])
    op.create_index(op.f("ix_predictions_ts"), "predictions", ["ts"])
    op.create_index(op.f("ix_predictions_was_correct"), "predictions", ["was_correct"])
    op.create_index("ix_predictions_pending_eval", "predictions", ["evaluated_at", "ts"])


def downgrade() -> None:
    # Reverse creation order so foreign keys never block a drop.
    for table in (
        "predictions",
        "ml_models",
        "portfolio_snapshots",
        "trades",
        "orders",
        "positions",
        "signals",
        "strategies",
        "broker_sessions",
        "users",
        "quotes",
        "candles",
        "instruments",
    ):
        op.drop_table(table)
