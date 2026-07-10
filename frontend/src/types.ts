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
  wallet_activity?: ProviderStatusInfo;
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

export type WalletIngestionSurface =
  | "transfers"
  | "transactions"
  | "swaps"
  | "balances"
  | "jettons";

export type WalletIngestionStatus =
  | "planned"
  | "queued"
  | "running"
  | "success"
  | "partial"
  | "error"
  | "stale";

export type WalletSourceStatus =
  | "live"
  | "mock"
  | "offline"
  | "limited"
  | "unavailable"
  | "error";

export interface WalletIngestionRequest {
  wallet_address: string;
  time_window: TimeWindow;
  custom_start?: string;
  custom_end?: string;
  surfaces: WalletIngestionSurface[];
}

export interface WalletActivityProviderEvidence {
  provider: string;
  data_mode: "mock" | "real";
  source_status: WalletSourceStatus;
  warnings: string[];
  freshness?: string | null;
  raw_count: number;
  normalized_count: number;
}

export interface WalletActivityAcquisitionPageEvidence {
  page_index: number;
  request_cursor: string | null;
  response_cursor: string | null;
  requested_limit: number;
  raw_count: number;
  normalized_count: number;
  duplicate_count: number;
  min_logical_time: string | null;
  max_logical_time: string | null;
  min_timestamp: string | null;
  max_timestamp: string | null;
  response_digest: string;
  attempt_count: number;
  error_code: string | null;
  error_message: string | null;
  fetched_at: string | null;
}

export interface WalletActivityAcquisitionStreamEvidence {
  provider: string;
  stream_key: string;
  contract_version: string;
  scope_kind: string;
  requested_start: string | null;
  requested_end: string | null;
  query_filters: Record<string, unknown>;
  sort_order: string;
  page_size: number;
  page_cap: number;
  completion_state:
    | "complete"
    | "incomplete"
    | "error"
    | "preview_only"
    | "legacy_unavailable";
  termination_reason: string | null;
  page_count: number;
  pages_succeeded?: number;
  raw_count: number;
  normalized_count: number;
  duplicate_count: number;
  first_cursor: string | null;
  terminal_cursor: string | null;
  bounds_verified: boolean;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  pages: WalletActivityAcquisitionPageEvidence[];
}

export interface WalletIngestionPreviewResponse {
  success: boolean;
  wallet_address: string;
  time_window: string;
  requested_surfaces: WalletIngestionSurface[];
  provider_coverage: WalletActivityProviderEvidence[];
  unavailable_surfaces: WalletIngestionSurface[];
  incomplete_surfaces?: WalletIngestionSurface[];
  acquisition_streams?: WalletActivityAcquisitionStreamEvidence[];
  warnings: string[];
  message: string;
}

export interface WalletEventActionIdentityRecord {
  status: "provider_scoped" | "unavailable";
  version: string;
  provider?: string | null;
  network: "ton-mainnet" | "ton-testnet" | "ton-unknown";
  account_canonical?: string | null;
  event_id_canonical?: string | null;
  logical_time_canonical?: string | null;
  action_index?: number | null;
  action_type?: string | null;
  key?: string | null;
  is_provider_observation_identity: boolean;
  is_blockchain_proof_verified: false;
  is_authoritative_activity_identity: false;
  is_ownership_proof: false;
  eligible_for_cost_basis: false;
  deduplication_applied: false;
  used_by_pnl: false;
}

export interface WalletTransferRecord {
  tx_hash?: string | null;
  logical_time?: string | null;
  timestamp?: string | null;
  asset: string;
  amount?: string | null;
  direction: "in" | "out" | "unknown";
  counterparty?: string | null;
  provider: string;
  source_status: WalletSourceStatus;
  event_action_identity: WalletEventActionIdentityRecord;
  raw?: Record<string, unknown> | null;
}

export interface WalletTransactionRecord {
  tx_hash: string;
  logical_time?: string | null;
  timestamp?: string | null;
  fee_ton?: string | null;
  success: "success" | "failed" | "unknown";
  provider: string;
  source_status: WalletSourceStatus;
  transaction_identity: WalletTransactionIdentityRecord;
  raw?: Record<string, unknown> | null;
}

export interface WalletTransactionIdentityRecord {
  status: "network_scoped" | "unavailable";
  version: string;
  network: "ton-mainnet" | "ton-testnet" | "ton-unknown";
  account_canonical?: string | null;
  logical_time_canonical?: string | null;
  hash_canonical?: string | null;
  key?: string | null;
  is_deduplication_identity: boolean;
  is_blockchain_proof_verified: false;
  is_ownership_proof: false;
  deduplication_applied: false;
  used_by_pnl: false;
}

export interface WalletTransactionTraceEvidenceAnchor {
  transaction_hash: string;
  logical_time: string;
  account_canonical: string;
  matches_stored_transaction: true;
}

