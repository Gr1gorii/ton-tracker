import type {
  WalletPersistedTransactionTraceEvidenceResponse,
  WalletPersistedTransactionTraceEvidenceSummary,
  WalletTransactionRecord,
  WalletTransactionTraceEvidenceAnchor,
  WalletTransactionTraceEvidenceResponse,
  WalletTransactionTraceEvidenceSummary,
} from "./types";

const MAX_UINT64 = 18_446_744_073_709_551_615n;
const RESPONSE_KEYS = [
  "activity_merge_applied",
  "anchor",
  "contract_version",
  "deduplication_applied",
  "eligible_for_cost_basis",
  "is_authoritative_activity_identity",
  "is_blockchain_proof_verified",
  "is_ownership_proof",
  "is_provider_indexed_low_level_trace",
  "message",
  "provider",
  "run_id",
  "semantic_reconstruction_applied",
  "source_status",
  "summary",
  "trace_state",
  "used_by_pnl",
] as const;
const ANCHOR_KEYS = [
  "account_canonical",
  "logical_time",
  "matches_stored_transaction",
  "transaction_hash",
] as const;
const SUMMARY_KEYS = [
  "aborted_transaction_count",
  "failed_transaction_count",
  "max_depth",
  "out_message_count",
  "pending_internal_message_count",
  "root_transaction_hash",
  "successful_transaction_count",
  "transaction_count",
  "unique_account_count",
] as const;
const FALSE_FLAG_KEYS = [
  "is_blockchain_proof_verified",
  "is_authoritative_activity_identity",
  "semantic_reconstruction_applied",
  "activity_merge_applied",
  "deduplication_applied",
  "eligible_for_cost_basis",
  "used_by_pnl",
  "is_ownership_proof",
] as const;
const PERSISTED_RESPONSE_KEYS = [
  "activity_merge_applied",
  "anchor",
  "capture_id",
  "captured_at",
  "contract_version",
  "deduplication_applied",
  "eligible_for_cost_basis",
  "evidence_digest_sha256",
  "is_authoritative_activity_identity",
  "is_blockchain_proof_verified",
  "is_immutable_record",
  "is_ownership_proof",
  "is_provider_indexed_low_level_trace",
  "message",
  "message_body_persisted",
  "network",
  "persisted_graph_revalidated",
  "provider",
  "provider_structure_validated",
  "raw_boc_persisted",
  "run_id",
  "semantic_reconstruction_applied",
  "source_status",
  "summary",
  "trace_state",
  "used_by_pnl",
] as const;
const PERSISTED_SUMMARY_KEYS = [
  "aborted_transaction_count",
  "child_internal_message_count",
  "external_in_message_count",
  "external_out_message_count",
  "failed_transaction_count",
  "internal_message_count",
  "max_depth",
  "message_count",
  "remaining_out_message_count",
  "root_inbound_message_count",
  "root_transaction_hash",
  "successful_transaction_count",
  "transaction_count",
  "unique_account_count",
] as const;
const PERSISTED_FALSE_FLAG_KEYS = [
  ...FALSE_FLAG_KEYS,
  "raw_boc_persisted",
  "message_body_persisted",
] as const;

export interface WalletTraceEvidenceExpectedAnchor {
  runId: number;
  transactionHash: string;
  logicalTime: string;
  accountCanonical: string;
}

export interface WalletTraceEligibleTransaction {
  transactionHash: string;
  logicalTime: string;
  accountCanonical: string;
  network: "ton-mainnet" | "ton-testnet";
  timestamp: string | null;
}

export interface WalletPersistedTraceEvidenceExpectedAnchor
  extends WalletTraceEvidenceExpectedAnchor {
  network: "ton-mainnet" | "ton-testnet";
}

