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
  plan: PlanKey
}

// ------------------------------------------------------------------ plans --

export type PlanKey = 'free' | 'pro'

/** GET /me/plan: what the signed-in person may see. `unrestricted` means the
 * whole app: the owner (unless previewing a plan), or anyone while plans are
 * switched off — `plan` is then "owner" or "all". */
export interface MyPlan {
  plan: PlanKey | 'owner' | 'all'
  unrestricted: boolean
  can_manage_plans: boolean
  plans_enabled: boolean
  brain_enabled: boolean
  previewing: boolean
  features: string[]
  limits: Partial<PlanLimits>
}

export interface PlanLimits {
  picks_per_day: number
  allowed_cap_tiers: string[]
  history_days: number
}

export interface PlanConfig {
  key: PlanKey
  name: string
  features: Record<string, boolean>
  limits: PlanLimits
}

export interface PlanCatalogue {
  features: { key: string; label: string; group: string; description: string }[]
  limits: { key: keyof PlanLimits; label: string; description: string; kind: 'int' | 'tiers' }[]
  cap_tiers: string[]
  base_model: string
}

export interface AdminUser {
  id: number
  username: string
  email: string | null
  auth_provider: string
  is_active: boolean
  is_owner: boolean
  plan: PlanKey
  last_login_at: string | null
}

export interface PlanPick {
  symbol: string
  name: string | null
  cap_tier: string
  strategy_name: string
  price: number | null
  confidence: number | null
  stop_loss: number | null
  take_profit: number | null
  horizon_days: number | null
  reason: string | null
  generated_at: string
}

