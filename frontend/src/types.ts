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
  stonfi?: ProviderStatusInfo;
  tonapi?: ProviderStatusInfo;
}

export interface DataQualityComponents {
  pool_data: "mock" | "real" | "fallback_mock";
  token_data: "mock" | "real" | "fallback_mock";
  wallet_buyers: "mock";
  wallet_balances: "mock";
  pnl: "mock_calculated";
  clustering: "mock_calculated";
  common_holdings: "mock";
}

export interface DataQuality {
  mode: "mock" | "real";
  components: DataQualityComponents;
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

export type ImportFormat = "csv" | "json";
export type ImportSource = "imported_csv" | "imported_json";
export type ImportPreviewContent =
  | string
  | Record<string, unknown>
  | Array<Record<string, unknown>>;

export interface ImportValidationError {
  row: number;
  field: string;
  message: string;
}

export interface ImportValidationSummary {
  total_rows: number;
  valid_rows: number;
  invalid_rows: number;
  duplicate_rows: number;
  errors: ImportValidationError[];
}

export interface ImportedTradePreview {
  tx_hash: string;
  block_time: string;
  wallet: string;
  side: "buy" | "sell";
  token_amount: string | number;
  usd_amount: string | number;
  price_usd?: string | number | null;
  pool_address?: string | null;
  dex?: string | null;
  source: ImportSource;
}

export interface ImportPreviewRequest {
  format: ImportFormat;
  content: ImportPreviewContent;
  preview_limit?: number;
}

export interface ImportPreviewResponse {
  summary: ImportValidationSummary;
  trades_preview: ImportedTradePreview[];
  preview_limit: number;
  has_more: boolean;
  source: ImportSource;
}

export type ImportedWalletStatus =
  | "holder"
  | "partial_seller"
  | "full_exit"
  | "seller_only"
  | "unknown";

export interface ImportedTradesAnalysisSummary extends ImportValidationSummary {
  wallets_count: number;
  buy_trades_count: number;
  sell_trades_count: number;
}

export interface ImportedWalletAnalysis {
  wallet: string;
  buy_trades_count: number;
  sell_trades_count: number;
  total_bought_qty: string;
  total_bought_usd: string;
  total_sold_qty: string;
  total_sold_usd: string;
  net_holding_qty: string;
  avg_buy_price_usd: string | null;
  avg_sell_price_usd: string | null;
  realized_pnl_usd: string;
  realized_pnl_pct: string | null;
  status: ImportedWalletStatus;
  first_trade_time: string;
  last_trade_time: string;
}

export interface ImportedTradesAnalysisResponse {
  summary: ImportedTradesAnalysisSummary;
  wallets: ImportedWalletAnalysis[];
  trades_preview: ImportedTradePreview[];
  preview_limit: number;
  has_more_wallets: boolean;
  source: ImportSource;
  analysis_note: string;
}

export interface BitqueryTokenTradesRequest {
  token_address: string;
  start: string;
  end: string;
  preview_limit?: number;
}

export interface BitqueryProviderError {
  code: string | null;
  message: string;
}

export interface BitqueryPreviewSummary {
  total_trades: number;
  preview_count: number;
}

export interface BitqueryAnalysisSummary {
  total_trades: number;
  valid_rows: number;
  wallets_count: number;
  buy_trades_count: number;
  sell_trades_count: number;
  errors: ImportValidationError[];
}

export interface BitqueryTradePreview {
  tx_hash: string;
  block_time: string;
  wallet: string;
  side: "buy" | "sell";
  token_amount: string | number;
  usd_amount: string | number;
  price_usd?: string | number | null;
  pool_address?: string | null;
  dex?: string | null;
  source: "bitquery";
}

export type BitqueryWalletAnalysis = ImportedWalletAnalysis;

export interface BitqueryPreviewResponse {
  provider: "bitquery";
  data_mode: "mock" | "real";
  success: boolean;
  summary: BitqueryPreviewSummary;
  trades_preview: BitqueryTradePreview[];
  warnings: string[];
  error: BitqueryProviderError | null;
}

export interface BitqueryAnalysisResponse {
  provider: "bitquery";
  data_mode: "mock" | "real";
  success: boolean;
  summary: BitqueryAnalysisSummary;
  wallets: BitqueryWalletAnalysis[];
  trades_preview: BitqueryTradePreview[];
  preview_limit: number;
  has_more_wallets: boolean;
  warnings: string[];
  error: BitqueryProviderError | null;
  analysis_note: string;
}

export interface StonfiProviderError {
  code: string | null;
  message: string;
}

export interface StonfiPoolsPreviewSummary {
  total_pools: number;
  preview_count: number;
  requested_limit: number;
}

export interface StonfiPoolPreview {
  address?: string | null;
  router_address?: string | null;
  token0_address?: string | null;
  token1_address?: string | null;
  token0_symbol?: string | null;
  token1_symbol?: string | null;
  reserve0?: string | number | null;
  reserve1?: string | number | null;
  token0_balance?: string | number | null;
  token1_balance?: string | number | null;
  lp_total_supply_usd?: string | number | null;
  liquidity_usd?: string | number | null;
  volume_24h_usd?: string | number | null;
  apy_1d?: string | number | null;
  apy_7d?: string | number | null;
  apy_30d?: string | number | null;
  deprecated?: boolean;
  tags?: string[];
  source?: string | null;
  [key: string]: unknown;
}

export interface StonfiPoolsPreviewResponse {
  provider: "stonfi";
  data_mode: "mock" | "real";
  source: "mock" | "real";
  success: boolean;
  summary: StonfiPoolsPreviewSummary;
  pools_preview: StonfiPoolPreview[];
  warnings: string[];
  message: string;
  error: StonfiProviderError | null;
}

export interface TonapiProviderError {
  code: string | null;
  message: string;
  diagnostic?: string | null;
}

export interface TonapiAccountJettonsPreviewSummary {
  total_jettons: number;
  preview_count: number;
  requested_limit: number;
}

export interface TonapiJettonPreview {
  wallet_address?: string | null;
  jetton_address?: string | null;
  jetton_name?: string | null;
  jetton_symbol?: string | null;
  balance?: string | number | null;
  decimals?: string | number | null;
  image?: string | null;
  price?: string | number | null;
  price_usd?: string | number | null;
  wallet_contract_address?: string | null;
  source?: string | null;
  [key: string]: unknown;
}

export interface TonapiAccountJettonsPreviewResponse {
  provider: "tonapi";
  data_mode: "mock" | "real";
  source: "mock" | "real";
  success: boolean;
  summary: TonapiAccountJettonsPreviewSummary;
  account_address: string;
  jettons_preview: TonapiJettonPreview[];
  warnings: string[];
  message: string;
  error: TonapiProviderError | null;
}

export interface TonapiWalletIntelligenceSummary {
  total_jettons: number;
  preview_count: number;
  requested_limit: number;
  non_zero_balance_count?: number;
  jettons_with_price_count?: number;
  stablecoin_like_count?: number;
}

export interface TonapiTopJettonPreview {
  jetton_address?: string | null;
  jetton_name?: string | null;
  jetton_symbol?: string | null;
  balance?: string | number | null;
  decimals?: string | number | null;
  display_balance?: string | number | null;
  price?: string | number | null;
  price_usd?: string | number | null;
  wallet_contract_address?: string | null;
  source?: string | null;
  [key: string]: unknown;
}

export interface TonapiWalletIntelligence {
  scope?: string;
  data_sources?: string[];
  account_address?: string;
  total_jettons?: number;
  preview_count?: number;
  requested_limit?: number;
  non_zero_balance_count?: number;
  jettons_with_price_count?: number;
  stablecoin_like_count?: number;
  top_jettons_by_display_balance?: TonapiTopJettonPreview[];
  basic_notes?: string[];
  [key: string]: unknown;
}

export interface TonapiWalletIntelligencePreviewResponse {
  provider: "tonapi";
  data_mode: "mock" | "real";
  source: "mock" | "real";
  success: boolean;
  account_address: string;
  summary: TonapiWalletIntelligenceSummary;
  intelligence: TonapiWalletIntelligence;
  jettons_preview: TonapiJettonPreview[];
  warnings: string[];
  message: string;
  error: TonapiProviderError | null;
}
