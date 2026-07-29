// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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

import GramAccountStateProofCard from "./GramAccountStateProofCard";

const OWNER = `0:${"1".repeat(64)}`;
const WALLET = `0:${"2".repeat(64)}`;
const MASTER = `0:${"3".repeat(64)}`;

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
    jetton_wallet_account_canonical: WALLET,
    jetton_master_account_canonical: MASTER,
    asset_identity_key: `ton_jetton_asset_v1|ton-mainnet|${MASTER}`,
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
    verified_at: "2026-07-29T12:00:00Z",
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
    message: "Verified account state.",
  };
}

function catalog(rows: WalletJettonContractVerificationResponse[]): WalletJettonContractVerificationCatalogResponse {
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
    message: "Stored evidence revalidated.",
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
      wallet_contract_address: WALLET,
      jetton_address: MASTER,
    },
  };
}

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getWalletJettonContractVerifications
    .mockResolvedValueOnce(catalog([]))
    .mockResolvedValueOnce(catalog([verification()]));
  apiMocks.verifyWalletJettonContractRelationship.mockResolvedValue(verification());
});

describe("GramAccountStateProofCard", () => {
  it("verifies account state only after the user selects the action", async () => {
    const user = userEvent.setup();
    render(<GramAccountStateProofCard runId={25} dataMode="real" network="ton-mainnet" balances={[balance()]} />);

    const button = await screen.findByRole("button", { name: "Verify account state" });
    expect(apiMocks.verifyWalletJettonContractRelationship).not.toHaveBeenCalled();
    await user.click(button);

    await waitFor(() => expect(apiMocks.verifyWalletJettonContractRelationship).toHaveBeenCalledWith(25, WALLET, MASTER));
    expect(await screen.findByText("Account state and jetton relationship verified.")).toBeTruthy();
    expect(screen.getByText("Local TVM")).toBeTruthy();
    expect(screen.getByText("Trust 1")).toBeTruthy();
  });

  it("does not load evidence for a mock run", () => {
    render(<GramAccountStateProofCard runId={25} dataMode="mock" network="ton-unknown" balances={[balance()]} />);
    expect(screen.getByText("Live network-scoped run required")).toBeTruthy();
    expect(apiMocks.getWalletJettonContractVerifications).not.toHaveBeenCalled();
  });
});