export function eligibleTraceTransactions(
  transactions: WalletTransactionRecord[],
): WalletTraceEligibleTransaction[] {
  if (!Array.isArray(transactions)) return [];

  const seen = new Set<string>();
  const eligible: WalletTraceEligibleTransaction[] = [];
  for (const transaction of transactions) {
    const identity = transaction?.transaction_identity;
    const transactionHash = identity?.hash_canonical;
    const logicalTime = identity?.logical_time_canonical;
    const accountCanonical = identity?.account_canonical;
    const network = identity?.network;
    if (
      transaction?.provider !== "tonapi" ||
      transaction?.source_status !== "live" ||
      identity?.status !== "network_scoped" ||
      identity.is_deduplication_identity !== true ||
      !isCanonicalHash(transactionHash) ||
      !isCanonicalUint64(logicalTime) ||
      !isCanonicalTonAddress(accountCanonical) ||
      (network !== "ton-mainnet" && network !== "ton-testnet") ||
      seen.has(transactionHash)
    ) {
      continue;
    }
    seen.add(transactionHash);
    eligible.push({
      transactionHash,
      logicalTime,
      accountCanonical,
      network,
      timestamp:
        typeof transaction.timestamp === "string" ? transaction.timestamp : null,
    });
  }
  return eligible;
}

export function validatePersistedWalletTransactionTraceEvidenceResponse(
  value: unknown,
  expected: WalletPersistedTraceEvidenceExpectedAnchor,
): WalletPersistedTransactionTraceEvidenceResponse {
  validateExpectedAnchor(expected);
  if (!isRecord(value) || !hasExactKeys(value, PERSISTED_RESPONSE_KEYS)) {
    throw new Error(
      "Persisted trace evidence returned an unexpected response shape.",
    );
  }
  if (
    value.contract_version !== "tonapi_low_level_trace_evidence_v1" ||
    !isCanonicalPositiveInt64(value.capture_id) ||
    value.run_id !== String(expected.runId) ||
    value.provider !== "tonapi" ||
    value.source_status !== "live" ||
    value.network !== expected.network ||
    value.trace_state !== "finalized" ||
    !isUtcIsoTimestamp(value.captured_at) ||
    !isCanonicalHash(value.evidence_digest_sha256) ||
    value.is_provider_indexed_low_level_trace !== true ||
    value.provider_structure_validated !== true ||
    value.persisted_graph_revalidated !== true ||
    value.is_immutable_record !== true ||
    typeof value.message !== "string" ||
    value.message.trim().length === 0 ||
    value.message.length > 500 ||
    PERSISTED_FALSE_FLAG_KEYS.some((key) => value[key] !== false)
  ) {
    throw new Error("Persisted trace evidence returned invalid contract metadata.");
  }

  return {
    contract_version: value.contract_version,
    capture_id: value.capture_id,
    run_id: value.run_id,
    provider: value.provider,
    source_status: value.source_status,
    network: expected.network,
    trace_state: value.trace_state,
    captured_at: value.captured_at,
    anchor: validateAnchor(value.anchor, expected),
    summary: validatePersistedSummary(value.summary),
    evidence_digest_sha256: value.evidence_digest_sha256,
    is_provider_indexed_low_level_trace: true,
    provider_structure_validated: true,
    persisted_graph_revalidated: true,
    is_immutable_record: true,
    raw_boc_persisted: false,
    message_body_persisted: false,
    is_blockchain_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: value.message,
  };
}

export function validateWalletTransactionTraceEvidenceResponse(
  value: unknown,
  expected: WalletTraceEvidenceExpectedAnchor,
): WalletTransactionTraceEvidenceResponse {
  validateExpectedAnchor(expected);
  if (!isRecord(value) || !hasExactKeys(value, RESPONSE_KEYS)) {
    throw new Error("Trace evidence preview returned an unexpected response shape.");
  }
  if (
    value.contract_version !== "tonapi_transaction_trace_preview_v1" ||
    value.run_id !== String(expected.runId) ||
    value.provider !== "tonapi" ||
    value.source_status !== "live" ||
    (value.trace_state !== "finalized" && value.trace_state !== "pending") ||
    value.is_provider_indexed_low_level_trace !== true ||
    typeof value.message !== "string" ||
    value.message.trim().length === 0 ||
    value.message.length > 500 ||
    FALSE_FLAG_KEYS.some((key) => value[key] !== false)
  ) {
    throw new Error("Trace evidence preview returned invalid contract metadata.");
  }

  const anchor = validateAnchor(value.anchor, expected);
  const summary = validateSummary(value.summary);
  if (
    (value.trace_state === "finalized") !==
    (summary.pending_internal_message_count === 0)
  ) {
    throw new Error("Trace evidence preview returned an incoherent trace state.");
  }

  return {
    contract_version: value.contract_version,
    run_id: value.run_id,
    provider: value.provider,
    source_status: value.source_status,
    trace_state: value.trace_state,
    anchor,
    summary,
    is_provider_indexed_low_level_trace: true,
    is_blockchain_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: value.message,
  };
}