export interface WalletTransactionTraceEvidenceSummary {
  root_transaction_hash: string;
  transaction_count: number;
  max_depth: number;
  out_message_count: number;
  pending_internal_message_count: number;
  successful_transaction_count: number;
  failed_transaction_count: number;
  aborted_transaction_count: number;
  unique_account_count: number;
}

export interface WalletTransactionTraceEvidenceResponse {
  contract_version: "tonapi_transaction_trace_preview_v1";
  run_id: string;
  provider: "tonapi";
  source_status: "live";
  trace_state: "finalized" | "pending";
  anchor: WalletTransactionTraceEvidenceAnchor;
  summary: WalletTransactionTraceEvidenceSummary;
  is_provider_indexed_low_level_trace: true;
  is_blockchain_proof_verified: false;
  is_authoritative_activity_identity: false;
  semantic_reconstruction_applied: false;
  activity_merge_applied: false;
  deduplication_applied: false;
  eligible_for_cost_basis: false;
  used_by_pnl: false;
  is_ownership_proof: false;
  message: string;
}

export interface WalletPersistedTransactionTraceEvidenceSummary {
  root_transaction_hash: string;
  transaction_count: number;
  max_depth: number;
  message_count: number;
  root_inbound_message_count: number;
  child_internal_message_count: number;
  remaining_out_message_count: number;
  internal_message_count: number;
  external_in_message_count: number;
  external_out_message_count: number;
  successful_transaction_count: number;
  failed_transaction_count: number;
  aborted_transaction_count: number;
  unique_account_count: number;
}

export interface WalletPersistedTransactionTraceEvidenceResponse {
  contract_version: "tonapi_low_level_trace_evidence_v1";
  capture_id: string;
  run_id: string;
  provider: "tonapi";
  source_status: "live";
  network: "ton-mainnet" | "ton-testnet";
  trace_state: "finalized";
  captured_at: string;
  anchor: WalletTransactionTraceEvidenceAnchor;
  summary: WalletPersistedTransactionTraceEvidenceSummary;
  evidence_digest_sha256: string;
  is_provider_indexed_low_level_trace: true;
  provider_structure_validated: true;
  persisted_graph_revalidated: true;
  is_immutable_record: true;
  raw_boc_persisted: false;
  message_body_persisted: false;
  is_blockchain_proof_verified: false;
  is_authoritative_activity_identity: false;
  semantic_reconstruction_applied: false;
  activity_merge_applied: false;
  deduplication_applied: false;
  eligible_for_cost_basis: false;
  used_by_pnl: false;
  is_ownership_proof: false;
  message: string;
}

export interface WalletTraceBocVerificationSummary {
  transaction_count: number;
  message_count: number;
  total_boc_bytes: number;
  normalized_external_in_hash_count: number;
  direct_cell_hash_message_count: number;
  body_hash_count: number;
  opcode_count: number;
}

export interface WalletTraceBocVerifiedTransaction {
  preorder_index: number;
  transaction_hash: string;
  transaction_boc_bytes: number;
  transaction_cell_hash: string;
  raw_out_message_count: number;
  message_count: number;
  body_hash_count: number;
  opcode_count: number;
  message_evidence_digest_sha256: string;
}

export interface WalletTraceBocVerificationResponse {
  contract_version: "ton_boc_trace_verification_v1";
  verification_id: string;
  capture_id: string;
  run_id: string;
  provider: "tonapi";
  source_status: "live";
  network: "ton-mainnet" | "ton-testnet";
  verified_at: string;
  verifier: { name: "pytoniq-core"; version: "0.1.46" };
  anchor: WalletTransactionTraceEvidenceAnchor;
  capture_evidence_digest_sha256: string;
  evidence_digest_sha256: string;
  summary: WalletTraceBocVerificationSummary;
  transactions: WalletTraceBocVerifiedTransaction[];
  transaction_bocs_deserialized_locally: true;
  transaction_cell_hashes_verified: true;
  transaction_headers_verified: true;
  message_hashes_verified: true;
  message_headers_verified: true;
  message_body_hashes_derived: true;
  raw_boc_persisted: true;
  raw_boc_returned: false;
  message_bodies_returned: false;
  is_blockchain_inclusion_proof_verified: false;
  is_authoritative_activity_identity: false;
  semantic_reconstruction_applied: false;
  activity_merge_applied: false;
  deduplication_applied: false;
  eligible_for_cost_basis: false;
  used_by_pnl: false;
  is_ownership_proof: false;
  message: string;
}

export type WalletJettonPayloadOperation =
  | "transfer"
  | "transfer_notification"
  | "excesses"
  | "burn"
  | "internal_transfer"
  | "burn_notification";

