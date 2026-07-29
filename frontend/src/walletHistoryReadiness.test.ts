import { describe, expect, it } from "vitest";

import type { WalletHistoryIntervalCoverageLayerRecord } from "./types";
import {
  historyCoveragePercent,
  validateWalletHistoryReadiness,
} from "./walletHistoryReadiness";

const ids = [3, 1];

function identity() {
  return {
    status: "network_scoped",
    version: "ton_wallet_identity_v1",
    network: "ton-mainnet",
    canonical_address: "0:abc",
    workchain_id: 0,
    account_id_hex: "abc",
    submitted_format: "user_friendly",
    bounceable: false,
    testnet_only: false,
    is_account_existence_proof: false,
    is_ownership_proof: false,
  };
}

function layer(stream: "transactions" | "account_events") {
  return {
    stream_key: stream,
    coverage_kind: stream === "transactions" ? "low_level_transaction_stream" : "provider_display_event_stream",
    eligible_state: stream === "transactions" ? "complete" : "provider_stream_complete",
    provider_semantics: stream === "transactions" ? "bounded_low_level_transaction_query" : "display_only_actions",
    state: "no_validated_intervals",
    selected_run_count: 2,
    requested_run_count: 2,
    included_run_count: 0,
    included_run_ids: [] as number[],
    excluded_run_ids: [3, 1],
    not_requested_run_ids: [] as number[],
    selected_run_coverage_state: "none",
    run_evidence: ids.map((runId) => ({
      run_id: runId,
      source_state: "missing",
      candidate_states: ["missing"],
      classification: "excluded",
      reason: "state_not_eligible",
      source_reason_codes: ["stream_missing"],
      recorded_interval_start: null,
      recorded_interval_end: null,
      interval_start: null,
      interval_end: null,
      duration_microseconds: null,
      included_in_union: false,
    })),
    accepted_intervals: [],
    selected_span: null,
    union_intervals: [],
    overlap_intervals: [],
    gap_intervals: [],
    span_duration_microseconds: "0",
    covered_duration_microseconds: "0",
    gap_duration_microseconds: "0",
    overlapped_duration_microseconds: "0",
    max_coverage_depth: 0,
    is_contiguous_within_selected_span: false,
    outside_selected_span_coverage: "unknown",
    establishes_full_history: false,
    is_authoritative_activity_coverage: false,
  };
}

function coverage() {
  return {
    activity_observations: 14,
    timestamped_activity_observations: 14,
    transaction_observations: 6,
    transaction_observations_with_hash: 6,
    transaction_observations_with_exact_identity: 0,
    transaction_observations_with_weak_identity: 6,
    transaction_observations_with_unavailable_identity: 0,
    transaction_observations_with_invalid_identity_contract: 0,
    transaction_identity_coverage_state: "incomplete",
    overlapping_transaction_identity_groups: 0,
    conflicting_transaction_identity_groups: 0,
    event_action_observations: 8,
    event_action_observations_with_provider_scoped_identity: 0,
    event_action_observations_with_unavailable_identity: 8,
    event_action_observations_with_invalid_identity_contract: 0,
    event_action_identity_coverage_state: "incomplete",
    overlapping_provider_scoped_event_action_identity_groups: 0,
    conflicting_provider_scoped_event_action_identity_groups: 0,
    swap_observations: 2,
    swap_observations_with_exact_identity: 0,
    swap_observations_with_provider_scoped_identity: 0,
    swap_observations_with_weak_identity: 2,
    overlapping_exact_swap_identity_groups: 0,
    overlapping_provider_scoped_swap_identity_groups: 0,
    overlapping_weak_swap_identity_groups: 1,
    conflicting_swap_identity_groups: 0,
    non_ton_swap_legs: 2,
    addressed_non_ton_swap_legs: 2,
    asset_address_coverage_state: "complete",
    fee_link_candidate_swaps: 2,
    same_run_fee_hash_match_candidates: 0,
    fee_hash_match_coverage_state: "incomplete",
    fee_linkage_contract_verified: false,
  };
}

