/** Shared JSON value shapes returned by the StockAI dashboard API. */

export type JsonDecimal = string | number;

export interface PortfolioPosition {
  symbol: string;
  name?: string;
  quantity?: JsonDecimal;
  available_quantity?: JsonDecimal;
  average_cost?: JsonDecimal;
  last_price?: JsonDecimal;
  market_value?: JsonDecimal;
  unrealized_pnl?: JsonDecimal;
  realized_pnl?: JsonDecimal;
  weight?: JsonDecimal;
  trading_enabled?: boolean;
}

export interface Portfolio {
  cash?: JsonDecimal;
  total_asset?: JsonDecimal;
  total_market_value?: JsonDecimal;
  positions?: PortfolioPosition[];
}

export interface RiskConfig {
  max_symbol_weight?: JsonDecimal;
  max_etf_weight?: JsonDecimal;
  max_stock_weight?: JsonDecimal;
  max_etf_total_weight?: JsonDecimal;
  max_stock_total_weight?: JsonDecimal;
  max_total_exposure?: JsonDecimal;
  min_cash_ratio?: JsonDecimal;
  max_drawdown?: JsonDecimal;
  single_position_loss?: JsonDecimal;
  trailing_drawdown?: JsonDecimal;
  portfolio_daily_loss?: JsonDecimal;
  high_atr_ratio?: JsonDecimal;
  max_operations_per_symbol?: JsonDecimal;
  status?: string;
  pending_confirmation?: boolean;
}

export interface WatchlistItem {
  symbol: string;
  name: string;
  asset_type: string;
  lifecycle_status?: string;
  trading_enabled?: boolean | number;
  source?: string;
}

export interface MarketQuote {
  symbol?: string;
  name?: string;
  latest_price?: JsonDecimal;
  previous_close?: JsonDecimal;
  change_percent?: JsonDecimal;
  observed_at?: string;
  quoted_at?: string;
  updated_at?: string;
}

export interface FillRow {
  symbol: string;
  direction: string;
  quantity: number;
  price: JsonDecimal;
  fee: JsonDecimal;
  slippage?: JsonDecimal;
  gross_amount?: JsonDecimal;
  timestamp: string;
  order_id?: string;
}

export interface DecisionRow {
  symbol: string;
  direction: string;
  target_weight?: JsonDecimal;
  approved?: boolean;
  risk_reasons?: string[];
  strategy_id?: string;
  score?: JsonDecimal;
  confidence?: JsonDecimal;
  explanation?: string;
  evidence?: string[];
  objections?: string[];
  version?: string;
  reasons?: string[];
}

export interface ProfitLeaderboardRow {
  symbol: string;
  name: string;
  profit_amount: JsonDecimal;
  holding_days: number;
  return_rate: JsonDecimal;
}

export interface OverviewPayload {
  portfolio?: Portfolio;
  risk_config?: RiskConfig;
  daily_return?: JsonDecimal;
  pending_backtest_count?: number;
  today_decisions?: DecisionRow[];
  recent_fills?: FillRow[];
  watchlist?: WatchlistItem[];
  profit_leaderboard?: ProfitLeaderboardRow[];
  market_quotes?: Record<string, MarketQuote>;
  updated_at?: string;
  [key: string]: unknown;
}

export interface PerformanceQuery {
  performance_start: string;
  performance_end: string;
}

export interface EquityCurvePoint {
  day: string;
  total_asset: JsonDecimal;
}

export interface BenchmarkPoint {
  series: string;
  day: string;
  return_rate: JsonDecimal;
}

export interface BenchmarkOutperformance {
  series: string;
  day: string;
  agent_return: JsonDecimal;
  benchmark_return: JsonDecimal;
  difference: JsonDecimal;
}

export interface BenchmarkStatusRow {
  symbol: string;
  name: string;
  state: string;
  points: number;
  latest_day: string | null;
}

export interface PerformanceRange {
  start_date: string;
  end_date: string;
}

export interface PerformancePayload {
  equity_curve?: EquityCurvePoint[];
  benchmark_comparison?: BenchmarkPoint[];
  benchmark_outperformance?: BenchmarkOutperformance[];
  performance_range?: PerformanceRange;
  benchmark_status?: BenchmarkStatusRow[];
  benchmarks?: Record<string, string>;
}

export interface ProfitCalendarCell {
  period: string;
  start_date: string;
  end_date: string;
  pnl: JsonDecimal;
  return_rate: JsonDecimal;
}

export interface ProfitCalendar {
  daily?: ProfitCalendarCell[];
  monthly?: ProfitCalendarCell[];
  yearly?: ProfitCalendarCell[];
}

export interface CalendarPayload {
  profit_calendar?: ProfitCalendar;
}

export interface BacktestMetrics {
  total_return?: JsonDecimal;
  max_drawdown?: JsonDecimal;
  win_rate?: JsonDecimal;
  profit_loss_ratio?: JsonDecimal;
  turnover?: JsonDecimal;
  max_consecutive_losses?: JsonDecimal;
  summary?: string;
  proposals?: unknown[];
  [key: string]: unknown;
}

export interface BacktestRun {
  id: number;
  strategy_id: string;
  strategy_profile_id: string;
  parameters: Record<string, string | number>;
  metrics: BacktestMetrics;
  status: string;
  confirmed_at?: string | null;
  applied_at?: string | null;
  created_at: string;
}

