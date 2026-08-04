"""Pydantic request/response models.

Kept in one module: they are thin, and having the whole API contract readable in
a single file is worth more here than package-per-domain ceremony.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

ORM = ConfigDict(from_attributes=True)


# ------------------------------------------------------------------ system --


class HealthResponse(BaseModel):
    status: str
    app: str
    environment: str
    version: str


class ReadinessResponse(BaseModel):
    ready: bool
    database: bool
    broker_authenticated: bool
    scheduler_running: bool
    trading_mode: str
    live_trading_enabled: bool


class SystemStatus(BaseModel):
    app: str
    environment: str
    trading_mode: str
    live_trading_enabled: bool
    broker_authenticated: bool
    scheduler_running: bool
    scheduled_jobs: list[dict[str, Any]]
    telegram_enabled: bool
    active_model: str | None
    watchlist_size: int
    active_strategies: int
    open_positions: int


# -------------------------------------------------------------------- auth --


class LoginRequest(BaseModel):
    username: str
    password: str


class SignupRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8)
    email: str | None = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class CurrentUserOut(BaseModel):
    model_config = ORM
    id: int
    username: str
    email: str | None
    auth_provider: str
    is_superuser: bool


class KiteLoginResponse(BaseModel):
    login_url: str
    instructions: str


class KiteSessionResponse(BaseModel):
    model_config = ORM
    authenticated: bool
    kite_user_id: str | None = None
    user_name: str | None = None
    expires_at: datetime | None = None


# ------------------------------------------------------------- instruments --


class InstrumentOut(BaseModel):
    model_config = ORM
    id: int
    instrument_token: int
    tradingsymbol: str
    name: str | None
    exchange: str
    instrument_type: str | None
    lot_size: int
    tick_size: float
    is_watchlisted: bool
    is_active: bool


class WatchlistRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, description="NSE trading symbols")
    exchange: str = "NSE"


class BackfillRequest(BaseModel):
    symbols: list[str] | None = Field(None, description="Defaults to the whole watchlist")
    interval: str = "day"
    days: int | None = None
    incremental: bool = True


# ------------------------------------------------------------ market data --


class CandleOut(BaseModel):
    model_config = ORM
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


class QuoteOut(BaseModel):
    model_config = ORM
    instrument_id: int
    last_price: float
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    volume: int | None
    change_pct: float | None
    ts: datetime


# -------------------------------------------------------------- strategies --


class StrategyCreate(BaseModel):
    name: str
    strategy_type: str
    description: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)
    symbols: list[str] = Field(default_factory=list)
    max_positions: int | None = None
    capital_allocation: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


class StrategyUpdate(BaseModel):
    description: str | None = None
    params: dict[str, Any] | None = None
    symbols: list[str] | None = None
    is_active: bool | None = None
    max_positions: int | None = None
    capital_allocation: float | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


class StrategyOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    description: str | None
    strategy_type: str
    params: dict[str, Any]
    symbols: list[str]
    is_active: bool
    mode: str
    max_positions: int | None
    capital_allocation: float | None
    stop_loss_pct: float | None
    take_profit_pct: float | None
    created_at: datetime


class StrategyTypeInfo(BaseModel):
    strategy_type: str
    display_name: str
    description: str
    default_params: dict[str, Any]


class ScanResponse(BaseModel):
    strategies_run: int
    instruments_evaluated: int
    signals_generated: int
    buys: int
    exits: int
    executed: int
    errors: list[str]


# ----------------------------------------------------------------- signals --


class SignalOut(BaseModel):
    model_config = ORM
    id: int
    strategy_id: int
    instrument_id: int
    signal_type: str
    mode: str
    price: float
    confidence: float | None
    suggested_quantity: int | None
    stop_loss: float | None
    take_profit: float | None
    reason: str | None
    features: dict[str, Any]
    was_executed: bool
    rejection_reason: str | None
    generated_at: datetime


# ------------------------------------------------------------------ orders --


class OrderCreate(BaseModel):
    symbol: str = Field(..., description="NSE trading symbol, e.g. INFY")
    exchange: str = "NSE"
    transaction_type: str = Field(..., pattern="^(BUY|SELL)$")
    quantity: int = Field(..., gt=0)
    order_type: str = "MARKET"
    product: str = "CNC"
    price: float | None = None
    trigger_price: float | None = None


class OrderOut(BaseModel):
    model_config = ORM
    id: int
    signal_id: int | None
    strategy_id: int | None
    position_id: int | None
    instrument_id: int
    broker_order_id: str | None
    mode: str
    transaction_type: str
    order_type: str
    product: str
    quantity: int
    filled_quantity: int
    price: float | None
    average_price: float | None
    status: str
    status_message: str | None
    brokerage: float
    taxes: float
    slippage: float
    placed_at: datetime
    filled_at: datetime | None


# --------------------------------------------------------------- portfolio --


class PositionOut(BaseModel):
    model_config = ORM
    id: int
    strategy_id: int | None
    instrument_id: int
    mode: str
    status: str
    quantity: int
    entry_price: float
    entry_at: datetime
    exit_price: float | None
    exit_at: datetime | None
    exit_reason: str | None
    stop_loss: float | None
    take_profit: float | None
    current_price: float | None
    unrealized_pnl: float
    realized_pnl: float | None
    total_charges: float


class TradeOut(BaseModel):
    model_config = ORM
    id: int
    symbol: str
    mode: str
    quantity: int
    entry_price: float
    exit_price: float
    entry_at: datetime
    exit_at: datetime
    holding_days: int
    gross_pnl: float
    charges: float
    net_pnl: float
    return_pct: float
    exit_reason: str | None
    is_win: bool


class ClosePositionRequest(BaseModel):
    reason: str = "MANUAL"
    note: str | None = None


class EquityPoint(BaseModel):
    date: str
    total_value: float
    cash: float
    holdings_value: float
    day_pnl: float
    drawdown_pct: float
    open_positions: int


# ---------------------------------------------------------------------- ml --


class TrainRequest(BaseModel):
    name: str = "swing_classifier"
    algorithm: str = Field(
        "lightgbm", pattern="^(lightgbm|random_forest|gradient_boosting|logistic_regression)$"
    )
    symbols: list[str] | None = None
    interval: str = "day"
    horizon_days: int | None = None
    target_return: float | None = None
    test_size: float | None = None
    hyperparameters: dict[str, Any] | None = None
    auto_activate: bool = False


class MLModelOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    version: str
    algorithm: str
    status: str
    n_samples: int | None
    prediction_horizon_days: int
    target_return_pct: float
    accuracy: float | None
    precision: float | None
    recall: float | None
    f1_score: float | None
    roc_auc: float | None
    training_symbols: list[str]
    train_start: datetime | None
    train_end: datetime | None
    trained_at: datetime | None
    activated_at: datetime | None


class MLModelDetail(MLModelOut):
    feature_names: list[str]
    hyperparameters: dict[str, Any]
    metrics: dict[str, Any]
    feature_importance: dict[str, Any]


class PredictionOut(BaseModel):
    model_config = ORM
    id: int
    model_id: int
    instrument_id: int
    ts: datetime
    predicted_class: int
    probability: float
    price_at_prediction: float
    actual_return: float | None
    was_correct: bool | None


class PredictionRunOut(BaseModel):
    symbol: str
    instrument_id: int
    probability: float
    predicted_class: int
    price: float
    ts: datetime


# ------------------------------------------------------------ notifications --


class TelegramTestResponse(BaseModel):
    ok: bool
    bot: str | None = None
    chat_id: str | None = None
    error: str | None = None


class MessageResponse(BaseModel):
    message: str
    detail: str | None = None
