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

// Real Zerodha equity holdings — a direct pass-through from Kite, not
// anything the bot tracks or predicts. Distinct from DetailedPosition,
// which is the bot's own paper-mode trades and knows nothing about
// anything bought manually in the real account.
export interface Holding {
  symbol: string
  exchange: string
  quantity: number
  average_price: number
  last_price: number
  close_price: number | null
  pnl: number
  day_change: number | null
  day_change_percentage: number | null
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
  strategy_name: string | null
  cap_tier: string | null
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

// Note: named TrackRecordSignal, not ScanResult, because ScanResult is
// already taken (below) by the /strategies/scan-all response shape — this
// is the per-signal row behind the "Scan Results" tab (see
// docs/superpowers/specs/2026-09-12-signal-track-record-design.md).
export interface TrackRecordSignal {
  signal_id: number
  symbol: string
  name: string | null
  cap_tier: 'large' | 'midcap' | 'smallcap'
  strategy_name: string
  mode: 'paper' | 'real'
  generated_at: string
  age_days: number
  price: number
  stop_loss: number
  take_profit: number
  current_price: number | null
  confidence: number | null
  outcome: 'TARGET_HIT' | 'STOP_LOSS_HIT' | 'EXPIRED_NO_HIT' | null
  outcome_pct: number | null
  outcome_at: string | null
  was_executed: boolean
  reason: string | null
  trade_net_pnl: number | null
  trade_return_pct: number | null
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
  strategy_name: string | null
  cap_tier: string | null
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

export interface StrategyPerformanceWindow {
  trades: number
  win_rate: number
  profit_factor: number
  net_pnl: number
}

export interface StrategyPerformance {
  id: number
  name: string
  strategy_type: string
  execution_mode: 'auto' | 'advisory'
  cap_tier: 'large' | 'midcap' | 'smallcap'
  is_active: boolean
  universe_size: number
  open_positions: number
  windows: {
    last_30d: StrategyPerformanceWindow
    last_90d: StrategyPerformanceWindow
    all_time: StrategyPerformanceWindow
  }
}

export interface StrategyPerformanceResponse {
  strategies: StrategyPerformance[]
  recommended_strategy_id: number | null
  recommendation_reason: string
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
  label_kind?: string
  stop_return_pct?: number | null
  metrics?: { walk_forward?: WalkForwardFold[] } & Record<string, unknown>
}

/** One successive train/test window from ml/train.py::walk_forward. The
 * headline number is precision at the confidence threshold: of the calls the
 * model was confident enough to act on, how many worked out. */
export interface WalkForwardFold {
  fold: number
  skipped: boolean
  reason?: string
  n_train: number
  n_test: number
  train_start: string
  train_end: string
  test_start: string
  test_end: string
  metrics: {
    roc_auc?: number
    accuracy?: number
    threshold?: number
    precision_at_threshold?: number
    confident_signal_count?: number
  }
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

export interface MutualFundSearchResult {
  scheme_id: number
  scheme_code: string
  name: string
  amc_name: string | null
  category: string | null
  is_tracked: boolean
}

export interface MutualFundHolding {
  id: number
  scheme_id: number
  scheme_name: string
  category: string | null
  units: number
  purchase_nav: number
  purchase_date: string
  latest_nav: number | null
  current_value: number | null
  cost_basis: number
  absolute_return: number | null
  absolute_return_pct: number | null
  annualized_return_pct: number | null
  volatility: number | null
  max_drawdown: number | null
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
  mutual_funds_value: number
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

// ------------------------------------------------------------- risk layer --

export interface SectorExposure {
  sector: string
  value_inr: number
  pct_of_portfolio: number
}

export interface CurrentLimits {
  portfolio_value: number
  cash: number
  rung_value: number
  max_positions: number
  open_positions: number
  max_position_pct: number
  min_position_inr: number
  sector_rule: string
  sector_cap_pct: number | null
  max_adv_pct: number | null
  scale_out_enabled: boolean
  max_share_price_inr: number | null
  allowed_cap_tiers: string[]
  small_cap_budget_pct: number | null
  cash_floor_inr: number
  risk_per_trade_pct: number
  max_drawdown_pct: number
  regime: string
  plain_regime: string
  deployable_fraction: number
  deployable_ceiling_inr: number
  invested_inr: number
  room_inr: number
  sectors: SectorExposure[]
}

export interface SystemState {
  new_entries_enabled: boolean
  exits_enabled: boolean
  halt_reason: string | null
  halted_at: string | null
  halted_by: string | null
}

export interface RiskEvent {
  id: number
  ts: string
  mode: string
  strategy_id: number | null
  instrument_id: number | null
  symbol: string | null
  rule: string
  reason: string
  amount_inr: number | null
}

// ------------------------------------------------------------ calibration --

export interface CalibrationBucket {
  lower: number
  upper: number
  n: number
  wins: number
  observed_rate: number | null
  mean_confidence: number | null
  calibration_gap: number | null
  mean_outcome_pct: number | null
  worst_outcome_pct: number | null
  meaningful: boolean
}

export interface CalibrationReport {
  source: string
  mode: string | null
  strategy_id: number | null
  since: string | null
  model_id: number | null
  label_kind: string | null
  total_scored: number
  excluded_below_min: number
  brier_score: number | null
  buckets: CalibrationBucket[]
}

// ---- Real Zerodha buy & sell report --------------------------------------
export interface RealReportSummary {
  bought_value: number
  sold_value: number
  buy_count: number
  sell_count: number
  realized_pnl: number
  gross_pnl: number
  charges: number
  winning_sales: number
  losing_sales: number
  average_holding_days: number | null
  best_stock: { symbol: string; pnl: number } | null
  worst_stock: { symbol: string; pnl: number } | null
  open_pnl: number | null
  open_value: number | null
  open_invested: number | null
}

export interface RealReportStock {
  symbol: string
  bought_qty: number
  bought_value: number
  sold_qty: number
  sold_value: number
  realized_pnl: number
  open_qty: number
  open_avg_price: number | null
  last_price: number | null
  open_pnl: number | null
}

export interface RealReportSale {
  symbol: string
  quantity: number
  buy_date: string
  sell_date: string
  buy_price: number
  sell_price: number
  gross_pnl: number
  charges: number
  net_pnl: number
  pnl_pct: number
  holding_days: number
}

export interface RealReportFill {
  id: number
  symbol: string
  side: 'BUY' | 'SELL'
  quantity: number
  price: number
  value: number
  executed_at: string
  source: 'api' | 'csv'
}

export interface RealReport {
  summary: RealReportSummary
  by_stock: RealReportStock[]
  closed: RealReportSale[]
  unmatched_sales: { symbol: string; quantity: number; sell_date: string; sell_price: number }[]
  fills: RealReportFill[]
  records: { total_fills: number; first_at: string | null; last_at: string | null }
  holdings_note: string | null
}
