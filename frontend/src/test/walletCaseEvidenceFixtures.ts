import type {
  WalletCaseEvidenceCatalog,
  WalletCaseEvidenceVerification,
} from "../walletCaseEvidence";
import { ACTIVITY_ID, TRANSACTION_HASH } from "./walletCaseActivityFixtures";
import { CASE_ID, coverageFixture, SYNC_ID } from "./walletCaseFixtures";
import { currentTransactionInclusionCheckpoint } from "../walletTransactionInclusion";

export const VERIFICATION_ID = "550e8400-e29b-41d4-a716-446655440010";
export const SECOND_VERIFICATION_ID = "550e8400-e29b-41d4-a716-446655440011";
export const TRACE_DIGEST = "a".repeat(64);
export const BOC_DIGEST = "b".repeat(64);
export const INCLUSION_DIGEST = "c".repeat(64);
export const LEDGER_DIGEST = "d".repeat(64);
export const VERIFICATION_DIGEST = "e".repeat(64);

export function inclusionProvenanceFixture(
  network: "ton-mainnet" | "ton-testnet" = "ton-mainnet",
) {
  return {
    contract_version: "ton_transaction_inclusion_v2" as const,
    network,
    verifier_policy_id: "ton_liteserver_checkpoint_strict_2026_08_v2" as const,
    trust_level: 0 as const,
    trusted_checkpoint: currentTransactionInclusionCheckpoint(network),
    canonical_block_chain_verified_at_capture: true as const,
    checkpoint_to_observed_head_transcript_persisted: false as const,
  };
}

export function queuedEvidenceVerificationFixture(
  overrides: Partial<WalletCaseEvidenceVerification> = {},
): WalletCaseEvidenceVerification {
  return {
    case_public_id: CASE_ID,
    public_id: VERIFICATION_ID,
    snapshot_public_id: SYNC_ID,
    activity_public_id: ACTIVITY_ID,
    policy: "transaction_inclusion_v1",
    state: "queued",
    stage: "queued",
    status_version: 1,
    progress: { current: 0, total: 4 },
    cancel_requested: false,
    highest_evidence_level: "normalized",
    inclusion_provenance: null,
    provenance: {
      data_origin: "provider_observed",
      provider: "tonapi",
      identity_assurance: "network_scoped",
      source_sync_public_id: SYNC_ID,
      transaction: {
        network: "ton-mainnet",
        wallet_account_canonical: `0:${"a".repeat(64)}`,
        hash: TRANSACTION_HASH,
        logical_time: "45000000000000",
      },
    },
    steps: [
      pendingStep("trace_capture"),
      pendingStep("boc_verification"),
      pendingStep("block_inclusion"),
      pendingStep("native_ledger"),
    ],
    retry: null,
    error: null,
    limitations: [{
      code: "selected_transaction_only",
      message: "This job verifies only the explicitly selected transaction.",
    }],
    result: null,
    message: "Transaction evidence verification is queued.",
    created_at: "2026-08-10T12:00:00Z",
    updated_at: "2026-08-10T12:00:00Z",
    started_at: null,
    completed_at: null,
    ...overrides,
  };
}

export function retryWaitEvidenceVerificationFixture(
  overrides: Partial<WalletCaseEvidenceVerification> = {},
): WalletCaseEvidenceVerification {
  return queuedEvidenceVerificationFixture({
    stage: "retry_wait",
    status_version: 3,
    retry: {
      attempt: 1,
      max_attempts: 3,
      retry_at: "2026-08-10T12:01:30Z",
      reason_code: "provider_unavailable",
      message_safe: "The proof provider is temporarily unavailable.",
    },
    message: "Evidence verification will retry within its bounded budget.",
    updated_at: "2026-08-10T12:01:00Z",
    started_at: "2026-08-10T12:00:01Z",
    ...overrides,
  });
}