export interface WalletJettonPayloadOperationCountRecord {
  operation: WalletJettonPayloadOperation;
  count: number;
}

export interface WalletJettonPayloadObservationRecord {
  ordinal: number;
  payload_observation_identity: string;
  transaction_preorder_index: number;
  transaction_hash: string;
  message_role: "root_inbound" | "child_inbound" | "remaining_outbound";
  message_ordinal: number;
  message_hash: string;
  message_source_account_canonical?: string | null;
  message_destination_account_canonical?: string | null;
  message_native_value_nanoton: string;
  body_hash: string;
  opcode_hex: string;
  operation: WalletJettonPayloadOperation;
  standard_status: "active" | "suggested";
  query_id: string;
  amount_base_units?: string | null;
  destination_account_canonical?: string | null;
  response_destination_account_canonical?: string | null;
  sender_account_canonical?: string | null;
  from_account_canonical?: string | null;
  forward_ton_amount_nanoton?: string | null;
  custom_payload_present: boolean;
  custom_payload_hash?: string | null;
  forward_payload_in_ref?: boolean | null;
  forward_payload_hash?: string | null;
  forward_payload_bit_length?: number | null;
  forward_payload_ref_count?: number | null;
  contract_account_role:
    | "destination_jetton_wallet_observed"
    | "source_jetton_wallet_observed"
    | "destination_jetton_master_observed"
    | "unresolved_contract_role";
}

export interface WalletJettonPayloadObservationsResponse {
  contract_version: "ton_jetton_payload_observations_v1";
  identity_version: "ton_jetton_payload_obs_v1";
  verification_id: string;
  capture_id: string;
  run_id: string;
  provider: "tonapi";
  source_status: "live";
  network: "ton-mainnet" | "ton-testnet";
  anchor: WalletTransactionTraceEvidenceAnchor;
  verification_evidence_digest_sha256: string;
  message_evidence_digest_sha256: string;
  payload_observations_digest_sha256: string;
  source_message_count: number;
  recognized_message_count: number;
  unrecognized_message_count: number;
  operations: WalletJettonPayloadOperationCountRecord[];
  observations: WalletJettonPayloadObservationRecord[];
  tep74_decoder_applied: true;
  recognized_payload_semantics_applied: boolean;
  query_id_is_correlation_only: true;
  message_bodies_returned: false;
  jetton_wallet_contract_role_is_observation_only: true;
  jetton_master_identity_applied: false;
  jetton_asset_identity_applied: false;
  is_authoritative_jetton_transfer_ledger: false;
  activity_merge_applied: false;
  deduplication_applied: false;
  eligible_for_cost_basis: false;
  used_by_pnl: false;
  is_ownership_proof: false;
  message: string;
}

export interface WalletSwapRecord {
  tx_hash?: string | null;
  timestamp?: string | null;
  dex?: string | null;
  token_in?: string | null;
  token_in_address?: string | null;
  amount_in?: string | null;
  token_out?: string | null;
  token_out_address?: string | null;
  amount_out?: string | null;
  estimated_usd?: string | null;
  provider: string;
  source_status: WalletSourceStatus;
  event_action_identity: WalletEventActionIdentityRecord;
  raw?: Record<string, unknown> | null;
}

export interface WalletBalanceSnapshotRecord {
  asset: string;
  balance?: string | null;
  balance_usd?: string | null;
  provider: string;
  source_status: WalletSourceStatus;
  snapshot_at?: string | null;
  raw?: Record<string, unknown> | null;
}

export interface WalletJettonContractVerificationAnchorRecord {
  workchain: -1 | 0;
  shard: string;
  seqno: number;
  root_hash: string;
  file_hash: string;
}

export interface WalletJettonContractVerificationResponse {
  contract_version: "ton_jetton_contract_verification_v1";
  verification_id: string;
  run_id: string;
  balance_snapshot_id: string;
  verifier_name: "pytoniq-pytvm";
  verifier_version: string;
  network: "ton-mainnet" | "ton-testnet";
  trust_level: 0 | 1;
  anchor: WalletJettonContractVerificationAnchorRecord;
  owner_account_canonical: string;
  jetton_wallet_account_canonical: string;
  jetton_master_account_canonical: string;
  asset_identity_key: string;
  wallet_balance_base_units: string;
  total_supply_base_units: string;
  mintable: boolean;
  wallet_code_hash: string;
  wallet_data_hash: string;
  master_code_hash: string;
  master_data_hash: string;
  jetton_content_hash: string;
  account_state_boc_hashes: Record<string, string>;
  evidence_digest_sha256: string;
  verified_at: string;
  account_state_proof_verified: true;
  masterchain_checkpoint_chain_verified: boolean;
  local_tvm_execution_applied: true;
  wallet_owner_master_verified: true;
  master_wallet_address_verified: true;
  wallet_code_consistency_verified: true;
  jetton_asset_identity_applied: true;
  raw_account_state_bocs_persisted: true;
  raw_account_state_bocs_returned: false;
  is_blockchain_inclusion_proof_verified: boolean;
  eligible_for_cost_basis: false;
  used_by_pnl: false;
  is_ownership_proof: false;
  message: string;
}

