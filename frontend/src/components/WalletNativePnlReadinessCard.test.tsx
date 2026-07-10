// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WalletMultiAssetPnlReadinessResponse } from "../types";

const apiMocks = vi.hoisted(() => ({
  inspectWalletMultiAssetPnlReadiness: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import WalletNativePnlReadinessCard from "./WalletNativePnlReadinessCard";

function response(): WalletMultiAssetPnlReadinessResponse {
  return {
    contract_version: "ton_multi_asset_pnl_readiness_v4",
    target_run_id: 33,
    selected_run_ids: [32, 33],
    network: "ton-mainnet",
    wallet_account_canonical: `0:${"22".repeat(32)}`,
    source_native_analysis_digest_sha256: "11".repeat(32),
    native_flow_summary: {
      asset_identity_key: "ton_native_asset_v1|ton-mainnet",
      activity_count: 2,
      incoming_activity_count: 0,
      outgoing_activity_count: 2,
      self_activity_count: 0,
      incoming_nanoton: "0",
      outgoing_nanoton: "3340000000",
      self_nanoton: "0",
      net_nanoton: "-3340000000",
      incoming_ton: "0",
      outgoing_ton: "3.34",
      self_ton: "0",
      net_ton: "-3.34",
    },
    jetton_evidence_summary: {
      selected_capture_count: 2,
      verified_capture_count: 2,
      source_message_count: 3,
      recognized_payload_occurrence_count: 2,
      unrecognized_message_count: 1,
      deduplicated_payload_observation_count: 1,
      suppressed_payload_occurrence_count: 1,
      provider_jetton_snapshot_count: 4,
      valid_provider_asset_snapshot_count: 4,
      invalid_provider_asset_snapshot_count: 0,
      verified_jetton_contract_count: 2,
      asset_matched_observation_count: 1,
      asset_unmatched_observation_count: 0,
      fee_linked_observation_count: 1,
      fee_unlinked_observation_count: 0,
      linked_fee_transaction_count: 1,
      linked_fee_nanoton: "468567",
      linked_fee_ton: "0.000468567",
    },
    operations: [{ operation: "transfer", count: 1 }],
    evidence: [
      {
        ordinal: 0,
        payload_observation_identity: "22".repeat(32),
        occurrence_count: 2,
        source_run_ids: [32, 33],
        occurrences: [
          { run_id: 32, capture_id: 1, verification_id: 1 },
          { run_id: 33, capture_id: 2, verification_id: 2 },
        ],
        operation: "transfer",
        standard_status: "active",
        transaction_hash: "33".repeat(32),
        message_hash: "44".repeat(32),
        query_id: "7",
        amount_base_units: "123",
        contract_account_role: "destination_jetton_wallet_observed",
        observed_contract_account_canonical: `0:${"55".repeat(32)}`,
        asset_binding_status: "verified_contract_match",
        jetton_master_account_canonical: `0:${"66".repeat(32)}`,
        asset_identity_key: `ton_jetton_asset_v1|ton-mainnet|0:${"66".repeat(32)}`,
        contract_verification_ids: [7, 8],
        contract_verification_digests: ["77".repeat(32), "88".repeat(32)],
        contract_verification_run_ids: [32, 33],
        provider_asset_observation_key: "provider-asset",
        asset_decimals: 9,
        asset_symbol: "JET",
        asset_snapshot_run_ids: [32],
        transaction_fee_evidence_status: "exact_transaction_match",
        transaction_fee_nanoton: "468567",
        transaction_fee_ton: "0.000468567",
        fee_source_run_ids: [32],
        provider_snapshot_is_local_master_proof: false,
        fee_allocation_applied: false,
        eligible_for_cost_basis: false,
        used_by_pnl_calculation: false,
      },
    ],
    requirements: [
      {
        code: "deduplicated_native_activity",
        available: true,
        reason: null,
      },
      {
        code: "verified_jetton_payload_semantics",
        available: true,
        reason: null,
      },
      {
        code: "proof_checked_jetton_asset_identity",
        available: true,
        reason: null,
      },
      {
        code: "exact_transaction_fee_evidence",
        available: true,
        reason: null,
      },
      {
        code: "complete_wallet_history",
        available: false,
        reason: "Time outside selected captures remains unknown.",
      },
      {
        code: "authoritative_trade_semantics",
        available: false,
        reason: "Payloads do not prove trades.",
      },
      {
        code: "historical_trade_prices",
        available: false,
        reason: "No authoritative trade legs exist to price.",
      },
      {
        code: "transaction_fee_allocation",
        available: false,
        reason: "Fees remain unallocated.",
      },
      {
        code: "acquisition_lots_and_cost_basis",
        available: false,
        reason: "Acquisition lots are incomplete.",
      },
    ],
    blocked_requirement_codes: [
      "complete_wallet_history",
      "authoritative_trade_semantics",
      "historical_trade_prices",
      "transaction_fee_allocation",
      "acquisition_lots_and_cost_basis",
    ],
    lot_readiness_summary: {
      evidence_row_count: 1,
      proof_bound_asset_row_count: 1,
      exact_fee_row_count: 1,
      authoritative_trade_row_count: 0,
      historical_price_eligible_row_count: 0,
      fee_allocated_row_count: 0,
      lot_eligible_row_count: 0,
      blocked_row_count: 1,
    },
    real_pnl_gate: {
      contract_version: "ton_real_pnl_safety_gate_v1",
      target_run_id: 33,
      selected_run_ids: [32, 33],
      source_native_analysis_digest_sha256: "11".repeat(32),
      required_requirement_codes: [
        "deduplicated_native_activity",
        "verified_jetton_payload_semantics",
        "proof_checked_jetton_asset_identity",
        "exact_transaction_fee_evidence",
        "complete_wallet_history",
        "authoritative_trade_semantics",
        "historical_trade_prices",
        "transaction_fee_allocation",
        "acquisition_lots_and_cost_basis",
      ],
      satisfied_requirement_codes: [
        "deduplicated_native_activity",
        "verified_jetton_payload_semantics",
        "proof_checked_jetton_asset_identity",
        "exact_transaction_fee_evidence",
      ],
      blocking_requirement_codes: [
        "complete_wallet_history",
        "authoritative_trade_semantics",
        "historical_trade_prices",
        "transaction_fee_allocation",
        "acquisition_lots_and_cost_basis",
      ],
      all_requirements_satisfied: false,
      calculation_authorized: false,
      refuses_partial_calculation: true,
      gate_digest_sha256: "99".repeat(32),
    },
    analysis_digest_sha256: "33".repeat(32),
    analysis_status: "blocked_missing_evidence",
    calculation_mode: "evidence_reconciliation_only",
    cost_basis_method: "unavailable",
    cost_basis_usd: null,
    realized_pnl_usd: null,
    unrealized_pnl_usd: null,
    native_activity_deduplication_applied: true,
    jetton_observation_deduplication_applied: true,
    jetton_payload_semantics_used_by_pnl_readiness: true,
    verified_contract_identity_used_by_pnl_readiness: true,
    provider_asset_metadata_used_by_pnl_readiness: true,
    transaction_fee_evidence_used_by_pnl_readiness: true,
    provider_snapshot_asset_identity_is_authoritative: false,
    verified_contract_asset_identity_is_authoritative: true,
    transaction_fee_allocation_applied: false,
    historical_price_requests_performed: false,
    acquisition_lot_construction_applied: false,
    disposal_lot_construction_applied: false,
    provider_requests_performed: false,
    message_bodies_returned: false,
    used_by_pnl_calculation: false,
    establishes_complete_wallet_history: false,
    eligible_for_cost_basis: false,
    is_cost_basis: false,
    is_real_pnl: false,
    real_pnl_locked: true,
    message: "Multi-asset evidence reconciled; PnL remains unavailable.",
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WalletNativePnlReadinessCard", () => {
  it("reconciles selected runs and keeps PnL visibly locked", async () => {
    apiMocks.inspectWalletMultiAssetPnlReadiness.mockResolvedValue(response());
    const user = userEvent.setup();
    render(<WalletNativePnlReadinessCard targetRunId={33} />);

    await user.type(
      screen.getByLabelText("Other run IDs for evidence reconciliation"),
      "32",
    );
    await user.click(
      screen.getByRole("button", { name: "Check multi-asset readiness" }),
    );

    await waitFor(() =>
      expect(apiMocks.inspectWalletMultiAssetPnlReadiness).toHaveBeenCalledWith(
        33,
        [33, 32],
      ),
    );
    expect(screen.getByText("REAL PNL REFUSED")).toBeTruthy();
    expect(screen.getAllByText("-3.34 TON").length).toBeGreaterThan(0);
    expect(screen.getByText("Acquisition lots and cost basis")).toBeTruthy();
    expect(screen.getByText("JET · contract proof")).toBeTruthy();
    expect(screen.getByText("0.000468567 TON · unallocated")).toBeTruthy();
    expect(screen.getByText("Trade-qualified rows")).toBeTruthy();
    expect(screen.getByText("Lot-eligible rows")).toBeTruthy();
    expect(screen.getByText("1 rows blocked fail-closed")).toBeTruthy();
    expect(screen.getByText("REAL PNL REFUSED")).toBeTruthy();
    expect(screen.getByText(/partial calculation refused/)).toBeTruthy();
  });

  it("rejects a selection that contains only the target", async () => {
    const user = userEvent.setup();
    render(<WalletNativePnlReadinessCard targetRunId={33} />);

    await user.type(
      screen.getByLabelText("Other run IDs for evidence reconciliation"),
      "33",
    );
    await user.click(
      screen.getByRole("button", { name: "Check multi-asset readiness" }),
    );

    expect(
      screen.getByText("Add at least one run ID other than the target run."),
    ).toBeTruthy();
    expect(apiMocks.inspectWalletMultiAssetPnlReadiness).not.toHaveBeenCalled();
  });
});