export function runningEvidenceVerificationFixture(
  completed = 2,
  overrides: Partial<WalletCaseEvidenceVerification> = {},
): WalletCaseEvidenceVerification {
  const completedSteps = [
    succeededStep("trace_capture", "normalized", TRACE_DIGEST, "2026-08-10T12:00:10Z"),
    succeededStep("boc_verification", "locally_verified", BOC_DIGEST, "2026-08-10T12:00:20Z"),
    succeededStep("block_inclusion", "chain_inclusion_proven", INCLUSION_DIGEST, "2026-08-10T12:00:30Z"),
    succeededStep("native_ledger", "chain_inclusion_proven", LEDGER_DIGEST, "2026-08-10T12:00:40Z"),
  ];
  const pendingSteps = ["trace_capture", "boc_verification", "block_inclusion", "native_ledger"].map(
    (code) => pendingStep(code as WalletCaseEvidenceVerification["steps"][number]["code"]),
  );
  return queuedEvidenceVerificationFixture({
    state: "running",
    stage: completed < 1 ? "capturing_trace" : completed < 2 ? "verifying_bocs" : completed < 3 ? "proving_inclusion" : completed < 4 ? "building_native_ledger" : "finalizing",
    status_version: completed + 2,
    progress: { current: completed, total: 4 },
    highest_evidence_level: completed >= 3 ? "chain_inclusion_proven" : completed >= 2 ? "locally_verified" : "normalized",
    inclusion_provenance: completed >= 3 ? inclusionProvenanceFixture() : null,
    steps: pendingSteps.map((step, index) => index < completed ? completedSteps[index] : step),
    message: "Evidence verification is progressing through bounded stages.",
    updated_at: `2026-08-10T12:00:${String(Math.max(1, completed * 10)).padStart(2, "0")}Z`,
    started_at: "2026-08-10T12:00:01Z",
    ...overrides,
  });
}

export function partialEvidenceVerificationFixture(
  overrides: Partial<WalletCaseEvidenceVerification> = {},
): WalletCaseEvidenceVerification {
  return runningEvidenceVerificationFixture(2, {
    state: "partial",
    stage: "terminal",
    status_version: 6,
    error: null,
    limitations: [{
      code: "verification_partial",
      message: "Trace capture and local BOC verification succeeded; block inclusion was not proven.",
    }],
    result: {
      verification_digest_sha256: VERIFICATION_DIGEST,
      evidence_digests: {
        trace_capture: TRACE_DIGEST,
        boc_verification: BOC_DIGEST,
        block_inclusion: null,
        native_ledger: null,
      },
      inclusion_provenance: null,
      native_ledger: null,
    },
    message: "Partial evidence was preserved with an explicit verification boundary.",
    updated_at: "2026-08-10T12:01:00Z",
    completed_at: "2026-08-10T12:01:00Z",
    ...overrides,
  });
}

export function succeededEvidenceVerificationFixture(
  overrides: Partial<WalletCaseEvidenceVerification> = {},
): WalletCaseEvidenceVerification {
  return runningEvidenceVerificationFixture(4, {
    state: "succeeded",
    stage: "terminal",
    status_version: 8,
    result: {
      verification_digest_sha256: VERIFICATION_DIGEST,
      evidence_digests: {
        trace_capture: TRACE_DIGEST,
        boc_verification: BOC_DIGEST,
        block_inclusion: INCLUSION_DIGEST,
        native_ledger: LEDGER_DIGEST,
      },
      inclusion_provenance: inclusionProvenanceFixture(),
      native_ledger: {
        evidence_digest_sha256: LEDGER_DIGEST,
        activity_count: 1,
        incoming_nanoton: "1000000000",
        outgoing_nanoton: "250000000",
        self_nanoton: "0",
        native_ton_only: true,
        selected_evidence_only: true,
        is_authoritative_activity_ledger: false,
        establishes_complete_wallet_history: false,
        eligible_for_cost_basis: false,
        used_by_pnl: false,
        message: "This artifact contains only selected native TON evidence.",
      },
    },
    message: "Selected transaction evidence verification completed.",
    updated_at: "2026-08-10T12:01:10Z",
    completed_at: "2026-08-10T12:01:10Z",
    ...overrides,
  });
}