export interface TopPick extends PlanPick {
  suggested_allocation_inr: number
  suggested_quantity: number
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
  /** The TradeMind brain is switched on (BRAIN_ENABLED); its page shows only then. */
  brain_enabled?: boolean
  paper_tester_enabled?: boolean
  broker_authenticated: boolean
  scheduler_running: boolean
  scheduled_jobs: ScheduledJob[]
  telegram_enabled: boolean
  active_model: string | null
  /** Every active model, one per company size, as name:version (sorted). */
  active_models?: string[]
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
    blocked?: { rule: string; count: number; reason: string }[] | null
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
  // The date these figures are measured from (the current paper trial), or
  // null when they really are all-time. Everything below is scoped to it, so
  // the UI has to say so rather than implying a lifetime record.
  measured_since: string | null
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
  sector?: string | null
  entry_confidence: number | null
  last_confidence: number | null
  /** One entry per day with a real reading, oldest first. Missing days are absent. */
  score_trail?: { date: string; score: number; band: 'strong' | 'easing' | 'weak'; model_version: string | null }[]
  score_band?: 'strong' | 'easing' | 'weak' | null
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

// ---------------------------------------------------------------- brain --
// The TradeMind brain: it only records decisions; it never places orders.

export type IdeaWord = 'TRADE' | 'WATCH' | 'WAIT' | 'AVOID'
export type HoldingWord = 'HOLD' | 'MONITOR' | 'REDUCE' | 'EXIT'
export type MarketMode = 'NORMAL' | 'DEFENSIVE' | 'NO_NEW_TRADES'
export type ModuleMode = 'on' | 'shadow' | 'off'

export interface BrainDecision {
  id: number
  run_id: string
  symbol: string
  kind: 'idea' | 'holding'
  word: IdeaWord | HoldingWord
  reasons: string[]
  entry_low: number | null
  entry_high: number | null
  target: number | null
  stop: number | null
  qty: number
  horizon_days: number
  confidence: number | null
  evidence_text: string | null
  downgraded_from: string | null
  downgrade_reason: string | null
  overruled_word: string | null
  overrule_reason: string | null
  overruled_by: string | null
  overruled_at: string | null
}

export interface BrainBanner {
  mode: MarketMode | null
  headline: string | null
}

export interface BrainQuality {
  overall: { score: number; fresh: boolean; issues: string[] } | null
  stale: string[]
}

/** queued → running → done | failed. `superseded` = an earlier run of the same
 *  day, replaced by a newer one (kept for history, left out of results). */
export type BrainRunStatus = 'queued' | 'running' | 'done' | 'failed' | 'superseded'

/** Steps finished so far while a queued run is thinking. */
export interface BrainRunProgress {
  done: number
  total: number | null
  step: string | null
}

export interface BrainRunSummary {
  run_id: string
  kind: 'nightly' | 'intraday' | 'why'
  as_of: string
  live: boolean
  started_at: string
  ms: number
  status: BrainRunStatus
  error: string | null
  progress?: BrainRunProgress | null
  banner: BrainBanner
  counts: Record<string, number>
}

/** POST /brain/runs only queues a run (the worker runs it). */
export interface BrainRunQueued {
  run_id: string
  status: BrainRunStatus
  kind: string
  book: string
  requested_at: string | null
  already_running: boolean
}

export interface BrainSector {
  sector: string
  name: string
  rank: number
  of_total: number
  strength_20d: number | null
  rotation: 'leading' | 'improving' | 'weakening' | 'lagging' | 'unknown'
}

export interface BrainSituation {
  scope: 'market' | 'sector' | 'stock'
  subject: string
  label: string
  confidence: number
  is_unknown: boolean
  suggest_defensive: boolean
  evidence: string[]
}

export interface BrainEpisode {
  label: string
  start_day: string
  end_day: string | null
  days: number | null
  nifty_change: number | null
}

export interface BrainPortfolioView {
  largest_position?: [string, number] | null
  top_sector?: [string, number] | null
  holdings_moving_together?: [string, string, number][]
}

export interface BrainWhatIf {
  symbol: string
  qty: number
  price: number
  value: number
  cash_after: number
  stock_share_after: number
  sector_name: string | null
  sector_share_after: number | null
  warnings: string[]
}

export interface BrainTrack {
  symbol: string
  opened_on: string | null
  points: { day: string; day_n: number; ret: number; status: string; reason: string; stop: number | null }[]
  band: [number, number, number, number][]
}

export interface BrainRun extends BrainRunSummary {
  book: string
  requested_at?: string | null
  finished_at?: string | null
  modules: Record<string, ModuleMode>
  quality: BrainQuality
  sectors: BrainSector[]
  situations: BrainSituation[]
  portfolio: BrainPortfolioView
  decisions: BrainDecision[]
}

export interface BrainTraceEvent {
  step: string
  module_id: string
  status: 'used' | 'shadow' | 'fallback' | 'skipped' | 'rejected'
  reason: string
  ms: number
  version: string
}

export interface BrainModuleInfo {
  id: string
  name: string
  step: string
  kind: string
  version: string
  mode: ModuleMode
  mandatory: boolean
}

export interface BrainModules {
  steps: { step: string; modules: string[] }[]
  modules: BrainModuleInfo[]
}

export interface BrainWhy {
  run_id: string
  banner: BrainBanner
  decision: BrainDecision | null
  trace: BrainTraceEvent[]
}

export interface BrainHealth {
  last_run: {
    run_id: string
    kind: string
    started_at: string
    status: string
    ms: number
    error: string | null
  } | null
  last_nightly_ok: string | null
  failed_runs_7d: number
  data: { score: number | null; fresh: boolean | null; issues: string[] }
  stale_count: number
}

export interface BrainAlertPreview {
  items: { key: string; kind: string; symbol: string | null; text: string }[]
  text: string | null
}

export interface BrainAlertSend {
  sent: boolean
  count: number
  text: string | null
}

// -------------------------------------------------------- brain: learning --
// M09 learning loop: a read-only report on how the brain's past ideas
// actually worked out, plus proposals it wants the owner's permission to
// act on (constitution C9 — nothing changes until Accept is pressed).

export interface BrainLearningBand {
  band: string
  n: number
  /** Average confidence the brain carried in this band, 0..1. */
  said: number
  /** Share that actually hit target, 0..1. */
  hit: number
  /** Average outcome in R (return ÷ the 4% risked). */
  avg_r: number
}

export interface BrainLearningWord {
  word: string
  n: number
  hit: number
  avg_r: number
}

export interface BrainLearningWeek {
  week: string
  n: number
  hit: number
  avg_r: number
}

export interface BrainDrift {
  feature: string
  psi: number
  level: 'stable' | 'moderate' | 'major'
}

export interface BrainLearning {
  since: string | null
  n_scored: number
  by_band: BrainLearningBand[]
  by_word: BrainLearningWord[]
  by_week: BrainLearningWeek[]
  failures: string[]
  drift: BrainDrift[]
  drift_lines: string[]
  drift_note: string | null
  note: string | null
}

export type BrainProposalStatus = 'open' | 'accepted' | 'dismissed'

export interface BrainProposal {
  id: number
  kind: string
  title: string
  evidence: string
  change: Record<string, unknown>
  status: BrainProposalStatus
  created_at: string
  decided_by: string | null
  decided_at: string | null
  decided_note: string | null
}

// M18 go-live: the brain beside version 1, scored the same way.
export interface BrainCompareSummary {
  ideas: number
  finished: number
  hit_rate: number | null
  stopped: number | null
  avg_outcome_pct: number | null
}

export interface BrainCompareStrategy extends BrainCompareSummary {
  name: string
  is_brain: boolean
}

export interface BrainCompareWeek {
  week: string
  brain: BrainCompareSummary
  version1: BrainCompareSummary
}

export interface BrainCompare {
  days: number
  first_day: string | null
  last_day: string | null
  strategies: BrainCompareStrategy[]
  brain: BrainCompareSummary
  version1: BrainCompareSummary
  by_week: BrainCompareWeek[]
  note: string
  brain_finished: number
  needed: number
}

export type BrainStageName = 'shadow' | 'approval' | 'auto'

export interface BrainStageChange {
  stage: BrainStageName
  previous_stage: BrainStageName
  changed_by: string
  reason: string
  changed_at: string
}

export interface BrainStage {
  stage: BrainStageName
  plain: string
  finished: number
  needed: number
  ready: boolean
  history: BrainStageChange[]
}

export type BrainApprovalStatus = 'pending' | 'waiting' | 'approved' | 'rejected' | 'expired'

export interface BrainApproval {
  id: number
  symbol: string
  decision_day: string
  price: number
  stop_loss: number | null
  take_profit: number | null
  suggested_qty: number | null
  reason: string
  status: BrainApprovalStatus
  status_plain: string
  decided_by: string | null
  decided_at: string | null
  decided_note: string | null
  position_id: number | null
  result_note: string | null
  created_at: string | null
  valid_until: string | null
}

/** The app's one market clock (GET /market/session). */
export interface MarketSession {
  state: 'pre_open' | 'open' | 'closed' | 'weekend' | 'holiday'
  plain: string
  trading_day: boolean
  opens_at: string | null
  closes_at: string | null
  next_open: string
  next_close: string
  last_closed_trading_day: string
  calendar_warning: string | null
}
