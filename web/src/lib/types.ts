// ── Domain types mirroring the Python trade journal & config ──────────

export type Direction = "CALL" | "PUT";
export type Recommendation = "APPROVE" | "REJECT";
export type Regime = "BULL" | "NEUTRAL" | "BEAR" | "UNKNOWN";

export interface K2Output {
  symbol: string;
  direction: Direction;
  confidence: number;
  thesis: string;
  momentum_quality: number;
  fundamental_quality: number;
  catalyst_strength: number;
  risk_level: number;
  expected_holding_days: number;
  invalidation: string;
  catalyst_classification:
    | "POSITIVE"
    | "NEGATIVE"
    | "NEUTRAL"
    | "ALREADY_PRICED"
    | "UNCERTAIN";
  key_risks: string[];
}

export interface QwenOutput {
  symbol: string;
  recommendation: Recommendation;
  thesis_valid: boolean;
  adjusted_confidence: number;
  risk_score: number;
  momentum_assessment: "STRONG" | "ADEQUATE" | "WEAK" | "EXHAUSTED";
  fundamental_assessment: "POSITIVE" | "NEUTRAL" | "NEGATIVE";
  catalyst_assessment: "POSITIVE" | "NEUTRAL" | "NEGATIVE" | "ALREADY_PRICED";
  concerns: string[];
  contradictions: string[];
  invalidation_conditions: string[];
}

export type Gate = [name: string, passed: boolean, detail: string];

export interface PositionSize {
  max_contracts: number;
  cost_per_contract: number;
  total_cost: number;
  risk_pct: number;
}

export interface Evidence {
  momentum?: Record<string, unknown>;
  fundamentals?: Record<string, unknown>;
  earnings?: Record<string, unknown>;
  catalysts?: Record<string, unknown>;
}

export interface Candidate {
  timestamp: string;
  run_id?: string;
  symbol: string;
  momentum_score: number;
  direction: Direction;
  k2_confidence: number;
  qwen_recommendation: Recommendation;
  qwen_confidence: number;
  final_score: number;
  approved: boolean;
  reject_reason?: string | null;
  thesis: string;
  regime: string;
  k2?: K2Output | null;
  qwen?: QwenOutput | null;
  gates?: Gate[];
  risk_approved?: boolean | null;
  risk_reason?: string | null;
  position_size?: PositionSize | null;
  evidence?: Evidence | null;
  reused?: boolean;
}

export interface Trade {
  trade_id: string;
  symbol: string;
  option_symbol: string;
  direction: Direction;
  entry_time: string;
  entry_price: number;
  quantity: number;
  thesis: string;
  invalidation: string;
  confidence: number;
  expected_holding_days: number;
  max_holding_days: number;
  entry_momentum_rank: number;
  entry_close: number;
  order_id?: string;
  exit_time: string | null;
  exit_price: number | null;
  exit_reason: string;
  pnl: number | null;
  holding_days?: number | null;
}

export interface Journal {
  candidates: Candidate[];
  trades: Trade[];
  reports?: CycleReport[];
}

export interface ReporterVerdict {
  symbol: string;
  approved: boolean;
  direction: Direction;
  k2_agreed: boolean;
  qwen_agreed: boolean;
  final_score: number;
  why_approved_or_rejected: string;
  key_concern: string;
}

export interface CycleReport {
  timestamp: string;
  run_id: string;
  cycle_number: number;
  regime: string;
  total_candidates: number;
  total_approved: number;
  total_rejected: number;
  summary: string;
  verdicts: ReporterVerdict[];
}

export interface RunGroup {
  run_id: string;
  timestamp: string;
  candidates: Candidate[];
  approvedCount: number;
  regime: string;
}

export interface PerformanceSummary {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
}

export interface Config {
  models: {
    primary: { provider: string; model: string };
    critic: { provider: string; model: string };
    fallback: { provider: string; model: string };
  };
  risk: {
    max_risk_per_trade: number;
    max_open_positions: number;
    max_portfolio_option_premium: number;
    max_symbol_exposure: number;
    max_holding_days: number;
  };
  options: {
    min_dte: number;
    max_dte: number;
    target_delta_min: number;
    target_delta_max: number;
    max_bid_ask_spread_pct: number;
  };
  decision: {
    min_momentum_score: number;
    min_ai_confidence: number;
    require_critic_approval: boolean;
  };
  regime: {
    bull_max_exposure: number;
    neutral_max_exposure: number;
    bear_max_exposure: number;
  };
  momentum: {
    lookbacks: number[];
    candidate_count: number;
    min_score: number;
  };
  [key: string]: unknown;
}

export interface DashboardData {
  equity: number;
  cash: number;
  dailyPnl: number;
  totalPnl: number;
  openPositions: number;
  winRate: number;
  avgTrade: number;
  totalTrades: number;
  avgK2Conf: number;
  avgQwenConf: number;
  approveRate: number;
  candidateCount: number;
  regime: Regime;
  runs: RunGroup[];
  openTrades: Trade[];
  history: Trade[];
  avgWinner: number;
  avgLoser: number;
  config: Config;
  now: string;
  equitySeries: { t: string; v: number }[];
  scheduler: SchedulerState;
  latestReport: CycleReport | null;
}

export interface SchedulerState {
  enabled: boolean;
  running: boolean;
  cycle_count: number;
  last_run: string | null;
  last_result: string;
  next_run: string | null;
  interval_seconds: number;
  current_phase: string;
  error: string | null;
  updated: string | null;
}

export interface AlpacaAccountData {
  equity: number;
  cash: number;
  buying_power: number;
  portfolio_value: number;
  long_market_value: number;
  short_market_value: number;
  daytrade_count: number;
  last_equity: number;
  initial_margin: number;
  maintenance_margin: number;
  account_number: string;
}

export interface AlpacaOrder {
  id: string;
  client_order_id: string | null;
  symbol: string;
  side: string;
  type: string;
  qty: number;
  filled_qty: number;
  filled_avg_price: number | null;
  limit_price: number | null;
  stop_price: number | null;
  status: string;
  submitted_at: string | null;
  filled_at: string | null;
  expired_at: string | null;
  canceled_at: string | null;
  failed_at: string | null;
  replaced_at: string | null;
  time_in_force: string;
  order_class: string;
  notional: number | null;
}
