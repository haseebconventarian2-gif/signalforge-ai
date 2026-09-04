export type AgentStatus = {
  desired_state: string;
  effective_state: string;
  cycle_state: string;
  paper_trading: boolean;
  execution_enabled: boolean;
  autonomy_enabled: boolean;
  kill_switch_active: boolean;
  running_cycle: boolean;
  last_heartbeat: string | null;
  last_error: string | null;
};

export type Overview = {
  paper_trading: boolean;
  equity: string;
  cash: string;
  buying_power: string;
  options_buying_power: string | null;
  daily_pnl: string;
  total_pnl: string;
  win_rate: string;
  open_positions: number;
  execution_enabled: boolean;
};

export type RiskRule = {
  rule_name: string;
  passed: boolean;
  actual_value: string;
  limit: string;
  reason: string;
};

export type Candidate = {
  id: string;
  correlation_id: string;
  symbol: string;
  status: string;
  direction: string;
  signal_score: string;
  snapshot: Record<string, unknown>;
  reasons: string[];
  created_at: string;
  ai_decision: null | {
    decision: string;
    confidence: string;
    thesis: string;
    supporting_factors: string[];
    risk_factors: string[];
  };
  ai_metadata: null | { model: string; validation_status: string; failure_code: string | null };
  risk_decisions: { stage: string; verdict: string; evaluations: RiskRule[] }[];
  contract: null | {
    symbol: string;
    type: string;
    strike: string;
    expiration: string;
    premium: string;
    score: { total: string };
  };
};

export type Position = {
  id: string;
  underlying: string;
  contract_symbol: string;
  status: string;
  quantity: number;
  entry_price: string;
  current_price: string | null;
  unrealized_pnl: string;
  stop_price: string;
  target_price: string;
  expiration_date: string;
  opened_at: string;
  closed_at: string | null;
  realized_pnl: string | null;
  exit_reason: string | null;
};

export type Order = {
  id: string;
  candidate_id: string;
  contract_symbol: string;
  underlying: string;
  intent: string;
  status: string;
  quantity: number;
  filled_quantity: string;
  limit_price: string;
  average_fill_price: string | null;
  client_order_id: string;
  created_at: string;
};

export type Analytics = {
  trades: number;
  win_rate: string;
  average_win: string;
  average_loss: string;
  profit_factor: string | null;
  cumulative_pnl: { timestamp: string; pnl: string }[];
  by_symbol: Record<string, string>;
  rejections: Record<string, number>;
};

export type Opportunity = {
  symbol: string;
  directional_bias: string;
  signal_score: string;
  underlying_price: string;
  data_freshness_seconds: number;
  reasons: string[];
};

export type ScanResult = {
  timestamp: string;
  watchlist: string[];
  opportunities: Opportunity[];
  market_open: boolean | null;
};

export type Configuration = {
  watchlist: string[];
  scan_interval_seconds: number;
  signal_threshold: string;
  minimum_ai_confidence: string;
  maximum_risk_per_trade_pct: string;
  maximum_premium_per_trade: string;
  maximum_open_positions: number;
  maximum_spread_pct: string;
  dte_window: number[];
  stop_loss_pct: string;
  take_profit_pct: string;
  paper_trading: boolean;
  demo_mode: boolean;
};
