// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WalletNativeActivityPnlReadinessResponse } from "../types";

const apiMocks = vi.hoisted(() => ({
  inspectWalletNativePnlReadiness: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import WalletNativePnlReadinessCard from "./WalletNativePnlReadinessCard";

function response(): WalletNativeActivityPnlReadinessResponse {
  return {
    contract_version: "ton_native_activity_pnl_readiness_v1",
    target_run_id: 33,
    selected_run_ids: [32, 33],
    source_dedup_digest_sha256: "11".repeat(32),
    flow_summary: {
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
    requirements: [
      {
        code: "deduplicated_native_activity",
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
        reason: "Native messages do not prove trades.",
      },
      {
        code: "jetton_asset_identity",
        available: false,
        reason: "No jetton legs are present.",
      },
      {
        code: "historical_trade_prices",
        available: false,
        reason: "No verified trade legs exist to price.",
      },
      {
        code: "transaction_fee_linkage",
        available: false,
        reason: "Fees are not allocated to lots.",
      },
      {
        code: "acquisition_cost_basis",
        available: false,
        reason: "Acquisition lots are incomplete.",
      },
    ],
    blocked_requirement_codes: [
      "complete_wallet_history",
      "authoritative_trade_semantics",
      "jetton_asset_identity",
      "historical_trade_prices",
      "transaction_fee_linkage",
      "acquisition_cost_basis",
    ],
    network: "ton-mainnet",
    wallet_account_canonical: `0:${"22".repeat(32)}`,
    source_ledger_count: 2,
    merged_activity_count: 2,
    deduplicated_activity_count: 2,
    suppressed_occurrence_count: 0,
    analysis_digest_sha256: "33".repeat(32),
    analysis_status: "blocked_missing_evidence",
    calculation_mode: "native_flow_reconciliation_only",
    cost_basis_method: "unavailable",
    cost_basis_usd: null,
    realized_pnl_usd: null,
    unrealized_pnl_usd: null,
    activity_merge_applied: true,
    cross_run_deduplication_applied: true,
    native_activity_used_by_pnl_readiness: true,
    native_activity_used_by_pnl_calculation: false,
    establishes_complete_wallet_history: false,
    eligible_for_cost_basis: false,
    is_cost_basis: false,
    is_real_pnl: false,
    real_pnl_locked: true,
    message: "Native flows reconciled; PnL remains unavailable.",
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WalletNativePnlReadinessCard", () => {
  it("reconciles selected runs and keeps PnL visibly locked", async () => {
    apiMocks.inspectWalletNativePnlReadiness.mockResolvedValue(response());
    const user = userEvent.setup();
    render(<WalletNativePnlReadinessCard targetRunId={33} />);

    await user.type(
      screen.getByLabelText("Other run IDs for native flow reconciliation"),
      "32",
    );
    await user.click(screen.getByRole("button", { name: "Check PnL readiness" }));

    await waitFor(() =>
      expect(apiMocks.inspectWalletNativePnlReadiness).toHaveBeenCalledWith(
        33,
        [33, 32],
      ),
    );
    expect(screen.getByText("PNL REMAINS LOCKED")).toBeTruthy();
    expect(screen.getAllByText("-3.34 TON").length).toBeGreaterThan(0);
    expect(screen.getByText("Acquisition cost basis")).toBeTruthy();
  });

  it("rejects a selection that contains only the target", async () => {
    const user = userEvent.setup();
    render(<WalletNativePnlReadinessCard targetRunId={33} />);

    await user.type(
      screen.getByLabelText("Other run IDs for native flow reconciliation"),
      "33",
    );
    await user.click(screen.getByRole("button", { name: "Check PnL readiness" }));

    expect(
      screen.getByText("Add at least one run ID other than the target run."),
    ).toBeTruthy();
    expect(apiMocks.inspectWalletNativePnlReadiness).not.toHaveBeenCalled();
  });
});
