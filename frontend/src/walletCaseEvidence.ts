import { parseRfc3339Instant } from "./rfc3339";
import { isCanonicalRawTonAddress } from "./tonAddress";
import type { WalletTransactionInclusionBlockRecord } from "./types";
import {
  type WalletCaseActivitySnapshot,
  type WalletCaseActivityItem,
} from "./walletCaseActivity";
import {
  parseWalletCaseCoverage,
  type WalletCaseLimitation,
} from "./walletCase";
import {
  CURRENT_TRANSACTION_INCLUSION_POLICY,
  isCurrentTransactionInclusionCheckpoint,
} from "./walletTransactionInclusion";

export type WalletCaseEvidenceLevel =
  | "normalized"
  | "locally_verified"
  | "chain_inclusion_proven";
export type WalletCaseEvidenceVerificationState =
  | "queued"
  | "running"
  | "partial"
  | "succeeded"
  | "failed"
  | "cancelled";
export type WalletCaseEvidenceVerificationStage =
  | "queued"
  | "validating"
  | "capturing_trace"
  | "verifying_bocs"
  | "proving_inclusion"
  | "building_native_ledger"
  | "finalizing"
  | "retry_wait"
  | "terminal";
export type WalletCaseEvidenceStepCode =
  | "trace_capture"
  | "boc_verification"
  | "block_inclusion"
  | "native_ledger";

export interface WalletCaseEvidenceInclusionProvenance {
  contract_version: "ton_transaction_inclusion_v2";
  network: "ton-mainnet" | "ton-testnet";
  verifier_policy_id: "ton_liteserver_checkpoint_strict_2026_08_v2";
  trust_level: 0;
  trusted_checkpoint: WalletTransactionInclusionBlockRecord;
  canonical_block_chain_verified_at_capture: true;
  checkpoint_to_observed_head_transcript_persisted: false;
}

