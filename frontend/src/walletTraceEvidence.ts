import type {
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
  timestamp: string | null;
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
    if (
      transaction?.provider !== "tonapi" ||
      transaction?.source_status !== "live" ||
      identity?.status !== "network_scoped" ||
      identity.is_deduplication_identity !== true ||
      !isCanonicalHash(transactionHash) ||
      !isCanonicalUint64(logicalTime) ||
      !isCanonicalTonAddress(accountCanonical) ||
      seen.has(transactionHash)
    ) {
      continue;
    }
    seen.add(transactionHash);
    eligible.push({
      transactionHash,
      logicalTime,
      accountCanonical,
      timestamp:
        typeof transaction.timestamp === "string" ? transaction.timestamp : null,
    });
  }
  return eligible;
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

function isCanonicalHash(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
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
