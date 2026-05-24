// Types mirroring the backend analysis payload (services/analysis.py).

export type WalletStatus =
  | "holder"
  | "partial_seller"
  | "full_exit"
  | "unknown";

export type TimeWindow = "24h" | "3d" | "7d" | "custom";

export interface Position {
  symbol: string;
  value_usd: number;
}

export interface Wallet {
  address: string;
  status: WalletStatus;
  total_bought_qty: number;
  total_bought_usd: number;
  total_sold_qty: number;
  total_sold_usd: number;
  current_holding: number;
  avg_buy_price_usd: number;
  avg_sell_price_usd: number;
  realised_pnl_usd: number;
  realised_pnl_pct: number;
  unrealised_pnl_usd: number;
  unrealised_pnl_pct: number;
  total_pnl_usd: number;
  total_pnl_pct: number;
  ton_balance: number;
  portfolio_value_usd: number;
  positions: Position[];
  max_position_value_usd: number;
  common_tokens: string[];
  group: string;
  interesting: boolean;
  high_ton_balance: boolean;
  buy_time: string;
  sold_fraction: number;
  connected_score: number;
  // Cyrillic key returned by the backend (per-wallet conclusion).
  "Вывод": string;
}

export interface WalletGroup {
  group_name: string;
  group_type: string;
  wallet_list: string[];
  shared_tokens: string[];
  average_connected_score: number;
  reason_summary: string;
  "Вывод": string;
}

export interface CommonHolding {
  token: string;
  holder_count: number;
  total_value_usd: number;
  holders: string[];
}

export interface TokenInfo {
  name: string;
  symbol: string;
  address: string;
  decimals: number;
  current_price_usd: number;
  market_cap_usd: number;
  fdv_usd: number;
}

export interface PoolInfo {
  address: string;
  dex: string;
  base_token: string;
  quote_token: string;
  liquidity_usd: number;
  volume_24h_usd: number;
  created_at: string;
  requested_network?: string;
  requested_pool_address?: string | null;
}

export interface AnalysisSummary {
  total_buyers: number;
  holders: number;
  partial_sellers: number;
  full_exits: number;
  interesting_count: number;
  whale_count: number;
  group_count: number;
  total_realised_pnl_usd: number;
  total_unrealised_pnl_usd: number;
}

export interface AnalyzedWindow {
  start: string;
  end: string;
  window_seconds: number;
}

export interface ProviderStatusInfo {
  configured: boolean;
  available: boolean;
  message: string;
}

export interface ProvidersStatus {
  data_mode: string;
  geckoterminal: ProviderStatusInfo;
  ton_provider: ProviderStatusInfo;
  bitquery: ProviderStatusInfo;
}

export interface DataQuality {
  mode: string;
  warnings: string[];
  provider_notes: string[];
}

export interface AnalysisResult {
  pool_url: string;
  time_window: string;
  analyzed_window: AnalyzedWindow;
  token: TokenInfo;
  pool: PoolInfo;
  summary: AnalysisSummary;
  wallets: Wallet[];
  groups: WalletGroup[];
  common_holdings: CommonHolding[];
  interesting_wallets: Wallet[];
  data_quality: DataQuality;
  providers: ProvidersStatus;
  disclaimer: string;
  is_mock: boolean;
}

export interface AnalyzeRequest {
  pool_url: string;
  time_window: TimeWindow;
  custom_start?: string;
  custom_end?: string;
}
