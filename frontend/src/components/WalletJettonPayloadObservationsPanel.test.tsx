// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WalletJettonPayloadObservationsResponse } from "../types";

const apiMocks = vi.hoisted(() => ({
  getWalletTransactionJettonPayloadObservations: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import WalletJettonPayloadObservationsPanel from "./WalletJettonPayloadObservationsPanel";

const HASH = "a".repeat(64);
const ACCOUNT = `0:${"b".repeat(64)}`;

function response(): WalletJettonPayloadObservationsResponse {
  return {
    contract_version: "ton_jetton_payload_observations_v1",
    identity_version: "ton_jetton_payload_obs_v1",
    verification_id: "7",
    capture_id: "6",
    run_id: "25",
    provider: "tonapi",
    source_status: "live",
    network: "ton-mainnet",
    anchor: {
      transaction_hash: HASH,
      logical_time: "1000",
      account_canonical: ACCOUNT,
      matches_stored_transaction: true,
    },
    verification_evidence_digest_sha256: "1".repeat(64),
    message_evidence_digest_sha256: "2".repeat(64),
    payload_observations_digest_sha256: "3".repeat(64),
    source_message_count: 2,
    recognized_message_count: 1,
    unrecognized_message_count: 1,
    operations: [{ operation: "transfer", count: 1 }],
    observations: [
      {
        ordinal: 0,
        payload_observation_identity: "4".repeat(64),
        transaction_preorder_index: 0,
        transaction_hash: HASH,
        message_role: "remaining_outbound",
        message_ordinal: 0,
        message_hash: "5".repeat(64),
        message_source_account_canonical: ACCOUNT,
        message_destination_account_canonical: `0:${"c".repeat(64)}`,
        message_native_value_nanoton: "100000000",
        body_hash: "6".repeat(64),
        opcode_hex: "0x0f8a7ea5",
        operation: "transfer",
        standard_status: "active",
        query_id: "9",
        amount_base_units: "123456789",
        destination_account_canonical: `0:${"d".repeat(64)}`,
        response_destination_account_canonical: ACCOUNT,
        sender_account_canonical: null,
        from_account_canonical: null,
        forward_ton_amount_nanoton: "25000000",
        custom_payload_present: false,
        custom_payload_hash: null,
        forward_payload_in_ref: true,
        forward_payload_hash: "7".repeat(64),
        forward_payload_bit_length: 32,
        forward_payload_ref_count: 0,
        contract_account_role: "destination_jetton_wallet_observed",
      },
    ],
    tep74_decoder_applied: true,
    recognized_payload_semantics_applied: true,
    query_id_is_correlation_only: true,
    message_bodies_returned: false,
    jetton_wallet_contract_role_is_observation_only: true,
    jetton_master_identity_applied: false,
    jetton_asset_identity_applied: false,
    is_authoritative_jetton_transfer_ledger: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: "Recognized payload layouts were decoded locally.",
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WalletJettonPayloadObservationsPanel", () => {
  it("decodes only after an explicit action and renders bounded semantics", async () => {
    apiMocks.getWalletTransactionJettonPayloadObservations.mockResolvedValue(
      response(),
    );
    const user = userEvent.setup();
    render(
      <WalletJettonPayloadObservationsPanel
        runId={25}
        transactionHash={HASH}
        verificationId="7"
      />,
    );

    expect(apiMocks.getWalletTransactionJettonPayloadObservations).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Decode TEP-74 payloads" }),
    );

    await waitFor(() =>
      expect(
        apiMocks.getWalletTransactionJettonPayloadObservations,
      ).toHaveBeenCalledWith(25, HASH, expect.any(AbortSignal)),
    );
    expect(screen.getByText("transfer")).toBeTruthy();
    expect(screen.getByText("123456789")).toBeTruthy();
    expect(screen.getByText("ASSET UNRESOLVED")).toBeTruthy();
    expect(screen.queryByText("invoice-7")).toBeNull();
  });

  it("rejects an incoherent response before rendering observations", async () => {
    const invalid = response();
    invalid.jetton_asset_identity_applied = true as false;
    apiMocks.getWalletTransactionJettonPayloadObservations.mockResolvedValue(
      invalid,
    );
    const user = userEvent.setup();
    render(
      <WalletJettonPayloadObservationsPanel
        runId={25}
        transactionHash={HASH}
        verificationId="7"
      />,
    );

    await user.click(
      screen.getByRole("button", { name: "Decode TEP-74 payloads" }),
    );

    expect(
      await screen.findByText("Jetton payload response contract is incoherent."),
    ).toBeTruthy();
    expect(screen.queryByText("123456789")).toBeNull();
  });
});