export interface WalletJettonContractVerificationCatalogResponse {
  contract_version: "ton_jetton_contract_verification_v1";
  run_id: string;
  network: "ton-mainnet" | "ton-testnet";
  verification_count: number;
  verification_digests: string[];
  verifications: WalletJettonContractVerificationResponse[];
  catalog_digest_sha256: string;
  provider_requests_performed: false;
  raw_account_state_bocs_returned: false;
  message: string;
}

export interface WalletIngestionWarningRecord {
  severity: "info" | "warning" | "error" | "critical";
  provider?: string | null;
  message: string;
  evidence_key?: string | null;
}

export interface WalletActivityTransferAssetSummary {
  asset: string;
  in_count: number;
  out_count: number;
  unknown_count: number;
  in_amount: string;
  out_amount: string;
  net_amount: string;
}

export interface WalletActivitySummary {
  is_pnl: boolean;
  note: string;
  counts: {
    transfers: number;
    transactions: number;
    swaps: number;
    balances: number;
  };
  transfers_by_asset: WalletActivityTransferAssetSummary[];
  swaps_by_dex: { dex: string; count: number }[];
  swaps_by_token?: {
    token: string;
    sent_count: number;
    received_count: number;
    sent_amount: string;
    received_amount: string;
  }[];
  transactions: { count: number; total_fee_ton: string };
  balances: {
    count: number;
    assets: string[];
    portfolio?: {
      total_balance_usd: string | null;
      priced_assets: number;
      unpriced_assets: number;
      note: string;
    };
  };
}

export interface WalletIdentityRecord {
  status: "network_scoped" | "unscoped" | "unavailable";
  version: string;
  network: "ton-mainnet" | "ton-testnet" | "ton-unknown";
  canonical_address?: string | null;
  workchain_id?: number | null;
  account_id_hex?: string | null;
  submitted_format: "user_friendly" | "raw" | "unrecognized";
  bounceable?: boolean | null;
  testnet_only?: boolean | null;
  is_account_existence_proof: false;
  is_ownership_proof: false;
}

export interface WalletIngestionRunCatalogItem {
  run_id: string;
  wallet_hint: string;
  time_window: TimeWindow;
  created_at: string;
  status: WalletIngestionStatus;
  data_mode: "mock" | "real";
}

export interface WalletIngestionRunCatalogResponse {
  runs: WalletIngestionRunCatalogItem[];
  limit: number;
  truncated: boolean;
}

export interface WalletIngestionRunResponse {
  run_id: number;
  wallet_address: string;
  wallet_identity: WalletIdentityRecord;
  time_window: TimeWindow;
  custom_start: string | null;
  custom_end: string | null;
  created_at: string;
  status: WalletIngestionStatus;
  data_mode: "mock" | "real";
  requested_surfaces: WalletIngestionSurface[];
  provider_evidence: WalletActivityProviderEvidence[];
  unavailable_surfaces: WalletIngestionSurface[];
  incomplete_surfaces?: WalletIngestionSurface[];
  acquisition_streams?: WalletActivityAcquisitionStreamEvidence[];
  transfers: WalletTransferRecord[];
  transactions: WalletTransactionRecord[];
  swaps: WalletSwapRecord[];
  balances: WalletBalanceSnapshotRecord[];
  warnings: WalletIngestionWarningRecord[];
  message: string;
  activity_summary?: WalletActivitySummary;
}

export interface WalletSignalsRecord {
  run_id: number;
  wallet_address: string;
  data_mode: "mock" | "real";
  ton_balance: string;
  portfolio_value_usd?: string | null;
  distinct_tokens_touched: string[];
  buy_swap_count: number;
  sell_swap_count: number;
  avg_ton_per_buy_swap?: string | null;
  first_buy_at?: string | null;
  warnings: string[];
}

export interface WalletClusterPairRecord {
  wallet_a_run_id: number;
  wallet_b_run_id: number;
  wallet_a_address: string;
  wallet_b_address: string;
  score: number;
  band: string;
  shared_tokens: string[];
  note: string;
}

export interface WalletClusterCompareResponse {
  wallets: WalletSignalsRecord[];
  comparison_window_seconds: number;
  pairs: WalletClusterPairRecord[];
  is_cluster_proof: boolean;
  note: string;
}

export interface WalletHistoryReadinessRequest {
  target_run_id: number;
  run_ids: number[];
}

