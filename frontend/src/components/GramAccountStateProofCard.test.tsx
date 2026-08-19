// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletBalanceSnapshotRecord,
  WalletJettonContractVerificationCatalogResponse,
  WalletJettonContractVerificationResponse,
} from "../types";
import {
  validateWalletJettonContractVerification,
  validateWalletJettonContractVerificationCatalog,
} from "../walletJettonContractVerification";

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
  const verifiedAt = "2026-07-29T12:00:00Z";
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
    account_state_inclusion_proofs: [
      {
        contract_version: "ton_account_state_inclusion_v1",
        account_role: "jetton_master",
        account_address_canonical: MASTER,
        shard_block: {
          workchain: 0,
          shard: "-9223372036854775808",
          seqno: 120,
          root_hash: "1".repeat(64),
          file_hash: "2".repeat(64),
        },
        boc_sha256: {
          state_boc_hex: "3".repeat(64),
          account_proof_boc_hex: "4".repeat(64),
          shard_proof_boc_hex: "5".repeat(64),
        },
        evidence_digest_sha256: "6".repeat(64),
        verified_at: verifiedAt,
        provider_requests_performed: false,
        provider_free_revalidated: true,
        raw_bocs_returned: false,
      },
      {
        contract_version: "ton_account_state_inclusion_v1",
        account_role: "jetton_wallet",
        account_address_canonical: WALLET,
        shard_block: {
          workchain: 0,
          shard: "-9223372036854775808",
          seqno: 121,
          root_hash: "7".repeat(64),
          file_hash: "8".repeat(64),
        },
        boc_sha256: {
          state_boc_hex: "9".repeat(64),
          account_proof_boc_hex: "a".repeat(64),
          shard_proof_boc_hex: "b".repeat(64),
        },
        evidence_digest_sha256: "c".repeat(64),
        verified_at: verifiedAt,
        provider_requests_performed: false,
        provider_free_revalidated: true,
        raw_bocs_returned: false,
      },
    ],
    evidence_digest_sha256: "f".repeat(64),
    verified_at: verifiedAt,
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
    limitations: ["checkpoint_policy_not_persisted_v1"],
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
    expect(screen.getByText("Legacy · non-canonical")).toBeTruthy();
    expect(screen.getByText("2 account proofs")).toBeTruthy();
    expect(screen.getByText(/did not persist the checkpoint policy/)).toBeTruthy();
  });

  it("never presents a legacy trust-zero record as canonical", async () => {
    const trustZero = verification();
    trustZero.trust_level = 0;
    apiMocks.getWalletJettonContractVerifications
      .mockReset()
      .mockResolvedValue(catalog([trustZero]));
    render(<GramAccountStateProofCard runId={25} dataMode="real" network="ton-mainnet" balances={[balance()]} />);

    expect(await screen.findByText("Legacy · non-canonical")).toBeTruthy();
    expect(screen.getByTitle("Recorded liteserver trust level 0")).toBeTruthy();
    expect(screen.getByText(/canonical chain inclusion is not claimed/)).toBeTruthy();
    expect(screen.queryByText(/checkpoint chain verified/i)).toBeNull();
  });

  it("shows the explicit proof gap for an older record without persisted Merkle rows", async () => {
    const legacy = verification();
    legacy.account_state_inclusion_proofs = [];
    legacy.raw_account_state_bocs_persisted = false;
    apiMocks.getWalletJettonContractVerifications
      .mockReset()
      .mockResolvedValue(catalog([legacy]));
    render(<GramAccountStateProofCard runId={25} dataMode="real" network="ton-mainnet" balances={[balance()]} />);

    expect(await screen.findByText("Legacy proof gap")).toBeTruthy();
    expect(screen.getByText(/predates persisted account Merkle proofs/)).toBeTruthy();
  });

  it("fails closed for partial, reordered, cross-address or time-detached account proofs", () => {
    const mutations: Array<(value: any) => void> = [
      (value) => { value.account_state_inclusion_proofs.pop(); },
      (value) => { value.account_state_inclusion_proofs.reverse(); },
      (value) => { value.account_state_inclusion_proofs[0].account_address_canonical = WALLET; },
      (value) => { value.account_state_inclusion_proofs[0].verified_at = "2026-07-29T12:00:01Z"; },
      (value) => { value.account_state_inclusion_proofs[0].boc_sha256.state_boc_hex = "bad"; },
      (value) => { value.account_state_inclusion_proofs[0].state_boc_hex = "00"; },
    ];
    mutations.forEach((mutate) => {
      const value: any = structuredClone(verification());
      mutate(value);
      expect(() => validateWalletJettonContractVerification(value, 25, "ton-mainnet")).toThrow(
        /Jetton contract proof response is incoherent/,
      );
    });
  });

  it("requires the legacy checkpoint limitation and false canonical flags at trust zero", () => {
    const missingLimitation: any = structuredClone(verification());
    missingLimitation.limitations = [];
    expect(() => validateWalletJettonContractVerification(missingLimitation, 25, "ton-mainnet")).toThrow();

    const overstated: any = structuredClone(verification());
    overstated.trust_level = 0;
    overstated.masterchain_checkpoint_chain_verified = true;
    overstated.is_blockchain_inclusion_proof_verified = true;
    expect(() => validateWalletJettonContractVerification(overstated, 25, "ton-mainnet")).toThrow();
  });

  it("enforces the exact signed 32-bit seqno ceiling for every block record", () => {
    const topAnchor: any = structuredClone(verification());
    topAnchor.anchor.seqno = 2_147_483_648;
    expect(() => validateWalletJettonContractVerification(topAnchor, 25, "ton-mainnet")).toThrow();

    const nestedShardBlock: any = structuredClone(verification());
    nestedShardBlock.account_state_inclusion_proofs[0].shard_block.seqno = 2_147_483_648;
    expect(() => validateWalletJettonContractVerification(nestedShardBlock, 25, "ton-mainnet")).toThrow();
  });

  it("rejects unexpected public or nested fields in the v1 response", () => {
    const response: any = structuredClone(verification());
    response.verifier_policy_id = "not_persisted";
    expect(() => validateWalletJettonContractVerification(response, 25, "ton-mainnet")).toThrow();

    const nested: any = structuredClone(verification());
    nested.account_state_inclusion_proofs[0].boc_sha256.state_boc_hex_raw = "00";
    expect(() => validateWalletJettonContractVerification(nested, 25, "ton-mainnet")).toThrow();

    const responseCatalog: any = catalog([verification()]);
    responseCatalog.internal_rows = [7];
    expect(() => validateWalletJettonContractVerificationCatalog(responseCatalog, 25, "ton-mainnet")).toThrow();
  });

  it("does not load evidence for a mock run", () => {
    render(<GramAccountStateProofCard runId={25} dataMode="mock" network="ton-unknown" balances={[balance()]} />);
    expect(screen.getByText("Live network-scoped run required")).toBeTruthy();
    expect(apiMocks.getWalletJettonContractVerifications).not.toHaveBeenCalled();
  });
});