export interface BacktestsPayload {
  backtest_runs: BacktestRun[];
}

export interface ConfirmBacktestsResult extends BacktestsPayload {
  updated?: number;
  queued?: number;
  reviewed?: number;
  rejected?: number;
}

export interface StrategyDefinition {
  strategy_id: string;
  name_zh: string;
  name_en: string;
  category_zh: string;
  category_en: string;
  description_zh: string;
  description_en: string;
}

export interface ProfileDiffEntry {
  field: string;
  before: unknown;
  after: unknown;
}

export interface StrategyProfile {
  profile_id: string;
  name_zh?: string;
  name_en?: string;
  scope_type?: string;
  scope_value?: string;
  status?: string;
  config_schema_version?: number;
  revision?: number;
  enabled?: string[];
  weights?: Record<string, string>;
  technical?: Record<string, unknown>;
  quant?: Record<string, unknown>;
  external?: Record<string, unknown>;
  aggregator?: Record<string, unknown>;
  target_weight_levels?: string[];
  pending_confirmation?: boolean;
  pending_activation?: boolean;
  effective_monitor_round?: string;
  source_backtest_id?: number;
  source_backtest_parameters?: Record<string, string | number>;
  active_revision?: number;
  draft_diff?: ProfileDiffEntry[];
  migration_note?: string;
}

export interface StrategyChange {
  profile_id: string;
  action: string;
  operator?: string;
  before?: unknown;
  after?: unknown;
  created_at: string;
}

export interface StrategyCenter {
  definitions: StrategyDefinition[];
  profiles: StrategyProfile[];
  changes: StrategyChange[];
}

export interface StrategiesPayload {
  strategies: StrategyCenter;
  saved_profile_id?: string;
}

export interface DailyReportSummary {
  report_date: string;
  status: string;
  summary?: string;
  total_asset?: JsonDecimal;
  daily_pnl?: JsonDecimal;
  daily_return?: JsonDecimal;
  updated_at?: string;
}

export interface DailyReportAccount {
  cash?: JsonDecimal;
  total_asset?: JsonDecimal;
  total_market_value?: JsonDecimal;
  position_ratio?: JsonDecimal;
  daily_pnl?: JsonDecimal;
  daily_return?: JsonDecimal;
  previous_total_asset?: JsonDecimal;
}

export interface DailyReportPosition {
  symbol: string;
  quantity: number;
  available_quantity?: number;
  average_cost?: JsonDecimal;
  last_price?: JsonDecimal;
  market_value?: JsonDecimal;
  position_weight?: JsonDecimal;
  realized_pnl?: JsonDecimal;
  unrealized_pnl?: JsonDecimal;
}

export interface DailyReportFill {
  symbol: string;
  direction: string;
  quantity: number;
  price: JsonDecimal;
  fee: JsonDecimal;
  slippage?: JsonDecimal;
  gross_amount?: JsonDecimal;
  timestamp: string;
}

export interface DailyReportDecision {
  symbol: string;
  direction: string;
  target_weight?: JsonDecimal;
  approved?: boolean;
  risk_reasons?: string[];
  strategy_id?: string;
  score?: JsonDecimal;
  confidence?: JsonDecimal;
  explanation?: string;
  evidence?: string[];
  objections?: string[];
  version?: string;
}

export interface DailyReportTimelineEvent {
  event_at?: string;
  symbol?: string;
  phase?: string;
  direction?: string;
  status?: string;
  reasons?: string[];
}

export interface DailyReport extends DailyReportSummary {
  system_notes?: string[];
  account?: DailyReportAccount;
  positions?: DailyReportPosition[];
  fills?: DailyReportFill[];
  decisions?: DailyReportDecision[];
  decision_timeline?: DailyReportTimelineEvent[];
}

export interface DailyReportsPayload {
  daily_reports: DailyReportSummary[];
}

export interface DailyReportPayload {
  daily_report: DailyReport | null;
}

export interface InstrumentRef {
  symbol: string;
  name: string;
  asset_type: string;
}

export interface BarPayload {
  time: string;
  open: JsonDecimal;
  high: JsonDecimal;
  low: JsonDecimal;
  close: JsonDecimal;
  volume: JsonDecimal;
  amount: JsonDecimal;
}

export interface QuoteTick {
  symbol?: string;
  latest_price?: JsonDecimal;
  observed_at?: string;
  quoted_at?: string;
  [key: string]: unknown;
}

export interface TradeMarker {
  timestamp: string;
  direction: string;
  quantity: number;
  price: JsonDecimal;
  fee: JsonDecimal;
  summary: string;
}

export interface InstrumentDetail {
  instrument: InstrumentRef;
  latest_quote: MarketQuote | null;
  intraday: {
    ticks: QuoteTick[];
    previous_close: JsonDecimal | null;
  };
  five_day: BarPayload[];
  five_day_trading_days: number;
  daily: BarPayload[];
  weekly: BarPayload[];
  monthly: BarPayload[];
  minute_bars: Record<string, BarPayload[]>;
  trade_markers: TradeMarker[];
}

export interface InstrumentSearchResult {
  symbol: string;
  name: string;
  asset_type: string;
}

export interface InstrumentCatalogStatus {
  count?: number;
  synced_date?: string;
}