export interface WalletHistoryRunScopeRecord {
  run_id: number;
  is_target: boolean;
  wallet_address: string;
  wallet_identity: WalletIdentityRecord;
  time_window: string;
  status: WalletIngestionStatus;
  created_at?: string | null;
  requested_start?: string | null;
  requested_end?: string | null;
  requested_bounds_verified: false;
  observed_activity_start?: string | null;
  observed_activity_end?: string | null;
  transfer_count: number;
  transaction_count: number;
  swap_count: number;
  timestamped_activity_count: number;
  untimestamped_activity_count: number;
  outside_requested_bounds_count: number;
  requested_surfaces: WalletIngestionSurface[];
  unavailable_surfaces: WalletIngestionSurface[];
}

export interface WalletHistoryIdentityGroupRecord {
  identity: string;
  identity_type:
    | "account_transaction"
    | "transaction_hash"
    | "provider_event_action_observation"
    | "event_action"
    | "event_reference"
    | "swap_fingerprint";
  identity_strength: "exact" | "provider_scoped" | "weak";
  run_ids: number[];
  observation_count: number;
  distinct_payload_count: number;
  has_conflict: boolean;
}

export interface WalletHistoryCoverageRecord {
  activity_observations: number;
  timestamped_activity_observations: number;
  transaction_observations: number;
  transaction_observations_with_hash: number;
  transaction_observations_with_exact_identity: number;
  transaction_observations_with_weak_identity: number;
  transaction_observations_with_unavailable_identity: number;
  transaction_observations_with_invalid_identity_contract: number;
  transaction_identity_coverage_state: "not_observed" | "complete" | "incomplete";
  overlapping_transaction_identity_groups: number;
  conflicting_transaction_identity_groups: number;
  event_action_observations: number;
  event_action_observations_with_provider_scoped_identity: number;
  event_action_observations_with_unavailable_identity: number;
  event_action_observations_with_invalid_identity_contract: number;
  event_action_identity_coverage_state: "not_observed" | "complete" | "incomplete";
  overlapping_provider_scoped_event_action_identity_groups: number;
  conflicting_provider_scoped_event_action_identity_groups: number;
  swap_observations: number;
  swap_observations_with_exact_identity: number;
  swap_observations_with_provider_scoped_identity: number;
  swap_observations_with_weak_identity: number;
  overlapping_exact_swap_identity_groups: number;
  overlapping_provider_scoped_swap_identity_groups: number;
  overlapping_weak_swap_identity_groups: number;
  conflicting_swap_identity_groups: number;
  non_ton_swap_legs: number;
  addressed_non_ton_swap_legs: number;
  asset_address_coverage_state: "not_observed" | "complete" | "incomplete";
  fee_link_candidate_swaps: number;
  same_run_fee_hash_match_candidates: number;
  fee_hash_match_coverage_state: "not_observed" | "complete" | "incomplete";
  fee_linkage_contract_verified: false;
}

export interface WalletHistoryIntervalRecord {
  start: string;
  end: string;
  duration_microseconds: string;
}

export interface WalletHistoryAcceptedIntervalRecord
  extends WalletHistoryIntervalRecord {
  run_id: number;
}

export interface WalletHistoryOverlapIntervalRecord
  extends WalletHistoryIntervalRecord {
  run_ids: number[];
  coverage_depth: number;
}

export interface WalletHistoryGapIntervalRecord
  extends WalletHistoryIntervalRecord {
  left_run_ids: number[];
  right_run_ids: number[];
}

export interface WalletHistoryIntervalRunEvidenceRecord {
  run_id: number;
  source_state?: string | null;
  candidate_states: string[];
  classification: "included" | "excluded" | "not_requested";
  reason?: string | null;
  source_reason_codes: string[];
  recorded_interval_start?: string | null;
  recorded_interval_end?: string | null;
  interval_start?: string | null;
  interval_end?: string | null;
  duration_microseconds?: string | null;
  included_in_union: boolean;
}

export interface WalletHistoryIntervalCoverageLayerRecord {
  stream_key: "transactions" | "account_events";
  coverage_kind:
    | "low_level_transaction_stream"
    | "provider_display_event_stream";
  eligible_state: "complete" | "provider_stream_complete";
  provider_semantics:
    | "bounded_low_level_transaction_query"
    | "display_only_actions";
  state:
    | "no_validated_intervals"
    | "contiguous_selected_span"
    | "gapped_selected_span";
  selected_run_count: number;
  requested_run_count: number;
  included_run_count: number;
  included_run_ids: number[];
  excluded_run_ids: number[];
  not_requested_run_ids: number[];
  selected_run_coverage_state: "none" | "partial" | "complete";
  run_evidence: WalletHistoryIntervalRunEvidenceRecord[];
  accepted_intervals: WalletHistoryAcceptedIntervalRecord[];
  selected_span?: WalletHistoryIntervalRecord | null;
  union_intervals: WalletHistoryIntervalRecord[];
  overlap_intervals: WalletHistoryOverlapIntervalRecord[];
  gap_intervals: WalletHistoryGapIntervalRecord[];
  span_duration_microseconds: string;
  covered_duration_microseconds: string;
  gap_duration_microseconds: string;
  overlapped_duration_microseconds: string;
  max_coverage_depth: number;
  is_contiguous_within_selected_span: boolean;
  outside_selected_span_coverage: "unknown";
  establishes_full_history: false;
  is_authoritative_activity_coverage: false;
}