export interface WalletCaseEvidenceVerification {
  case_public_id: string;
  public_id: string;
  snapshot_public_id: string;
  activity_public_id: string;
  policy: "transaction_inclusion_v1";
  state: WalletCaseEvidenceVerificationState;
  stage: WalletCaseEvidenceVerificationStage;
  status_version: number;
  progress: { current: number; total: 4 };
  cancel_requested: boolean;
  highest_evidence_level: WalletCaseEvidenceLevel;
  inclusion_provenance: WalletCaseEvidenceInclusionProvenance | null;
  provenance: {
    data_origin: "provider_observed";
    provider: string;
    identity_assurance: "network_scoped";
    source_sync_public_id: string;
    transaction: {
      network: "ton-mainnet" | "ton-testnet";
      wallet_account_canonical: string;
      hash: string;
      logical_time: string;
    };
  };
  steps: Array<{
    code: WalletCaseEvidenceStepCode;
    state: "pending" | "succeeded";
    evidence_level: WalletCaseEvidenceLevel | null;
    evidence_digest_sha256: string | null;
    completed_at: string | null;
  }>;
  retry: null | {
    attempt: number;
    max_attempts: number;
    retry_at: string;
    reason_code: string;
    message_safe: string;
  };
  error: null | { code: string; message_safe: string; retryable: boolean };
  limitations: WalletCaseLimitation[];
  result: null | {
    verification_digest_sha256: string;
    evidence_digests: Record<WalletCaseEvidenceStepCode, string | null>;
    inclusion_provenance: WalletCaseEvidenceInclusionProvenance | null;
    native_ledger: null | {
      evidence_digest_sha256: string;
      activity_count: number;
      incoming_nanoton: string;
      outgoing_nanoton: string;
      self_nanoton: string;
      native_ton_only: true;
      selected_evidence_only: true;
      is_authoritative_activity_ledger: false;
      establishes_complete_wallet_history: false;
      eligible_for_cost_basis: false;
      used_by_pnl: false;
      message: string;
    };
  };
  message: string;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface WalletCaseEvidenceCatalog {
  case_public_id: string;
  snapshot: WalletCaseActivitySnapshot | null;
  aggregate: {
    total: number;
    returned_count: number;
    counts_scope: "returned_revalidated";
    queued: number;
    running: number;
    partial: number;
    succeeded: number;
    failed: number;
    cancelled: number;
    normalized: number;
    locally_verified: number;
    chain_inclusion_proven: number;
  };
  readiness: {
    transaction_verification_available: boolean;
    report_available: boolean;
    highest_evidence_level: WalletCaseEvidenceLevel | null;
  };
  limitations: WalletCaseLimitation[];
  verifications: WalletCaseEvidenceVerification[];
  limit: 50;
  truncated: boolean;
}

export interface WalletCaseEvidenceVerificationRequest {
  snapshot_public_id: string;
  activity_public_id: string;
  policy: "transaction_inclusion_v1";
}

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ACTIVITY_ID = /^act_[0-9a-f]{64}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const HASH = /^[0-9a-f]{64}$/;
const WALLET_ACCOUNT = /^(?:-1|0):[0-9a-f]{64}$/;
const LOGICAL_TIME = /^(?:0|[1-9][0-9]{0,19})$/;
const NANOTON = /^(?:0|[1-9][0-9]*)$/;
const MAX_UINT64 = 18_446_744_073_709_551_615n;
const LEVELS = ["normalized", "locally_verified", "chain_inclusion_proven"] as const;
const STATES = ["queued", "running", "partial", "succeeded", "failed", "cancelled"] as const;
const STAGES = ["queued", "validating", "capturing_trace", "verifying_bocs", "proving_inclusion", "building_native_ledger", "finalizing", "retry_wait", "terminal"] as const;
const STEP_CODES = ["trace_capture", "boc_verification", "block_inclusion", "native_ledger"] as const;
const STEP_LEVELS: Record<WalletCaseEvidenceStepCode, WalletCaseEvidenceLevel> = {
  trace_capture: "normalized",
  boc_verification: "locally_verified",
  block_inclusion: "chain_inclusion_proven",
  native_ledger: "chain_inclusion_proven",
};
const TERMINAL_STATES = new Set<WalletCaseEvidenceVerificationState>(["partial", "succeeded", "failed", "cancelled"]);
const RUNNING_STAGES = new Set<WalletCaseEvidenceVerificationStage>([
  "validating",
  "capturing_trace",
  "verifying_bocs",
  "proving_inclusion",
  "building_native_ledger",
  "finalizing",
]);

export function parseWalletCaseEvidenceVerification(value: unknown): WalletCaseEvidenceVerification {
  const item = exactRecord(value, [
    "case_public_id", "public_id", "snapshot_public_id", "activity_public_id", "policy",
    "state", "stage", "status_version", "progress", "cancel_requested",
    "highest_evidence_level", "inclusion_provenance", "provenance", "steps", "retry", "error", "limitations", "result",
    "message", "created_at", "updated_at", "started_at", "completed_at",
  ], "Wallet Case Evidence verification");
  const state = enumValue(item.state, STATES, "Evidence verification state");
  const stage = enumValue(item.stage, STAGES, "Evidence verification stage");
  const progressValue = exactRecord(item.progress, ["current", "total"], "Evidence verification progress");
  const progress = {
    current: integer(progressValue.current, "Evidence progress current"),
    total: literal(progressValue.total, 4, "Evidence progress total"),
  };
  if (progress.current > progress.total) fail("Evidence verification progress is inconsistent");

  const provenanceValue = exactRecord(item.provenance, [
    "data_origin", "provider", "identity_assurance", "source_sync_public_id", "transaction",
  ], "Evidence provenance");
  const transactionValue = exactRecord(provenanceValue.transaction, [
    "network", "wallet_account_canonical", "hash", "logical_time",
  ], "Evidence transaction provenance");
  const transactionNetwork = enumValue(transactionValue.network, ["ton-mainnet", "ton-testnet"] as const, "Evidence transaction network");
  const logicalTime = text(transactionValue.logical_time, "Evidence logical time");
  if (!LOGICAL_TIME.test(logicalTime) || BigInt(logicalTime) > MAX_UINT64) fail("Evidence logical time is invalid");
  const walletAccount = text(transactionValue.wallet_account_canonical, "Evidence wallet account");
  if (!isCanonicalRawTonAddress(walletAccount) || !WALLET_ACCOUNT.test(walletAccount)) {
    fail("Evidence wallet account is invalid");
  }
  const transactionHash = text(transactionValue.hash, "Evidence transaction hash");
  if (!HASH.test(transactionHash)) fail("Evidence transaction hash is invalid");
  const inclusionProvenance = item.inclusion_provenance === null
    ? null
    : parseInclusionProvenance(item.inclusion_provenance);

  if (!Array.isArray(item.steps) || item.steps.length !== STEP_CODES.length) {
    fail("Evidence verification steps are invalid");
  }
  const steps = item.steps.map((rawStep, index) => {
    const step = exactRecord(rawStep, ["code", "state", "evidence_level", "evidence_digest_sha256", "completed_at"], `Evidence step ${index}`);
    const code = enumValue(step.code, STEP_CODES, `Evidence step ${index} code`);
    if (code !== STEP_CODES[index]) fail("Evidence verification step order is invalid");
    const stepState = enumValue(step.state, ["pending", "succeeded"] as const, `Evidence step ${index} state`);
    const digest = nullableDigest(step.evidence_digest_sha256, `Evidence step ${index} digest`);
    const completedAt = nullableTimestamp(step.completed_at, `Evidence step ${index} completion`);
    if ((stepState === "succeeded") !== (digest !== null && completedAt !== null)) {
      fail(`Evidence step ${index} completion is inconsistent`);
    }
    const evidenceLevel = step.evidence_level === null
      ? null
      : enumValue(step.evidence_level, LEVELS, `Evidence step ${index} level`);
    if (
      (stepState === "pending" && evidenceLevel !== null) ||
      (stepState === "succeeded" && evidenceLevel !== STEP_LEVELS[code])
    ) fail(`Evidence step ${index} level is inconsistent`);
    return { code, state: stepState, evidence_level: evidenceLevel, evidence_digest_sha256: digest, completed_at: completedAt };
  });
  const completedSteps = steps.filter((step) => step.state === "succeeded").length;
  if (completedSteps !== progress.current) fail("Evidence progress does not match completed steps");
  if (steps.some((step, index) => (index < completedSteps) !== (step.state === "succeeded"))) {
    fail("Evidence verification steps are not a completed prefix");
  }

  const retry = item.retry === null ? null : (() => {
    const value = exactRecord(item.retry, ["attempt", "max_attempts", "retry_at", "reason_code", "message_safe"], "Evidence retry");
    const attempt = positiveInteger(value.attempt, "Evidence retry attempt");
    const maxAttempts = positiveInteger(value.max_attempts, "Evidence retry maximum");
    if (attempt >= maxAttempts) fail("Evidence retry budget is exhausted");
    return {
      attempt,
      max_attempts: maxAttempts,
      retry_at: timestamp(value.retry_at, "Evidence retry time"),
      reason_code: text(value.reason_code, "Evidence retry reason"),
      message_safe: text(value.message_safe, "Evidence retry message"),
    };
  })();
  if ((stage === "retry_wait") !== (retry !== null)) fail("Evidence retry state is inconsistent");

  const error = item.error === null ? null : (() => {
    const value = exactRecord(item.error, ["code", "message_safe", "retryable"], "Evidence error");
    return {
      code: text(value.code, "Evidence error code"),
      message_safe: text(value.message_safe, "Evidence error message"),
      retryable: boolean(value.retryable, "Evidence error retryable flag"),
    };
  })();
  const cancelRequested = boolean(item.cancel_requested, "Evidence cancellation flag");
  if (
    (state === "cancelled" && !cancelRequested) ||
    (state !== "running" && state !== "cancelled" && cancelRequested)
  ) fail("Evidence cancellation flag is inconsistent with its state");

  const parsedLimitations = parseLimitations(item.limitations);

  const result = item.result === null ? null : parseResult(item.result);
  if ((state === "partial" || state === "succeeded") !== (result !== null)) {
    fail("Evidence verification result is inconsistent with its state");
  }
  if (state === "partial" && !parsedLimitations.some((item) => item.code === "verification_partial")) {
    fail("Partial Evidence verification requires an explicit limitation");
  }
  if (state === "partial" && completedSteps === 0) fail("Partial Evidence verification requires a completed artifact");
  if (state === "succeeded" && completedSteps !== STEP_CODES.length) fail("Succeeded Evidence verification is incomplete");
  if (state === "failed" && completedSteps !== 0) fail("Failed Evidence verification published completed artifacts");
  if (state === "partial" && error !== null) fail("Partial Evidence verification must explain its boundary through limitations");
  if (state === "failed" && error === null) fail("Failed Evidence verification requires a safe error");
  if (result !== null && steps.some((step) => result.evidence_digests[step.code] !== step.evidence_digest_sha256)) {
    fail("Evidence result digests do not match completed steps");
  }
  if (
    (inclusionProvenance !== null) !== (progress.current >= 3) ||
    (inclusionProvenance !== null && inclusionProvenance.network !== transactionNetwork)
  ) {
    fail("Evidence inclusion provenance does not match the completed proof prefix");
  }
  if (
    result !== null &&
    !sameInclusionProvenance(result.inclusion_provenance, inclusionProvenance)
  ) fail("Evidence result inclusion provenance changed");
  if (state === "succeeded" && result?.native_ledger === null) fail("Succeeded Evidence verification requires its native ledger summary");
  if ((stage === "terminal") !== TERMINAL_STATES.has(state)) {
    fail("Evidence verification stage is inconsistent with its state");
  }
  if (state === "queued" && stage !== "queued" && stage !== "retry_wait") {
    fail("Queued Evidence verification has an invalid stage");
  }
  if (state === "running" && !RUNNING_STAGES.has(stage)) {
    fail("Running Evidence verification has an invalid stage");
  }
  if (state !== "failed" && error !== null) {
    fail("Evidence verification published an unexpected error");
  }

  const highestEvidenceLevel = enumValue(item.highest_evidence_level, LEVELS, "Highest Evidence level");
  const expectedLevel: WalletCaseEvidenceLevel = steps.some((step) => step.state === "succeeded" && step.evidence_level === "chain_inclusion_proven")
    ? "chain_inclusion_proven"
    : steps.some((step) => step.state === "succeeded" && step.evidence_level === "locally_verified")
      ? "locally_verified"
      : "normalized";
  if (highestEvidenceLevel !== expectedLevel) fail("Highest Evidence level is inconsistent with completed steps");

  const createdAt = timestamp(item.created_at, "Evidence creation time");
  const updatedAt = timestamp(item.updated_at, "Evidence update time");
  const startedAt = nullableTimestamp(item.started_at, "Evidence start time");
  const completedAt = nullableTimestamp(item.completed_at, "Evidence completion time");
  if (
    instant(updatedAt) < instant(createdAt) ||
    (startedAt !== null && instant(startedAt) < instant(createdAt)) ||
    (startedAt !== null && instant(updatedAt) < instant(startedAt)) ||
    (completedAt !== null && (instant(completedAt) < instant(createdAt) || (startedAt !== null && instant(completedAt) < instant(startedAt)))) ||
    (completedAt !== null && instant(updatedAt) < instant(completedAt)) ||
    TERMINAL_STATES.has(state) !== (completedAt !== null) ||
    (state === "queued" && stage === "queued" && startedAt !== null) ||
    (state === "running" && startedAt === null) ||
    (state === "queued" && stage === "retry_wait" && startedAt === null)
  ) fail("Evidence verification timestamps are inconsistent");

  const activityPublicId = text(item.activity_public_id, "Evidence Activity ID");
  if (!ACTIVITY_ID.test(activityPublicId)) fail("Evidence Activity ID is invalid");
  return {
    case_public_id: uuid(item.case_public_id, "Evidence case ID"),
    public_id: uuid(item.public_id, "Evidence verification ID"),
    snapshot_public_id: uuid(item.snapshot_public_id, "Evidence snapshot ID"),
    activity_public_id: activityPublicId,
    policy: literal(item.policy, "transaction_inclusion_v1", "Evidence policy"),
    state,
    stage,
    status_version: positiveInteger(item.status_version, "Evidence status version"),
    progress,
    cancel_requested: cancelRequested,
    highest_evidence_level: highestEvidenceLevel,
    inclusion_provenance: inclusionProvenance,
    provenance: {
      data_origin: literal(provenanceValue.data_origin, "provider_observed", "Evidence data origin"),
      provider: text(provenanceValue.provider, "Evidence provider"),
      identity_assurance: literal(provenanceValue.identity_assurance, "network_scoped", "Evidence identity assurance"),
      source_sync_public_id: uuid(provenanceValue.source_sync_public_id, "Evidence source sync ID"),
      transaction: {
        network: transactionNetwork,
        wallet_account_canonical: walletAccount,
        hash: transactionHash,
        logical_time: logicalTime,
      },
    },
    steps,
    retry,
    error,
    limitations: parsedLimitations,
    result,
    message: text(item.message, "Evidence message"),
    created_at: createdAt,
    updated_at: updatedAt,
    started_at: startedAt,
    completed_at: completedAt,
  };
}

export function parseWalletCaseEvidenceCatalog(value: unknown): WalletCaseEvidenceCatalog {
  const response = exactRecord(value, [
    "case_public_id", "snapshot", "aggregate", "readiness", "limitations",
    "verifications", "limit", "truncated",
  ], "Wallet Case Evidence catalog");
  const casePublicId = uuid(response.case_public_id, "Evidence catalog case ID");
  const snapshot = response.snapshot === null ? null : parseSnapshot(response.snapshot);
  const aggregateValue = exactRecord(response.aggregate, [
    "total", "returned_count", "counts_scope", "queued", "running", "partial", "succeeded", "failed", "cancelled",
    "normalized", "locally_verified", "chain_inclusion_proven",
  ], "Evidence aggregate");
  const aggregate = {
    total: integer(aggregateValue.total, "Evidence total"),
    returned_count: integer(aggregateValue.returned_count, "Returned Evidence total"),
    counts_scope: literal(aggregateValue.counts_scope, "returned_revalidated", "Evidence aggregate count scope"),
    queued: integer(aggregateValue.queued, "Queued Evidence total"),
    running: integer(aggregateValue.running, "Running Evidence total"),
    partial: integer(aggregateValue.partial, "Partial Evidence total"),
    succeeded: integer(aggregateValue.succeeded, "Succeeded Evidence total"),
    failed: integer(aggregateValue.failed, "Failed Evidence total"),
    cancelled: integer(aggregateValue.cancelled, "Cancelled Evidence total"),
    normalized: integer(aggregateValue.normalized, "Normalized Evidence total"),
    locally_verified: integer(aggregateValue.locally_verified, "Locally verified Evidence total"),
    chain_inclusion_proven: integer(aggregateValue.chain_inclusion_proven, "Chain-proven Evidence total"),
  };
  if (
    aggregate.queued + aggregate.running + aggregate.partial + aggregate.succeeded + aggregate.failed + aggregate.cancelled !== aggregate.returned_count ||
    aggregate.normalized + aggregate.locally_verified + aggregate.chain_inclusion_proven !== aggregate.returned_count
  ) fail("Evidence aggregate is inconsistent");

  const readinessValue = exactRecord(response.readiness, [
    "transaction_verification_available", "report_available", "highest_evidence_level",
  ], "Evidence readiness");
  const readiness = {
    transaction_verification_available: boolean(readinessValue.transaction_verification_available, "Evidence availability"),
    report_available: boolean(readinessValue.report_available, "Evidence report availability"),
    highest_evidence_level: readinessValue.highest_evidence_level === null
      ? null
      : enumValue(readinessValue.highest_evidence_level, LEVELS, "Catalog highest Evidence level"),
  };
  const limitations = parseLimitations(response.limitations);
  if (!Array.isArray(response.verifications)) fail("Evidence catalog verifications are invalid");
  const verifications = response.verifications.map(parseWalletCaseEvidenceVerification);
  const limit = literal(response.limit, 50, "Evidence catalog limit");
  const truncated = boolean(response.truncated, "Evidence catalog truncation flag");
  if (
    verifications.length > limit || aggregate.returned_count !== verifications.length || aggregate.returned_count > aggregate.total ||
    new Set(verifications.map((item) => item.public_id)).size !== verifications.length ||
    verifications.some((item) => item.case_public_id !== casePublicId) ||
    (snapshot !== null && verifications.some((item) => item.snapshot_public_id !== snapshot.public_id)) ||
    truncated !== (aggregate.total > aggregate.returned_count) ||
    (truncated && !limitations.some((item) => item.code === "catalog_history_not_revalidated"))
  ) fail("Evidence catalog entries are inconsistent");
  if (snapshot === null) {
    if (
      aggregate.total !== 0 || verifications.length !== 0 || readiness.transaction_verification_available || readiness.report_available ||
      !limitations.some((item) => item.code === "not_synchronized")
    ) fail("Unsynchronized Evidence catalog published verification state");
  } else if (!readiness.report_available ||
    (snapshot.data_mode === "mock" && (
      readiness.transaction_verification_available ||
      !limitations.some((item) => item.code === "demo_evidence_not_verifiable")
    )) ||
    (readiness.transaction_verification_available && limitations.some((item) => [
      "demo_evidence_not_verifiable",
      "evidence_runner_unavailable",
      "evidence_runtime_unavailable",
    ].includes(item.code))) ||
    (snapshot.data_mode === "real" && !readiness.transaction_verification_available && !limitations.some((item) => [
      "evidence_runner_unavailable",
      "evidence_runtime_unavailable",
    ].includes(item.code)))
  ) {
    fail("Evidence catalog availability is inconsistent");
  }
  if (aggregate.total === 0 && readiness.highest_evidence_level !== null) {
    fail("Empty Evidence catalog cannot publish an Evidence level");
  }
  const aggregateHighest: WalletCaseEvidenceLevel | null = aggregate.chain_inclusion_proven > 0
    ? "chain_inclusion_proven"
    : aggregate.locally_verified > 0
      ? "locally_verified"
      : aggregate.normalized > 0
        ? "normalized"
        : null;
  if (readiness.highest_evidence_level !== aggregateHighest) fail("Catalog highest Evidence level is inconsistent");
  return { case_public_id: casePublicId, snapshot, aggregate, readiness, limitations, verifications, limit, truncated };
}

export function walletCaseEvidenceEligibility(item: WalletCaseActivityItem | null): { eligible: boolean; code: string; message: string } {
  if (item === null) return { eligible: false, code: "no_activity_selected", message: "Choose a transaction from Activity to verify its evidence." };
  if (item.kind !== "transaction") return { eligible: false, code: "transaction_required", message: "Transfers and swaps are provider-derived actions. Open their authoritative transaction only when a proven linkage becomes available." };
  if (item.provenance.data_origin !== "provider_observed") return { eligible: false, code: "live_observation_required", message: "Demo fixtures cannot be promoted to locally verified or chain-inclusion evidence." };
  if (item.provenance.identity_assurance !== "network_scoped" || item.transaction.linkage !== "self" || item.transaction.hash === null) {
    return { eligible: false, code: "canonical_transaction_required", message: "Verification requires a network-scoped transaction identity and its canonical transaction hash." };
  }
  return { eligible: true, code: "eligible", message: "This provider-observed transaction has the canonical identity required for the verification pipeline." };
}

export function isActiveWalletCaseEvidenceVerification(value: WalletCaseEvidenceVerification | null): boolean {
  return value !== null && (value.state === "queued" || value.state === "running");
}

function parseResult(value: unknown): NonNullable<WalletCaseEvidenceVerification["result"]> {
  const result = exactRecord(value, ["verification_digest_sha256", "evidence_digests", "inclusion_provenance", "native_ledger"], "Evidence result");
  const digestValue = exactRecord(result.evidence_digests, [...STEP_CODES], "Evidence result digests");
  const evidenceDigests = Object.fromEntries(STEP_CODES.map((code) => [code, nullableDigest(digestValue[code], `Evidence ${code} result digest`)])) as Record<WalletCaseEvidenceStepCode, string | null>;
  const inclusionProvenance = result.inclusion_provenance === null
    ? null
    : parseInclusionProvenance(result.inclusion_provenance);
  const nativeLedger = result.native_ledger === null ? null : (() => {
    const ledger = exactRecord(result.native_ledger, [
      "evidence_digest_sha256", "activity_count", "incoming_nanoton", "outgoing_nanoton", "self_nanoton",
      "native_ton_only", "selected_evidence_only", "is_authoritative_activity_ledger",
      "establishes_complete_wallet_history", "eligible_for_cost_basis", "used_by_pnl", "message",
    ], "Evidence native ledger summary");
    return {
      evidence_digest_sha256: digest(ledger.evidence_digest_sha256, "Native ledger digest"),
      activity_count: integer(ledger.activity_count, "Native ledger activity count"),
      incoming_nanoton: nanoton(ledger.incoming_nanoton, "Native ledger incoming amount"),
      outgoing_nanoton: nanoton(ledger.outgoing_nanoton, "Native ledger outgoing amount"),
      self_nanoton: nanoton(ledger.self_nanoton, "Native ledger self-transfer amount"),
      native_ton_only: literal(ledger.native_ton_only, true, "Native ledger asset scope"),
      selected_evidence_only: literal(ledger.selected_evidence_only, true, "Native ledger evidence scope"),
      is_authoritative_activity_ledger: literal(ledger.is_authoritative_activity_ledger, false, "Native ledger authority"),
      establishes_complete_wallet_history: literal(ledger.establishes_complete_wallet_history, false, "Native ledger history scope"),
      eligible_for_cost_basis: literal(ledger.eligible_for_cost_basis, false, "Native ledger cost-basis eligibility"),
      used_by_pnl: literal(ledger.used_by_pnl, false, "Native ledger PnL usage"),
      message: text(ledger.message, "Native ledger message"),
    };
  })();
  if ((evidenceDigests.native_ledger !== null) !== (nativeLedger !== null)) {
    fail("Native ledger summary does not match its Evidence digest");
  }
  if (nativeLedger !== null && nativeLedger.evidence_digest_sha256 !== evidenceDigests.native_ledger) {
    fail("Native ledger summary digest does not match its Evidence result");
  }
  return {
    verification_digest_sha256: digest(result.verification_digest_sha256, "Evidence verification digest"),
    evidence_digests: evidenceDigests,
    inclusion_provenance: inclusionProvenance,
    native_ledger: nativeLedger,
  };
}

function parseInclusionProvenance(value: unknown): WalletCaseEvidenceInclusionProvenance {
  const provenance = exactRecord(value, [
    "canonical_block_chain_verified_at_capture",
    "checkpoint_to_observed_head_transcript_persisted",
    "contract_version",
    "network",
    "trust_level",
    "trusted_checkpoint",
    "verifier_policy_id",
  ], "Evidence inclusion provenance");
  const network = enumValue(
    provenance.network,
    ["ton-mainnet", "ton-testnet"] as const,
    "Evidence inclusion network",
  );
  if (!isCurrentTransactionInclusionCheckpoint(network, provenance.trusted_checkpoint)) {
    fail("Evidence inclusion checkpoint is invalid");
  }
  return {
    contract_version: literal(provenance.contract_version, "ton_transaction_inclusion_v2", "Evidence inclusion contract"),
    network,
    verifier_policy_id: literal(provenance.verifier_policy_id, CURRENT_TRANSACTION_INCLUSION_POLICY, "Evidence inclusion verifier policy"),
    trust_level: literal(provenance.trust_level, 0, "Evidence inclusion trust level"),
    trusted_checkpoint: provenance.trusted_checkpoint,
    canonical_block_chain_verified_at_capture: literal(provenance.canonical_block_chain_verified_at_capture, true, "Evidence canonical chain flag"),
    checkpoint_to_observed_head_transcript_persisted: literal(provenance.checkpoint_to_observed_head_transcript_persisted, false, "Evidence inclusion transcript flag"),
  };
}

function sameInclusionProvenance(
  left: WalletCaseEvidenceInclusionProvenance | null,
  right: WalletCaseEvidenceInclusionProvenance | null,
): boolean {
  if (left === null || right === null) return left === right;
  return (
    left.contract_version === right.contract_version &&
    left.network === right.network &&
    left.verifier_policy_id === right.verifier_policy_id &&
    left.trust_level === right.trust_level &&
    left.canonical_block_chain_verified_at_capture ===
      right.canonical_block_chain_verified_at_capture &&
    left.checkpoint_to_observed_head_transcript_persisted ===
      right.checkpoint_to_observed_head_transcript_persisted &&
    left.trusted_checkpoint.workchain === right.trusted_checkpoint.workchain &&
    left.trusted_checkpoint.shard === right.trusted_checkpoint.shard &&
    left.trusted_checkpoint.seqno === right.trusted_checkpoint.seqno &&
    left.trusted_checkpoint.root_hash === right.trusted_checkpoint.root_hash &&
    left.trusted_checkpoint.file_hash === right.trusted_checkpoint.file_hash
  );
}

function parseSnapshot(value: unknown): WalletCaseActivitySnapshot {
  const item = exactRecord(value, ["public_id", "state", "completed_at", "data_mode", "provider", "requested_period", "coverage"], "Evidence snapshot");
  const periodValue = exactRecord(item.requested_period, ["start_at", "end_at"], "Evidence snapshot period");
  const requestedPeriod = {
    start_at: timestamp(periodValue.start_at, "Evidence snapshot period start"),
    end_at: timestamp(periodValue.end_at, "Evidence snapshot period end"),
  };
  if (instant(requestedPeriod.start_at) >= instant(requestedPeriod.end_at)) fail("Evidence snapshot period is invalid");
  const coverage = parseWalletCaseCoverage(item.coverage);
  if (coverage.requested_start_at !== requestedPeriod.start_at || coverage.requested_end_at !== requestedPeriod.end_at) {
    fail("Evidence snapshot coverage does not match its period");
  }
  return {
    public_id: uuid(item.public_id, "Evidence snapshot ID"),
    state: enumValue(item.state, ["partial", "succeeded"] as const, "Evidence snapshot state"),
    completed_at: timestamp(item.completed_at, "Evidence snapshot completion"),
    data_mode: enumValue(item.data_mode, ["mock", "real"] as const, "Evidence snapshot data mode"),
    provider: text(item.provider, "Evidence snapshot provider"),
    requested_period: requestedPeriod,
    coverage,
  };
}

function parseLimitations(value: unknown): WalletCaseLimitation[] {
  if (!Array.isArray(value)) fail("Evidence limitations are invalid");
  const parsed = value.map((raw, index) => {
    const item = exactRecord(raw, ["code", "message"], `Evidence limitation ${index}`);
    return { code: text(item.code, `Evidence limitation ${index} code`), message: text(item.message, `Evidence limitation ${index} message`) };
  });
  if (new Set(parsed.map((item) => item.code)).size !== parsed.length) fail("Evidence limitations contain duplicate codes");
  return parsed;
}

function exactRecord(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${label} must be an object`);
  const record = value as Record<string, unknown>;
  const actual = Object.keys(record).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(`${label} fields are invalid`);
  return record;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0 || value.length > 2_000 || value.trim() !== value) fail(`${label} is invalid`);
  return value;
}

function uuid(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!UUID_V4.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function digest(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!DIGEST.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function nullableDigest(value: unknown, label: string): string | null {
  return value === null ? null : digest(value, label);
}

function nanoton(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!NANOTON.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function timestamp(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (parseRfc3339Instant(parsed, { maximumFractionDigits: 6 }) === null) fail(`${label} is invalid`);
  return parsed;
}

function nullableTimestamp(value: unknown, label: string): string | null {
  return value === null ? null : timestamp(value, label);
}

function instant(value: string): bigint {
  const parsed = parseRfc3339Instant(value, { maximumFractionDigits: 6 });
  if (parsed === null) fail("Evidence timestamp is invalid");
  return parsed;
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) fail(`${label} is invalid`);
  return value as number;
}

function positiveInteger(value: unknown, label: string): number {
  const parsed = integer(value, label);
  if (parsed < 1) fail(`${label} is invalid`);
  return parsed;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") fail(`${label} is invalid`);
  return value;
}

function literal<T extends string | number | boolean>(value: unknown, expected: T, label: string): T {
  if (value !== expected) fail(`${label} is invalid`);
  return expected;
}

function enumValue<T extends string>(value: unknown, allowed: readonly T[], label: string): T {
  if (typeof value !== "string" || !allowed.includes(value as T)) fail(`${label} is invalid`);
  return value as T;
}

function fail(message: string): never {
  throw new Error(message);
}