function response() {
  return {
    analysis_version: "wallet_history_readiness_v0.22.7",
    target_run_id: 3,
    run_ids: [3, 1],
    wallet_address: "UQwallet-history",
    wallet_identity: identity(),
    data_mode: "mock",
    requested_bounds_verified: false,
    observed_activity_start: "2026-06-01T10:00:00Z",
    observed_activity_end: "2026-06-01T11:00:00Z",
    runs: ids.map((runId) => ({
      run_id: runId,
      is_target: runId === 3,
      wallet_address: "UQwallet-history",
      wallet_identity: identity(),
      time_window: "24h",
      status: "success",
      created_at: "2026-07-29T12:00:00Z",
      requested_start: null,
      requested_end: null,
      requested_bounds_verified: false,
      observed_activity_start: "2026-06-01T10:00:00Z",
      observed_activity_end: "2026-06-01T11:00:00Z",
      transfer_count: 3,
      transaction_count: 3,
      swap_count: 1,
      timestamped_activity_count: 7,
      untimestamped_activity_count: 0,
      outside_requested_bounds_count: 0,
      requested_surfaces: ["transfers", "transactions", "swaps"],
      unavailable_surfaces: [],
    })),
    transaction_identity_groups: [],
    swap_identity_groups: [],
    event_action_identity_groups: [],
    transaction_identity_groups_total: 0,
    swap_identity_groups_total: 0,
    event_action_identity_groups_total: 0,
    evidence_groups_truncated: false,
    coverage: coverage(),
    bounded_interval_coverage: {
      contract_version: "wallet_multi_run_interval_coverage_v1",
      selected_run_ids: [3, 1],
      interval_semantics: "[start,end)",
      coverage_scope: "selected_validated_run_intervals_only",
      gap_scope: "inside_validated_selected_span_only",
      cross_stream_union_applied: false,
      low_level_transactions: layer("transactions"),
      provider_display_events: layer("account_events"),
      full_pre_run_history_established: false,
      complete_wallet_history_established: false,
      is_global_history_coverage: false,
      is_authoritative_activity_coverage: false,
      activity_rows_merged: false,
      deduplication_applied: false,
      is_cost_basis: false,
      eligible_for_cost_basis: false,
      used_by_pnl: false,
      note: "Coverage stays bounded.",
    },
    blockers: [{ code: "history_incomplete", reason: "Earlier activity remains unknown.", run_ids: [3, 1], evidence: {} }],
    history_complete: false,
    deduplication_applied: false,
    is_cost_basis: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    note: "Diagnostic evidence only.",
  };
}

describe("validateWalletHistoryReadiness", () => {
  it("accepts a bounded fail-closed history diagnostic", () => {
    const value = response();
    expect(validateWalletHistoryReadiness(value, 3, ids)).toBe(value);
  });

  it("rejects any promotion to full history, deduplication or PnL", () => {
    for (const key of ["history_complete", "deduplication_applied", "used_by_pnl"] as const) {
      const value = response();
      value[key] = true;
      expect(() => validateWalletHistoryReadiness(value, 3, ids)).toThrow("incoherent");
    }
  });

  it("rejects cross-stream unions and broken selected-run partitions", () => {
    const promoted = response();
    promoted.bounded_interval_coverage.cross_stream_union_applied = true;
    expect(() => validateWalletHistoryReadiness(promoted, 3, ids)).toThrow("incoherent");

    const duplicate = response();
    duplicate.bounded_interval_coverage.low_level_transactions.excluded_run_ids = [3];
    duplicate.bounded_interval_coverage.low_level_transactions.not_requested_run_ids = [3];
    expect(() => validateWalletHistoryReadiness(duplicate, 3, ids)).toThrow("incoherent");
  });
});

describe("historyCoveragePercent", () => {
  it("reports included selected runs without implying time coverage", () => {
    expect(historyCoveragePercent({ selected_run_count: 4, included_run_count: 3 } as unknown as WalletHistoryIntervalCoverageLayerRecord)).toBe(75);
  });
});
