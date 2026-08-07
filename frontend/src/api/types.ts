// Mirrors the Pydantic schemas in backend/src/swing_trade_ml/schemas/__init__.py.
// Kept hand-written rather than generated so the dashboard depends on a stable
// subset of the API rather than on every field the backend happens to expose.

export type TradingMode = 'paper' | 'live'
export type SignalType = 'BUY' | 'SELL' | 'HOLD' | 'EXIT'

export interface CurrentUser {
  id: number
  username: string
  email: string | null
  auth_provider: 'local' | 'google'
  is_superuser: boolean
}

export interface SystemStatus {
  app: string
  environment: string
  trading_mode: TradingMode
  live_trading_enabled: boolean
  broker_authenticated: boolean
  scheduler_running: boolean
  scheduled_jobs: ScheduledJob[]
  telegram_enabled: boolean
  active_model: string | null
  watchlist_size: number
  active_strategies: number
  open_positions: number
}

export interface ScheduledJob {
  id: string
  name: string
  trigger: string
  next_run: string | null
}

export interface PortfolioSummary {
  mode: TradingMode
  starting_capital: number
  total_value: number
  cash: number
  holdings_value: number
  realized_pnl: number
  unrealized_pnl: number
  total_pnl: number
  total_return_pct: number
  open_positions: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  avg_win: number
  avg_loss: number
  profit_factor: number
  avg_holding_days: number
  expectancy: number
  total_charges: number
  max_drawdown_pct: number
  current_drawdown_pct: number
  day_pnl: number
  day_pnl_pct: number
  sharpe_ratio: number
  sortino_ratio: number
  top_movers: { symbol: string; pnl: number; pnl_pct: number }[]
}

export interface DetailedPosition {
  id: number
  symbol: string
  name: string | null
  quantity: number
  entry_price: number
  current_price: number
  invested: number
  current_value: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  stop_loss: number | null
  take_profit: number | null
  entry_at: string
  holding_days: number
  strategy_id: number | null
  entry_confidence: number | null
  last_confidence: number | null
  horizon_days: number | null
}

export interface LatestSignal {
  id: number
  symbol: string
  name: string | null
  signal: SignalType
  price: number
  confidence: number | null
  quantity: number | null
  stop_loss: number | null
  take_profit: number | null
  reason: string | null
  executed: boolean
  advisory_only: boolean
  rejection_reason: string | null
  generated_at: string
}

export interface Trade {
  id: number
  symbol: string
  mode: TradingMode
  quantity: number
  entry_price: number
  exit_price: number
  entry_at: string
  exit_at: string
  holding_days: number
  gross_pnl: number
  charges: number
  net_pnl: number
  return_pct: number
  exit_reason: string | null
  is_win: boolean
}

export interface EquityPoint {
  date: string
  total_value: number
  cash: number
  holdings_value: number
  day_pnl: number
  drawdown_pct: number
  open_positions: number
}

export interface Strategy {
  id: number
  name: string
  description: string | null
  strategy_type: string
  params: Record<string, unknown>
  symbols: string[]
  is_active: boolean
  mode: TradingMode
  max_positions: number | null
  capital_allocation: number | null
  stop_loss_pct: number | null
  take_profit_pct: number | null
  created_at: string
}

export interface StrategyType {
  strategy_type: string
  display_name: string
  description: string
  default_params: Record<string, unknown>
}

export interface MLModel {
  id: number
  name: string
  version: string
  algorithm: string
  status: string
  n_samples: number | null
  prediction_horizon_days: number
  target_return_pct: number
  accuracy: number | null
  precision: number | null
  recall: number | null
  f1_score: number | null
  roc_auc: number | null
  training_symbols: string[]
  train_start: string | null
  train_end: string | null
  trained_at: string | null
  activated_at: string | null
}

export interface Instrument {
  id: number
  instrument_token: number
  tradingsymbol: string
  name: string | null
  exchange: string
  instrument_type: string | null
  lot_size: number
  tick_size: number
  is_watchlisted: boolean
  is_active: boolean
}

export interface PredictionRun {
  symbol: string
  instrument_id: number
  probability: number
  predicted_class: number
  price: number
  ts: string
}

export interface HorizonAccuracy {
  horizon_days: number
  target_return: number
  total_predictions: number
  evaluable: number
  correct: number
  accuracy: number
  avg_actual_return: number
}

export interface Prediction {
  id: number
  model_id: number
  instrument_id: number
  symbol: string
  ts: string
  predicted_class: number
  probability: number
  price_at_prediction: number
  actual_return: number | null
  was_correct: boolean | null
  evaluated_at: string | null
}

export interface MarketRegime {
  regime: 'bullish' | 'bearish' | 'unknown'
  volatility_level: 'elevated' | 'normal' | 'low' | 'unknown'
  nifty_close: number | null
  sma_50: number | null
  sma_200: number | null
  as_of: string | null
}

export interface ScanResult {
  strategies_run: number
  instruments_evaluated: number
  signals_generated: number
  buys: number
  exits: number
  executed: number
  errors: string[]
}

export interface MessageResponse {
  message: string
  detail: string | null
}