export interface WalletHistoryBoundedIntervalCoverageRecord {
  contract_version: "wallet_multi_run_interval_coverage_v1";
  selected_run_ids: number[];
  interval_semantics: "[start,end)";
  coverage_scope: "selected_validated_run_intervals_only";
  gap_scope: "inside_validated_selected_span_only";
  cross_stream_union_applied: false;
  low_level_transactions: WalletHistoryIntervalCoverageLayerRecord;
  provider_display_events: WalletHistoryIntervalCoverageLayerRecord;
  full_pre_run_history_established: false;
  complete_wallet_history_established: false;
  is_global_history_coverage: false;
  is_authoritative_activity_coverage: false;
  activity_rows_merged: false;
  deduplication_applied: false;
  is_cost_basis: false;
  eligible_for_cost_basis: false;
  used_by_pnl: false;
  note: string;
}

export interface WalletHistoryBlockerRecord {
  code: string;
  reason: string;
  run_ids: number[];
  evidence: Record<string, unknown>;
}

export interface WalletHistoryReadinessResponse {
  analysis_version: "wallet_history_readiness_v0.22.7";
  target_run_id: number;
  run_ids: number[];
  wallet_address: string;
  wallet_identity: WalletIdentityRecord;
  data_mode: "mock" | "real";
  requested_bounds_verified: false;
  observed_activity_start?: string | null;
  observed_activity_end?: string | null;
  runs: WalletHistoryRunScopeRecord[];
  transaction_identity_groups: WalletHistoryIdentityGroupRecord[];
  swap_identity_groups: WalletHistoryIdentityGroupRecord[];
  event_action_identity_groups: WalletHistoryIdentityGroupRecord[];
  transaction_identity_groups_total: number;
  swap_identity_groups_total: number;
  event_action_identity_groups_total: number;
  evidence_groups_truncated: boolean;
  coverage: WalletHistoryCoverageRecord;
  bounded_interval_coverage: WalletHistoryBoundedIntervalCoverageRecord;
  blockers: WalletHistoryBlockerRecord[];
  history_complete: false;
  deduplication_applied: false;
  is_cost_basis: false;
  eligible_for_cost_basis: false;
  used_by_pnl: false;
  note: string;
}

export interface WalletNativeActivityPnlFlowSummaryRecord {
  asset_identity_key: string;
  activity_count: number;
  incoming_activity_count: number;
  outgoing_activity_count: number;
  self_activity_count: number;
  incoming_nanoton: string;
  outgoing_nanoton: string;
  self_nanoton: string;
  net_nanoton: string;
  incoming_ton: string;
  outgoing_ton: string;
  self_ton: string;
  net_ton: string;
}

export type WalletNativeActivityPnlRequirementCode =
  | "deduplicated_native_activity"
  | "complete_wallet_history"
  | "authoritative_trade_semantics"
  | "jetton_asset_identity"
  | "historical_trade_prices"
  | "transaction_fee_linkage"
  | "acquisition_cost_basis";

export interface WalletNativeActivityPnlRequirementRecord {
  code: WalletNativeActivityPnlRequirementCode;
  available: boolean;
  reason?: string | null;
}

export interface WalletNativeActivityPnlReadinessResponse {
  contract_version: "ton_native_activity_pnl_readiness_v1";
  target_run_id: number;
  selected_run_ids: number[];
  source_dedup_digest_sha256: string;
  flow_summary: WalletNativeActivityPnlFlowSummaryRecord;
  requirements: WalletNativeActivityPnlRequirementRecord[];
  blocked_requirement_codes: WalletNativeActivityPnlRequirementCode[];
  network: string;
  wallet_account_canonical: string;
  source_ledger_count: number;
  merged_activity_count: number;
  deduplicated_activity_count: number;
  suppressed_occurrence_count: number;
  analysis_digest_sha256: string;
  analysis_status: "blocked_missing_evidence";
  calculation_mode: "native_flow_reconciliation_only";
  cost_basis_method: "unavailable";
  cost_basis_usd: null;
  realized_pnl_usd: null;
  unrealized_pnl_usd: null;
  activity_merge_applied: true;
  cross_run_deduplication_applied: true;
  native_activity_used_by_pnl_readiness: true;
  native_activity_used_by_pnl_calculation: false;
  establishes_complete_wallet_history: false;
  eligible_for_cost_basis: false;
  is_cost_basis: false;
  is_real_pnl: false;
  real_pnl_locked: true;
  message: string;
}

