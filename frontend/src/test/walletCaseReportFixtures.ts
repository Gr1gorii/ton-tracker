import type { WalletCaseReportResponse } from "../walletCaseReport";
import type { WalletCaseCoverage } from "../walletCase";
import { CASE_ID, SYNC_ID } from "./walletCaseFixtures";

const CONTENT_HASH = "f".repeat(64);

export function walletCaseReportFixture(): WalletCaseReportResponse {
  const coverage: WalletCaseCoverage = {
    state: "bounded_complete" as const,
    requested_start_at: "2026-08-08T12:00:00Z",
    requested_end_at: "2026-08-09T12:00:00Z",
    requested_surfaces: ["transactions"],
    unavailable_surfaces: [],
    incomplete_surfaces: [],
    streams: [],
    full_history_proven: false as const,
  };
  return {
    case_public_id: CASE_ID,
    snapshot_public_id: SYNC_ID,
    report: {
      contract_version: "wallet_case_report_v1",
      public_id: `rpt_${CONTENT_HASH}`,
      content_hash_sha256: CONTENT_HASH,
      case_public_id: CASE_ID,
      snapshot_public_id: SYNC_ID,
      assurance_level: "normalized",
      subject: {
        network: "ton-mainnet",
        data_environment: "live",
        wallet_account_canonical: `0:${"1".repeat(64)}`,
      },
      snapshot: {
        public_id: SYNC_ID,
        state: "succeeded",
        completed_at: "2026-08-09T12:01:00Z",
        data_mode: "real",
        provider: "tonapi_wallet_activity_live",
        requested_period: {
          start_at: coverage.requested_start_at,
          end_at: coverage.requested_end_at,
        },
        coverage,
      },
      activity_revision: {
        digest_sha256: "a".repeat(64),
        aggregate: {
          total_items: 1,
          transactions: 1,
          transfers: 0,
          swaps: 0,
          failed_transactions: 0,
          source_sync_count: 1,
          suppressed_duplicate_observations: 0,
          conflicted_identity_count: 0,
        },
        observed_period: {
          start_at: "2026-08-08T13:00:00Z",
          end_at: "2026-08-08T13:00:00.000001Z",
        },
      },
      evidence_revision: {
        digest_sha256: "b".repeat(64),
        total_attempts: 0,
        returned_revalidated: 0,
        history_truncated: false,
        selected_activity_count: 0,
        locally_verified_activity_count: 0,
        chain_inclusion_proven_activity_count: 0,
        native_ledger_activity_count: 0,
      },
      coverage,
      gaps: [],
      canonical_gate: {
        eligible: false,
        unmet: [
          "full_history_proof_required",
          "every_transaction_must_be_chain_proven",
          "every_transaction_needs_native_ledger",
        ],
      },
      limitations: [
        { code: "selective_evidence_report", message: "Only explicitly selected transactions have evidence verification attempts." },
        { code: "canonical_gate_locked", message: "Canonical assurance remains locked until every published hard gate is met." },
      ],
      unverified_claims: [
        { code: "full_history_proof_required", message: "The pinned interval does not establish complete wallet history.", affected_count: null },
        { code: "every_transaction_must_be_chain_proven", message: "Not every transaction has a checkpoint-bound inclusion proof.", affected_count: 1 },
        { code: "every_transaction_needs_native_ledger", message: "Not every transaction has a completed native ledger artifact.", affected_count: 1 },
      ],
      truth_boundaries: {
        establishes_complete_wallet_history: false,
        eligible_for_cost_basis: false,
        used_by_pnl: false,
        includes_raw_provider_payloads: false,
        provider_free_full_report_revalidation: false,
      },
    },
    limitations: [],
  };
}

export function unsynchronizedWalletCaseReportFixture(): WalletCaseReportResponse {
  return {
    case_public_id: CASE_ID,
    snapshot_public_id: null,
    report: null,
    limitations: [{ code: "not_synchronized", message: "Synchronize this Wallet Case before building a report." }],
  };
}