function validateExpectedAnchor(
  expected: WalletTraceEvidenceExpectedAnchor,
): void {
  if (
    !Number.isSafeInteger(expected.runId) ||
    expected.runId <= 0 ||
    !isCanonicalHash(expected.transactionHash) ||
    !isCanonicalUint64(expected.logicalTime) ||
    !isCanonicalTonAddress(expected.accountCanonical)
  ) {
    throw new Error("Trace evidence preview has an invalid requested anchor.");
  }
}

function validateAnchor(
  value: unknown,
  expected: WalletTraceEvidenceExpectedAnchor,
): WalletTransactionTraceEvidenceAnchor {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ANCHOR_KEYS) ||
    value.transaction_hash !== expected.transactionHash ||
    value.logical_time !== expected.logicalTime ||
    value.account_canonical !== expected.accountCanonical ||
    value.matches_stored_transaction !== true
  ) {
    throw new Error("Trace evidence preview did not match the stored transaction anchor.");
  }
  return {
    transaction_hash: value.transaction_hash,
    logical_time: value.logical_time,
    account_canonical: value.account_canonical,
    matches_stored_transaction: true,
  };
}

function validateSummary(
  value: unknown,
): WalletTransactionTraceEvidenceSummary {
  if (!isRecord(value) || !hasExactKeys(value, SUMMARY_KEYS)) {
    throw new Error("Trace evidence preview returned an invalid trace summary.");
  }
  const integerKeys = SUMMARY_KEYS.filter(
    (key): key is Exclude<(typeof SUMMARY_KEYS)[number], "root_transaction_hash"> =>
      key !== "root_transaction_hash",
  );
  if (
    !isCanonicalHash(value.root_transaction_hash) ||
    integerKeys.some((key) => !isNonnegativeSafeInteger(value[key])) ||
    (value.transaction_count as number) < 1 ||
    (value.transaction_count as number) > 256 ||
    (value.max_depth as number) > 32 ||
    (value.out_message_count as number) > 2048 ||
    (value.pending_internal_message_count as number) > 2048 ||
    (value.unique_account_count as number) < 1 ||
    (value.successful_transaction_count as number) +
      (value.failed_transaction_count as number) !==
      (value.transaction_count as number) ||
    (value.aborted_transaction_count as number) >
      (value.transaction_count as number) ||
    (value.unique_account_count as number) >
      (value.transaction_count as number) ||
    (value.pending_internal_message_count as number) >
      (value.out_message_count as number) ||
    ((value.transaction_count as number) > 1 &&
      (value.max_depth as number) === 0)
  ) {
    throw new Error("Trace evidence preview returned invalid trace summary values.");
  }
  return {
    root_transaction_hash: value.root_transaction_hash,
    transaction_count: value.transaction_count as number,
    max_depth: value.max_depth as number,
    out_message_count: value.out_message_count as number,
    pending_internal_message_count:
      value.pending_internal_message_count as number,
    successful_transaction_count: value.successful_transaction_count as number,
    failed_transaction_count: value.failed_transaction_count as number,
    aborted_transaction_count: value.aborted_transaction_count as number,
    unique_account_count: value.unique_account_count as number,
  };
}