export type WalletMultiAssetPnlRequirementCode =
  | "deduplicated_native_activity"
  | "verified_jetton_payload_semantics"
  | "proof_checked_jetton_asset_identity"
  | "exact_transaction_fee_evidence"
  | "complete_wallet_history"
  | "authoritative_trade_semantics"
  | "historical_trade_prices"
  | "transaction_fee_allocation"
  | "acquisition_lots_and_cost_basis";

export interface WalletMultiAssetPnlRequirementRecord {
  code: WalletMultiAssetPnlRequirementCode;
  available: boolean;
  reason?: string | null;
}

export interface WalletJettonPayloadOccurrenceRecord {
  run_id: number;
  capture_id: number;
  verification_id: number;
}

export interface WalletJettonAssetFeeEvidenceRecord {
  ordinal: number;
  payload_observation_identity: string;
  occurrence_count: number;
  source_run_ids: number[];
  occurrences: WalletJettonPayloadOccurrenceRecord[];
  operation: WalletJettonPayloadOperation;
  standard_status: "active" | "suggested";
  transaction_hash: string;
  message_hash: string;
  query_id: string;
  amount_base_units?: string | null;
  contract_account_role: WalletJettonPayloadObservationRecord["contract_account_role"];
  observed_contract_account_canonical?: string | null;
  asset_binding_status: "verified_contract_match" | "unavailable";
  jetton_master_account_canonical?: string | null;
  asset_identity_key?: string | null;
  contract_verification_ids: number[];
  contract_verification_digests: string[];
  contract_verification_run_ids: number[];
  provider_asset_observation_key?: string | null;
  asset_decimals?: number | null;
  asset_symbol?: string | null;
  asset_snapshot_run_ids: number[];
  transaction_fee_evidence_status: "exact_transaction_match" | "unavailable";
  transaction_fee_nanoton?: string | null;
  transaction_fee_ton?: string | null;
  fee_source_run_ids: number[];
  provider_snapshot_is_local_master_proof: false;
  fee_allocation_applied: false;
  eligible_for_cost_basis: false;
  used_by_pnl_calculation: false;
}

export interface WalletJettonEvidenceSummaryRecord {
  selected_capture_count: number;
  verified_capture_count: number;
  source_message_count: number;
  recognized_payload_occurrence_count: number;
  unrecognized_message_count: number;
  deduplicated_payload_observation_count: number;
  suppressed_payload_occurrence_count: number;
  provider_jetton_snapshot_count: number;
  valid_provider_asset_snapshot_count: number;
  invalid_provider_asset_snapshot_count: number;
  verified_jetton_contract_count: number;
  asset_matched_observation_count: number;
  asset_unmatched_observation_count: number;
  fee_linked_observation_count: number;
  fee_unlinked_observation_count: number;
  linked_fee_transaction_count: number;
  linked_fee_nanoton: string;
  linked_fee_ton: string;
}

export interface WalletMultiAssetLotReadinessSummaryRecord {
  evidence_row_count: number;
  proof_bound_asset_row_count: number;
  exact_fee_row_count: number;
  authoritative_trade_row_count: 0;
  historical_price_eligible_row_count: 0;
  fee_allocated_row_count: 0;
  lot_eligible_row_count: 0;
  blocked_row_count: number;
}

export interface WalletMultiAssetPnlReadinessResponse {
  contract_version: "ton_multi_asset_pnl_readiness_v3";
  target_run_id: number;
  selected_run_ids: number[];
  network: string;
  wallet_account_canonical: string;
  source_native_analysis_digest_sha256: string;
  native_flow_summary: WalletNativeActivityPnlFlowSummaryRecord;
  jetton_evidence_summary: WalletJettonEvidenceSummaryRecord;
  operations: WalletJettonPayloadOperationCountRecord[];
  evidence: WalletJettonAssetFeeEvidenceRecord[];
  requirements: WalletMultiAssetPnlRequirementRecord[];
  blocked_requirement_codes: WalletMultiAssetPnlRequirementCode[];
  lot_readiness_summary: WalletMultiAssetLotReadinessSummaryRecord;
  analysis_digest_sha256: string;
  analysis_status: "blocked_missing_evidence";
  calculation_mode: "evidence_reconciliation_only";
  cost_basis_method: "unavailable";
  cost_basis_usd: null;
  realized_pnl_usd: null;
  unrealized_pnl_usd: null;
  native_activity_deduplication_applied: true;
  jetton_observation_deduplication_applied: true;
  jetton_payload_semantics_used_by_pnl_readiness: boolean;
  verified_contract_identity_used_by_pnl_readiness: boolean;
  provider_asset_metadata_used_by_pnl_readiness: boolean;
  transaction_fee_evidence_used_by_pnl_readiness: boolean;
  provider_snapshot_asset_identity_is_authoritative: false;
  verified_contract_asset_identity_is_authoritative: boolean;
  transaction_fee_allocation_applied: false;
  historical_price_requests_performed: false;
  acquisition_lot_construction_applied: false;
  disposal_lot_construction_applied: false;
  provider_requests_performed: false;
  message_bodies_returned: false;
  used_by_pnl_calculation: false;
  establishes_complete_wallet_history: false;
  eligible_for_cost_basis: false;
  is_cost_basis: false;
  is_real_pnl: false;
  real_pnl_locked: true;
  message: string;
}

