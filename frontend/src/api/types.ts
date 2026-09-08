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

export interface KiteLoginResponse {
  login_url: string
  instructions: string
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
  latest_candle_date: string | null
  last_scan_at: string | null
  last_scan_result: {
    ts: string
    strategies_run: number
    instruments_evaluated: number
    signals_generated: number
    buys: number
    exits: number
    executed: number
    errors: number
  } | null
  status_level: 'ok' | 'warning'
  status_message: string
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
  // Today's move only — vs. yesterday's close, or vs. entry price if bought
  // today. Null when there's no previous close to compare against yet
  // (brand-new symbol, no history).
  day_pnl: number | null
  stop_loss: number | null
  take_profit: number | null
  entry_at: string
  holding_days: number
  strategy_id: number | null
  entry_confidence: number | null
  last_confidence: number | null
  horizon_days: number | null
  action_code: 'exit' | 'alert' | 'weak' | 'dip' | 'bullish' | 'hold'
  action_label: string
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

// Shape returned by GET /strategies/{id}/signals — every signal from a scan
// (BUY/HOLD/EXIT alike), symbol-resolved. Distinct from LatestSignal, which
// is the cross-strategy "recent actionable signals" feed and excludes HOLD.
// One row per symbol, deduped to its single most recent signal, kept only
// when that signal is still BUY — see GET /signals/buy-list. If it's on this
// list, it's a fresh, currently-valid entry candidate, full stop.
export interface BuyListRow {
  symbol: string
  name: string | null
  strategy_name: string
  price: number
  confidence: number | null
  stop_loss: number | null
  take_profit: number | null
  reason: string | null
  generated_at: string
}

/** Stored market candle used for short-term price-performance summaries. */
export interface Candle {
  ts: string
  open: number
  high: number
  low: number
  close: number
  volume: number | null
}

export interface StrategySignal {
  id: number
  strategy_id: number
  instrument_id: number
  tradingsymbol: string
  name: string
  signal_type: SignalType
  mode: TradingMode
  price: number
  confidence: number | null
  suggested_quantity: number | null
  stop_loss: number | null
  take_profit: number | null
  reason: string | null
  // The model's actual technical readout at scoring time — see ml_swing.py's
  // evaluate(). Shape is stable in practice (every ml_swing signal carries
  // the same keys) but not schema-enforced, hence the loose typing.
  features: {
    probability?: number
    atr_14?: number
    avg_volume_20?: number
    daily_volatility_20?: number
    model?: string
    threshold?: number
    bear_market?: boolean
    return_5d?: number
  } | null
  was_executed: boolean
  rejection_reason: string | null
  advisory_only: boolean
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
  exit_reason_label: string | null
  is_win: boolean
  stop_loss: number | null
  take_profit: number | null
  entry_confidence: number | null
  last_confidence: number | null
  // How the stock moved after we sold it — null until enough trading days
  // have passed since exit_at for that checkpoint to exist yet.
  price_5d_after_exit: number | null
  return_5d_after_exit: number | null
  price_15d_after_exit: number | null
  return_15d_after_exit: number | null
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
  max_daily_buys: number | null
  execution_mode: 'auto' | 'advisory'
  allow_pyramiding: boolean
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

// --------------------------------------------------------------- finance --

export type FinanceDirection = 'DEBIT' | 'CREDIT' | 'UNKNOWN'
export type FinanceSourceType = 'phonepe_pdf' | 'icici_pdf' | 'csv'

/** The shared scope for Overview/Transactions/Net Worth — see Finance.tsx. */
export interface FinanceFilters {
  month?: string
  category?: string
  direction?: string
}

export interface FinanceTransaction {
  id: number
  txn_date: string
  month: string
  description: string
  amount: number
  direction: FinanceDirection
  status: string | null
  transaction_id: string | null
  source: string | null
  category: string
  is_manual_override: boolean
  is_reference_only: boolean
}

export interface FinanceIngestResult {
  file_name: string
  source_type: FinanceSourceType
  already_imported: boolean
  transactions_parsed: number
  transactions_imported: number
  duplicates_skipped: number
  message: string
}

export interface FinanceIngestedFile {
  id: number
  file_name: string
  source_type: FinanceSourceType
  status: string
  transaction_count: number
  message: string | null
  created_at: string
  deleted_at: string | null
}

export interface FinanceCalculationSummary {
  total_debits: number
  total_credits: number
  net: number
  transaction_count: number
}

export interface FinanceMonthlySummary {
  month: string
  total_expense: number
  transaction_count: number
  avg_transaction: number
}

export interface FinanceCategorySummary {
  category: string
  total_expense: number
  transaction_count: number
  avg_transaction: number
}

export interface FinanceMonthlyCategorySummary {
  month: string
  category: string
  total_expense: number
  transaction_count: number
}

export interface FinanceMerchantSummary {
  description: string
  total_expense: number
  transaction_count: number
}

export interface FinanceLoan {
  id: number
  account_number: string | null
  name: string
  principal: number
  annual_rate: number
  tenure_months: number
  emi: number
  extra_payment: number
  start_date: string
  outstanding: number
  scheduled_end: string
  estimated_close: string | null
  scheduled_pending_label: string
  pending_label: string
  monthly_interest: number
  yearly_interest: number
  total_interest: number
  estimated_interest: number
  interest_saved: number
  total_payable: number
}

// A monthly bill template, resolved against one month (default: the current
// one) — paid_this_month/amount_this_month/paid_at describe that month only,
// not the bill's whole history.
export interface FinanceRecurringBill {
  id: number
  name: string
  category: string | null
  default_amount: number
  is_active: boolean
  paid_this_month: boolean
  amount_this_month: number | null
  paid_at: string | null
}

export interface FinanceDailyCategory {
  id: number
  name: string
  is_active: boolean
}

export interface FinanceNetWorth {
  income_total: number
  expense_total: number
  cash_surplus: number
  investments_total: number
  liabilities: number
  net_worth: number
}

export interface FinanceCustomRule {
  id: number
  keyword: string
  category: string
  priority: number
}

export interface FinanceRuleUpsertResult {
  rule: FinanceCustomRule
  recategorized_count: number
}

export interface FinanceRecategorizeResult {
  recategorized_count: number
}
