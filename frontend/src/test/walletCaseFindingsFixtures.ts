import type { WalletCaseFindingsResponse } from "../walletCaseFindings";
import type { WalletCaseCoverage } from "../walletCase";
import { ACTIVITY_ID, ASSET_ID, SECOND_ACTIVITY_ID } from "./walletCaseActivityFixtures";
import { CASE_ID, SYNC_ID } from "./walletCaseFixtures";

const HASH = "f".repeat(64);
export const COUNTERPARTY = `0:${"2".repeat(64)}`;

export function walletCaseFindingsFixture(): WalletCaseFindingsResponse {
  const coverage: WalletCaseCoverage = {
    state: "bounded_complete" as const,
    requested_start_at: "2026-08-08T12:00:00Z",
    requested_end_at: "2026-08-09T12:00:00Z",
    requested_surfaces: ["transactions", "transfers", "swaps"],
    unavailable_surfaces: [],
    incomplete_surfaces: [],
    streams: [],
    full_history_proven: false as const,
  };
  return {
    case_public_id: CASE_ID,
    snapshot_public_id: SYNC_ID,
    findings: {
      contract_version: "wallet_case_findings_v1",
      public_id: `fset_${HASH}`,
      content_hash_sha256: HASH,
      case_public_id: CASE_ID,
      snapshot_public_id: SYNC_ID,
      subject: {
        network: "ton-mainnet",
        data_environment: "live",
        wallet_account_canonical: `0:${"a".repeat(64)}`,
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
          total_items: 3,
          transactions: 1,
          transfers: 1,
          swaps: 1,
          failed_transactions: 1,
          source_sync_count: 1,
          suppressed_duplicate_observations: 0,
          conflicted_identity_count: 0,
        },
        observed_period: {
          start_at: "2026-08-09T09:00:00Z",
          end_at: "2026-08-09T11:00:00.000001Z",
        },
      },
      evidence_revision: {
        digest_sha256: "b".repeat(64),
        total_attempts: 1,
        returned_revalidated: 1,
        history_truncated: false,
      },
      flows: {
        identified_asset_count: 1,
        returned_asset_count: 1,
        assets_truncated: false,
        unavailable_asset_observations: 0,
        identified_counterparty_count: 1,
        returned_counterparty_count: 1,
        counterparties_truncated: false,
        unavailable_counterparty_observations: 0,
        recognized_protocol_count: 1,
        returned_protocol_count: 1,
        protocols_truncated: false,
        unrecognized_protocol_observations: 0,
        asset_flows: [{
          asset_id: ASSET_ID,
          network: "ton-mainnet",
          standard: "native",
          contract_address: null,
          symbol: "TON",
          inflow_amount: "12.5",
          outflow_amount: "3",
          inflow_observations: 1,
          outflow_observations: 1,
          unknown_direction_observations: 0,
          amount_unavailable_observations: 0,
          supporting_activity_ids: [ACTIVITY_ID, SECOND_ACTIVITY_ID],
          support_truncated: false,
        }],
        counterparty_flows: [{
          canonical_address: COUNTERPARTY,
          incoming_observations: 2,
          outgoing_observations: 0,
          unknown_direction_observations: 0,
          supporting_activity_ids: [ACTIVITY_ID, SECOND_ACTIVITY_ID],
          support_truncated: false,
        }],
        protocol_flows: [{
          protocol_id: "stonfi_v2",
          family: "stonfi",
          version: "v2",
          label: "STON.fi v2",
          swap_observations: 1,
          supporting_activity_ids: [SECOND_ACTIVITY_ID],
          support_truncated: false,
        }],
      },
      findings: [{
        public_id: `finding_${"1".repeat(64)}`,
        rule_id: "failed_transaction_observations_v1",
        category: "transaction_outcome",
        importance: "attention",
        title: "Failed transaction observations",
        explanation: "A normalized transaction row reports a failed outcome; this is not a risk classification.",
        affected_count: 1,
        support_basis: "activity_rows",
        supporting_activities: [{
          activity_public_id: ACTIVITY_ID,
          kind: "transaction",
          occurred_at: "2026-08-09T09:00:00Z",
          evidence_level: "chain_inclusion_proven",
        }],
        support_truncated: false,
        evidence_level: "chain_inclusion_proven",
      }, {
        public_id: `finding_${"2".repeat(64)}`,
        rule_id: "recognized_protocol_observations_v1",
        category: "flow_pattern",
        importance: "information",
        title: "Recognized protocol observations: STON.fi v2",
        explanation: "One swap observation uses the published protocol registry identity; this is not an endorsement.",
        affected_count: 1,
        support_basis: "activity_rows",
        supporting_activities: [{
          activity_public_id: SECOND_ACTIVITY_ID,
          kind: "swap",
          occurred_at: "2026-08-09T11:00:00Z",
          evidence_level: "normalized_provider_observation",
        }],
        support_truncated: false,
        evidence_level: "normalized_provider_observation",
      }],
      gaps: [],
      limitations: [{
        code: "rule_based_findings_only",
        message: "Findings are deterministic published rules, not an opaque risk score.",
      }, {
        code: "absence_of_findings_not_safety",
        message: "No finding must not be interpreted as a safe wallet classification.",
      }],
      truth_boundaries: {
        establishes_complete_wallet_history: false,
        establishes_ownership_or_control: false,
        establishes_illicit_or_safe_status: false,
        absence_of_findings_means_safe: false,
        cross_asset_amounts_are_comparable: false,
        includes_raw_provider_payloads: false,
      },
    },
    limitations: [],
  };
}

export function unsynchronizedWalletCaseFindingsFixture(): WalletCaseFindingsResponse {
  return {
    case_public_id: CASE_ID,
    snapshot_public_id: null,
    findings: null,
    limitations: [{ code: "not_synchronized", message: "Synchronize this Wallet Case before reviewing findings." }],
  };
}