function validatePersistedSummary(
  value: unknown,
): WalletPersistedTransactionTraceEvidenceSummary {
  if (!isRecord(value) || !hasExactKeys(value, PERSISTED_SUMMARY_KEYS)) {
    throw new Error("Persisted trace evidence returned an invalid graph summary.");
  }
  const integerKeys = PERSISTED_SUMMARY_KEYS.filter(
    (
      key,
    ): key is Exclude<
      (typeof PERSISTED_SUMMARY_KEYS)[number],
      "root_transaction_hash"
    > => key !== "root_transaction_hash",
  );
  if (
    !isCanonicalHash(value.root_transaction_hash) ||
    integerKeys.some((key) => !isNonnegativeSafeInteger(value[key]))
  ) {
    throw new Error("Persisted trace evidence returned invalid graph summary values.");
  }

  const summary = value as Record<
    Exclude<(typeof PERSISTED_SUMMARY_KEYS)[number], "root_transaction_hash">,
    number
  > & { root_transaction_hash: string };
  if (
    summary.transaction_count < 1 ||
    summary.transaction_count > 256 ||
    summary.max_depth > 32 ||
    summary.message_count > 2304 ||
    summary.remaining_out_message_count > 2048 ||
    summary.root_inbound_message_count > 1 ||
    summary.child_internal_message_count !== summary.transaction_count - 1 ||
    summary.message_count !==
      summary.root_inbound_message_count +
        summary.child_internal_message_count +
        summary.remaining_out_message_count ||
    summary.internal_message_count +
      summary.external_in_message_count +
      summary.external_out_message_count !==
      summary.message_count ||
    summary.external_in_message_count > summary.root_inbound_message_count ||
    summary.external_out_message_count !== summary.remaining_out_message_count ||
    summary.internal_message_count !==
      summary.child_internal_message_count +
        summary.root_inbound_message_count -
        summary.external_in_message_count ||
    summary.successful_transaction_count + summary.failed_transaction_count !==
      summary.transaction_count ||
    summary.aborted_transaction_count > summary.transaction_count ||
    summary.unique_account_count < 1 ||
    summary.unique_account_count > summary.transaction_count ||
    (summary.transaction_count > 1 && summary.max_depth === 0)
  ) {
    throw new Error("Persisted trace evidence returned invalid graph summary values.");
  }

  return {
    root_transaction_hash: summary.root_transaction_hash,
    transaction_count: summary.transaction_count,
    max_depth: summary.max_depth,
    message_count: summary.message_count,
    root_inbound_message_count: summary.root_inbound_message_count,
    child_internal_message_count: summary.child_internal_message_count,
    remaining_out_message_count: summary.remaining_out_message_count,
    internal_message_count: summary.internal_message_count,
    external_in_message_count: summary.external_in_message_count,
    external_out_message_count: summary.external_out_message_count,
    successful_transaction_count: summary.successful_transaction_count,
    failed_transaction_count: summary.failed_transaction_count,
    aborted_transaction_count: summary.aborted_transaction_count,
    unique_account_count: summary.unique_account_count,
  };
}

function isCanonicalHash(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
}

function isCanonicalPositiveInt64(value: unknown): value is string {
  if (typeof value !== "string" || !/^[1-9][0-9]{0,18}$/.test(value)) {
    return false;
  }
  return BigInt(value) <= 9_223_372_036_854_775_807n;
}

function isUtcIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 40 &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(
      value,
    ) &&
    !Number.isNaN(Date.parse(value))
  );
}

function isCanonicalUint64(value: unknown): value is string {
  if (typeof value !== "string" || !/^[1-9][0-9]*$/.test(value)) return false;
  if (value.length > 20) return false;
  return BigInt(value) <= MAX_UINT64;
}

function isCanonicalTonAddress(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(-?(?:0|[1-9][0-9]*)):([0-9a-f]{64})$/.exec(value);
  if (!match || match[1] === "-0") return false;
  const workchain = Number(match[1]);
  return (
    Number.isSafeInteger(workchain) &&
    workchain >= -(2 ** 31) &&
    workchain <= 2 ** 31 - 1
  );
}

function isNonnegativeSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  const keys = Object.keys(value).sort();
  const expected = [...allowed].sort();
  return (
    keys.length === expected.length &&
    keys.every((key, index) => key === expected[index])
  );
}