export function evidenceCatalogFixture({
  verifications = [],
  total = verifications.length,
  transactionVerificationAvailable = true,
  limitations,
}: {
  verifications?: WalletCaseEvidenceVerification[];
  total?: number;
  transactionVerificationAvailable?: boolean;
  limitations?: WalletCaseEvidenceCatalog["limitations"];
} = {}): WalletCaseEvidenceCatalog {
  const states = count(verifications, (entry) => entry.state);
  const levels = count(verifications, (entry) => entry.highest_evidence_level);
  const aggregate = {
    total,
    returned_count: verifications.length,
    counts_scope: "returned_revalidated" as const,
    queued: states.queued ?? 0,
    running: states.running ?? 0,
    partial: states.partial ?? 0,
    succeeded: states.succeeded ?? 0,
    failed: states.failed ?? 0,
    cancelled: states.cancelled ?? 0,
    normalized: levels.normalized ?? 0,
    locally_verified: levels.locally_verified ?? 0,
    chain_inclusion_proven: levels.chain_inclusion_proven ?? 0,
  };
  const highest = aggregate.chain_inclusion_proven > 0
    ? "chain_inclusion_proven"
    : aggregate.locally_verified > 0
      ? "locally_verified"
      : aggregate.normalized > 0
        ? "normalized"
        : null;
  return {
    case_public_id: CASE_ID,
    snapshot: {
      public_id: SYNC_ID,
      state: "succeeded",
      completed_at: "2026-08-09T12:01:00Z",
      data_mode: "real",
      provider: "tonapi_wallet_activity_live",
      requested_period: {
        start_at: "2026-08-08T12:00:00Z",
        end_at: "2026-08-09T12:00:00Z",
      },
      coverage: coverageFixture(),
    },
    aggregate,
    readiness: {
      transaction_verification_available: transactionVerificationAvailable,
      report_available: false,
      highest_evidence_level: highest,
    },
    limitations: limitations ?? [
      { code: "selective_transaction_evidence", message: "Only selected transactions are verified." },
      { code: "report_not_built", message: "A Wallet Case report is not built yet." },
      ...(total > verifications.length ? [{ code: "catalog_history_not_revalidated", message: "Aggregate counts cover only returned revalidated attempts." }] : []),
    ],
    verifications,
    limit: 50,
    truncated: total > verifications.length,
  };
}

export function liveEvidenceActivityDetailFixture() {
  return {
    case_public_id: CASE_ID,
    snapshot_public_id: SYNC_ID,
    item: {
      public_id: ACTIVITY_ID,
      kind: "transaction" as const,
      occurred_at: "2026-08-09T11:00:00Z",
      logical_time: "45000000000000",
      direction: null,
      outcome: "success" as const,
      counterparty: null,
      assets: [],
      protocol: null,
      transaction: { linkage: "self" as const, hash: TRANSACTION_HASH, event_id: null },
      details: { kind: "transaction" as const, fee_ton: "0.01" },
      provenance: {
        data_origin: "provider_observed" as const,
        evidence_level: "normalized_provider_observation" as const,
        provider: "tonapi",
        source_status: "confirmed",
        identity_assurance: "network_scoped" as const,
        deduplication_basis: "transaction_identity" as const,
        observation_count: 1,
        suppressed_count: 0,
        first_seen_sync_public_id: SYNC_ID,
        last_seen_sync_public_id: SYNC_ID,
      },
      limitations: [{ code: "provider_observation", message: "This row is provider observed until verified." }],
    },
    source_observations: [{
      sync_public_id: SYNC_ID,
      observed_at: "2026-08-09T11:00:00Z",
      provider: "tonapi",
      source_status: "confirmed",
      data_origin: "provider_observed" as const,
    }],
    sources_truncated: false,
  };
}

function pendingStep(code: WalletCaseEvidenceVerification["steps"][number]["code"]) {
  return { code, state: "pending" as const, evidence_level: null, evidence_digest_sha256: null, completed_at: null };
}

function succeededStep(
  code: WalletCaseEvidenceVerification["steps"][number]["code"],
  evidenceLevel: NonNullable<WalletCaseEvidenceVerification["steps"][number]["evidence_level"]>,
  digest: string,
  completedAt: string,
) {
  return { code, state: "succeeded" as const, evidence_level: evidenceLevel, evidence_digest_sha256: digest, completed_at: completedAt };
}

function count<T extends string>(values: WalletCaseEvidenceVerification[], select: (entry: WalletCaseEvidenceVerification) => T): Partial<Record<T, number>> {
  return values.reduce<Partial<Record<T, number>>>((result, entry) => {
    const key = select(entry);
    result[key] = (result[key] ?? 0) + 1;
    return result;
  }, {});
}