export interface WalletEvidenceSignalRecord {
  code: string;
  title: string;
  confidence: "low" | "medium" | "high";
  observation: string;
  evidence: Record<string, unknown>;
  note: string;
}

export interface WalletEvidenceInsufficientRecord {
  code: string;
  reason: string;
}

export interface HistoricalPricePointRecord {
  timestamp: string;
  price_usd: string;
}

export interface HistoricalPricesPreviewResponse {
  token: string;
  currency: "usd";
  requested_start: string;
  requested_end: string;
  data_mode: "mock" | "real";
  source_status: "mock" | "real" | "unavailable";
  points: HistoricalPricePointRecord[];
  point_count: number;
  is_cost_basis_source: boolean;
  warnings: string[];
  message: string;
  note: string;
}

export interface WalletPnlRequirementRecord {
  code: string;
  available: boolean;
  reason?: string | null;
}

export interface WalletPnlTokenFlowRecord {
  token: string;
  buy_swap_count: number;
  sell_swap_count: number;
  token_bought_qty: string;
  token_sold_qty: string;
  ton_spent: string;
  ton_received: string;
  net_ton_flow: string;
  fee_ton: string;
  net_ton_flow_after_fees: string;
}

export interface WalletPnlUsdFlowRecord {
  token: string;
  usd_spent: string;
  usd_received: string;
  net_usd_flow: string;
  matched_swap_count: number;
}

export interface WalletPnlRealizedRecord {
  token: string;
  status: "computed" | "unavailable";
  reason?: string | null;
  sell_leg_count: number;
  proceeds_usd?: string | null;
  cost_basis_usd?: string | null;
  realized_pnl_usd?: string | null;
  remaining_qty?: string | null;
  remaining_cost_usd?: string | null;
}

export interface WalletPnlUnrealizedRecord {
  token: string;
  status: "computed" | "unavailable";
  reason?: string | null;
  remaining_qty?: string | null;
  remaining_cost_usd?: string | null;
  spot_price_usd?: string | null;
  priced_by?: string | null;
  market_value_usd?: string | null;
  unrealized_pnl_usd?: string | null;
}

export interface WalletPnlHistoricalPricingRecord {
  source_status: "mock" | "real" | "unavailable";
  points_fetched: number;
  swaps_matched: number;
  swaps_unmatched: number;
  tolerance_seconds: number;
  note: string;
}

export interface WalletRunPnlPreviewResponse {
  run_id?: number | null;
  wallet_address: string;
  pnl_mode:
    | "imported_pnl"
    | "estimated_onchain_pnl"
    | "real_pnl_locked"
    | "insufficient_data"
    | "real_pnl";
  confidence: "high" | "medium" | "low" | "unavailable";
  is_real_pnl: boolean;
  real_pnl_locked: boolean;
  token_flows: WalletPnlTokenFlowRecord[];
  total_ton_spent: string;
  total_ton_received: string;
  net_ton_flow: string;
  total_fees_ton: string;
  net_ton_flow_after_fees: string;
  swaps_used: number;
  swaps_excluded: number;
  usd_flows: WalletPnlUsdFlowRecord[];
  total_usd_spent?: string | null;
  total_usd_received?: string | null;
  net_usd_flow?: string | null;
  historical_pricing?: WalletPnlHistoricalPricingRecord | null;
  realized_pnl?: WalletPnlRealizedRecord[];
  total_realized_pnl_usd?: string | null;
  unrealized: WalletPnlUnrealizedRecord[];
  total_unrealized_pnl_usd?: string | null;
  unrealized_note?: string | null;
  requirements: WalletPnlRequirementRecord[];
  missing_evidence: string[];
  warnings: string[];
  note: string;
}

export interface WalletRunSignalsResponse {
  run_id?: number | null;
  wallet_address: string;
  is_risk_score: boolean;
  evaluated: string[];
  signals: WalletEvidenceSignalRecord[];
  insufficient_evidence: WalletEvidenceInsufficientRecord[];
  note: string;
}
