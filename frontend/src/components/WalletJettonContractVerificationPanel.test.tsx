// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type {
  WalletBalanceSnapshotRecord,
  WalletJettonContractVerificationCatalogResponse,
  WalletJettonContractVerificationResponse,
} from "../types";

const apiMocks = vi.hoisted(() => ({
  getWalletJettonContractVerifications: vi.fn(),
  verifyWalletJettonContractRelationship: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import WalletJettonContractVerificationPanel from "./WalletJettonContractVerificationPanel";

const OWNER = `0:${"1".repeat(64)}`;
const JETTON_WALLET = `0:${"2".repeat(64)}`;
const JETTON_MASTER = `0:${"3".repeat(64)}`;

function verification(): WalletJettonContractVerificationResponse {
  return {
    contract_version: "ton_jetton_contract_verification_v1",
    verification_id: "7",
    run_id: "25",
    balance_snapshot_id: "9",
    verifier_name: "pytoniq-pytvm",
    verifier_version: "pytoniq-test/pytvm-test",
    network: "ton-mainnet",
    trust_level: 1,
    anchor: {
      workchain: -1,
      shard: "-9223372036854775808",
      seqno: 123,
      root_hash: "4".repeat(64),
      file_hash: "5".repeat(64),
    },
    owner_account_canonical: OWNER,
    jetton_wallet_account_canonical: JETTON_WALLET,
    jetton_master_account_canonical: JETTON_MASTER,
    asset_identity_key: `ton_jetton_asset_v1|ton-mainnet|${JETTON_MASTER}`,
    wallet_balance_base_units: "123456",
    total_supply_base_units: "987654321",
    mintable: true,
    wallet_code_hash: "6".repeat(64),
    wallet_data_hash: "7".repeat(64),
    master_code_hash: "8".repeat(64),
    master_data_hash: "9".repeat(64),
    jetton_content_hash: "a".repeat(64),
    account_state_boc_hashes: {
      wallet_code_boc_hex: "b".repeat(64),
      wallet_data_boc_hex: "c".repeat(64),
      master_code_boc_hex: "d".repeat(64),
      master_data_boc_hex: "e".repeat(64),
    },
    evidence_digest_sha256: "f".repeat(64),
    verified_at: "2026-07-10T12:00:00Z",
    account_state_proof_verified: true,
    masterchain_checkpoint_chain_verified: false,
    local_tvm_execution_applied: true,
    wallet_owner_master_verified: true,
    master_wallet_address_verified: true,
    wallet_code_consistency_verified: true,
    jetton_asset_identity_applied: true,
    raw_account_state_bocs_persisted: true,
    raw_account_state_bocs_returned: false,
    is_blockchain_inclusion_proof_verified: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: "The exact jetton contract relationship is verified.",
  };
}

function catalog(
  rows: WalletJettonContractVerificationResponse[],
): WalletJettonContractVerificationCatalogResponse {
  return {
    contract_version: "ton_jetton_contract_verification_v1",
    run_id: "25",
    network: "ton-mainnet",
    verification_count: rows.length,
    verification_digests: rows.map((row) => row.evidence_digest_sha256),
    verifications: rows,
    catalog_digest_sha256: "a".repeat(64),
    provider_requests_performed: false,
    raw_account_state_bocs_returned: false,
    message: "Stored evidence was revalidated provider-free.",
  };
}

function balance(): WalletBalanceSnapshotRecord {
  return {
    asset: "TEST",
    balance: "123456",
    provider: "tonapi",
    source_status: "live",
    raw: {
      surface: "jettons",
      wallet_contract_address: JETTON_WALLET,
      jetton_address: JETTON_MASTER,
    },
  };
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("WalletJettonContractVerificationPanel", () => {
  it("reads stored evidence provider-free and verifies only after a click", async () => {
    const row = verification();
    apiMocks.getWalletJettonContractVerifications
      .mockResolvedValueOnce(catalog([]))
      .mockResolvedValueOnce(catalog([row]));
    apiMocks.verifyWalletJettonContractRelationship.mockResolvedValue(row);
    const user = userEvent.setup();

    render(
      <WalletJettonContractVerificationPanel
        runId={25}
        dataMode="real"
        network="ton-mainnet"
        balances={[balance()]}
      />,
    );

    const button = await screen.findByRole("button", {
      name: "Verify selected contract",
    });
    expect(apiMocks.verifyWalletJettonContractRelationship).not.toHaveBeenCalled();

    await user.click(button);
    await waitFor(() =>
      expect(
        apiMocks.verifyWalletJettonContractRelationship,
      ).toHaveBeenCalledWith(25, JETTON_WALLET, JETTON_MASTER),
    );
    expect((await screen.findAllByText("Matched")).length).toBe(2);
    expect(screen.getByText(/Cost basis and PnL remain disabled\./)).toBeTruthy();
    expect(apiMocks.getWalletJettonContractVerifications).toHaveBeenCalledTimes(2);
  });

  it("fails closed on an overstated proof response", async () => {
    const invalid = verification();
    invalid.is_blockchain_inclusion_proof_verified = true;
    apiMocks.getWalletJettonContractVerifications.mockResolvedValue(
      catalog([invalid]),
    );

    render(
      <WalletJettonContractVerificationPanel
        runId={25}
        dataMode="real"
        network="ton-mainnet"
        balances={[balance()]}
      />,
    );

    expect(
      await screen.findByText("Jetton contract proof response is incoherent."),
    ).toBeTruthy();
    expect(screen.queryByText("Matched")).toBeNull();
  });

  it("does not contact proof services for mock runs", () => {
    render(
      <WalletJettonContractVerificationPanel
        runId={25}
        dataMode="mock"
        network="ton-unknown"
        balances={[balance()]}
      />,
    );
    expect(screen.getByText("Real network-scoped run required.")).toBeTruthy();
    expect(apiMocks.getWalletJettonContractVerifications).not.toHaveBeenCalled();
  });
});
