// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletPersistedTransactionTraceEvidenceResponse,
  WalletTraceBocVerificationResponse,
  WalletTransactionInclusionCatalogResponse,
  WalletTransactionRecord,
} from "../types";

const apiMocks = vi.hoisted(() => ({
  getPersistedWalletTransactionTraceEvidence: vi.fn(),
  getWalletTransactionInclusionProofs: vi.fn(),
  getWalletTransactionTraceBocVerification: vi.fn(),
  persistWalletTransactionTraceEvidence: vi.fn(),
  proveWalletTransactionInclusion: vi.fn(),
  verifyWalletTransactionTraceBocs: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import GramTransactionProofCard from "./GramTransactionProofCard";

const HASH = "1".repeat(64);
const ACCOUNT = `0:${"a".repeat(64)}`;

function transaction(): WalletTransactionRecord {
  return {
    tx_hash: HASH,
    logical_time: "46000000000001",
    timestamp: "2026-07-29T12:00:00Z",
    success: "success",
    provider: "tonapi",
    source_status: "live",
    transaction_identity: {
      status: "network_scoped",
      version: "ton_account_tx_v1",
      network: "ton-mainnet",
      account_canonical: ACCOUNT,
      logical_time_canonical: "46000000000001",
      hash_canonical: HASH,
      key: `ton_account_tx_v1|ton-mainnet|${ACCOUNT}|46000000000001|${HASH}`,
      is_deduplication_identity: true,
      is_blockchain_proof_verified: false,
      is_ownership_proof: false,
      deduplication_applied: false,
      used_by_pnl: false,
    },
  };
}

function capture(): WalletPersistedTransactionTraceEvidenceResponse {
  return {
    contract_version: "tonapi_low_level_trace_evidence_v1",
    capture_id: "3",
    run_id: "25",
    provider: "tonapi",
    source_status: "live",
    network: "ton-mainnet",
    trace_state: "finalized",
    captured_at: "2026-07-29T12:00:00.123456Z",
    anchor: {
      transaction_hash: HASH,
      logical_time: "46000000000001",
      account_canonical: ACCOUNT,
      matches_stored_transaction: true,
    },
    summary: {
      root_transaction_hash: HASH,
      transaction_count: 1,
      max_depth: 0,
      message_count: 1,
      root_inbound_message_count: 1,
      child_internal_message_count: 0,
      remaining_out_message_count: 0,
      internal_message_count: 0,
      external_in_message_count: 1,
      external_out_message_count: 0,
      successful_transaction_count: 1,
      failed_transaction_count: 0,
      aborted_transaction_count: 0,
      unique_account_count: 1,
    },
    evidence_digest_sha256: "b".repeat(64),
    is_provider_indexed_low_level_trace: true,
    provider_structure_validated: true,
    persisted_graph_revalidated: true,
    is_immutable_record: true,
    raw_boc_persisted: false,
    message_body_persisted: false,
    is_blockchain_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: "Immutable trace evidence.",
  };
}

function boc(): WalletTraceBocVerificationResponse {
  return {
    contract_version: "ton_boc_trace_verification_v1",
    verification_id: "4",
    capture_id: "3",
    run_id: "25",
    provider: "tonapi",
    source_status: "live",
    network: "ton-mainnet",
    verified_at: "2026-07-29T12:01:00.123456Z",
    verifier: { name: "pytoniq-core", version: "0.1.46" },
    anchor: capture().anchor,
    capture_evidence_digest_sha256: "b".repeat(64),
    evidence_digest_sha256: "c".repeat(64),
    summary: {
      transaction_count: 1,
      message_count: 1,
      total_boc_bytes: 100,
      normalized_external_in_hash_count: 1,
      direct_cell_hash_message_count: 0,
      body_hash_count: 1,
      opcode_count: 0,
    },
    transactions: [{
      preorder_index: 0,
      transaction_hash: HASH,
      transaction_boc_bytes: 100,
      transaction_cell_hash: HASH,
      raw_out_message_count: 0,
      message_count: 1,
      body_hash_count: 1,
      opcode_count: 0,
      message_evidence_digest_sha256: "d".repeat(64),
    }],
    transaction_bocs_deserialized_locally: true,
    transaction_cell_hashes_verified: true,
    transaction_headers_verified: true,
    message_hashes_verified: true,
    message_headers_verified: true,
    message_body_hashes_derived: true,
    raw_boc_persisted: true,
    raw_boc_returned: false,
    message_bodies_returned: false,
    is_blockchain_inclusion_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: "Locally verified BOC evidence.",
  };
}

function inclusion(): WalletTransactionInclusionCatalogResponse {
  const checkpoint = {
    workchain: -1 as const,
    shard: "-9223372036854775808",
    seqno: 46_894_135,
    root_hash: "3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f",
    file_hash: "bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed",
  };
  return {
    contract_version: "ton_transaction_inclusion_v2",
    verifier_policy_id: "ton_liteserver_checkpoint_strict_2026_08_v2",
    trusted_checkpoint: checkpoint,
    boc_verification_id: "4",
    proof_count: 1,
    proof_digests: ["e".repeat(64)],
    proofs: [{
      contract_version: "ton_transaction_inclusion_v2",
      evidence_contract_version: "ton_transaction_inclusion_v2",
      network: "ton-mainnet",
      trust_level: 1,
      verifier_policy_id: "ton_liteserver_checkpoint_strict_2026_08_v2",
      trusted_checkpoint: checkpoint,
      account_address_canonical: ACCOUNT,
      logical_time: "46000000000001",
      transaction_hash: HASH,
      block: {
        workchain: 0,
        shard: "-9223372036854775808",
        seqno: 100,
        root_hash: "2".repeat(64),
        file_hash: "3".repeat(64),
      },
      masterchain_anchor: {
        workchain: -1,
        shard: "-9223372036854775808",
        seqno: 200,
        root_hash: "4".repeat(64),
        file_hash: "5".repeat(64),
      },
      transaction_boc_sha256: "6".repeat(64),
      block_proof_boc_sha256: "7".repeat(64),
      evidence_digest_sha256: "e".repeat(64),
      verified_at: "2026-07-29T12:02:00.123456Z",
      block_merkle_proof_verified: true,
      canonical_block_chain_verified_at_capture: false,
      checkpoint_to_observed_head_transcript_persisted: false,
      provider_free_revalidated: true,
      raw_bocs_returned: false,
    }],
    catalog_digest_sha256: "f".repeat(64),
    provider_requests_performed: false,
    all_transaction_bocs_included_in_blocks: true,
    raw_bocs_returned: false,
    message: "Every transaction BOC is included.",
  };
}

afterEach(cleanup);

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValue(null);
  apiMocks.getWalletTransactionTraceBocVerification.mockResolvedValue(null);
  apiMocks.getWalletTransactionInclusionProofs.mockResolvedValue(null);
  apiMocks.persistWalletTransactionTraceEvidence.mockResolvedValue(capture());
  apiMocks.verifyWalletTransactionTraceBocs.mockResolvedValue(boc());
  apiMocks.proveWalletTransactionInclusion.mockResolvedValue(inclusion());
});

describe("GramTransactionProofCard", () => {
  it("runs capture, local BOC verification and block inclusion in order", async () => {
    const user = userEvent.setup();
    render(<GramTransactionProofCard runId={25} dataMode="real" transactions={[transaction()]} />);

    await user.click(await screen.findByRole("button", { name: "Capture immutable trace" }));
    expect(apiMocks.persistWalletTransactionTraceEvidence).toHaveBeenCalledWith(25, HASH, expect.any(AbortSignal));

    await user.click(await screen.findByRole("button", { name: "Verify BOC locally" }));
    expect(apiMocks.verifyWalletTransactionTraceBocs).toHaveBeenCalledWith(25, HASH, expect.any(AbortSignal));

    await user.click(await screen.findByRole("button", { name: "Prove block inclusion" }));
    expect(apiMocks.proveWalletTransactionInclusion).toHaveBeenCalledWith(25, HASH, expect.any(AbortSignal));
    expect(await screen.findByText("Every captured transaction BOC is included in a block.")).toBeTruthy();
    expect(screen.getByText("Inclusion · trust 1")).toBeTruthy();
    expect(screen.getByText("Checkpoint #46894135")).toBeTruthy();
    expect(screen.getByText(/canonical checkpoint chain is not claimed at trust level 1/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Prove block inclusion" })).toBeNull();
  });

  it("labels legacy unpinned evidence as non-canonical even at trust level zero", async () => {
    const legacy = inclusion();
    legacy.verifier_policy_id = "legacy_unpinned_v1";
    legacy.trusted_checkpoint = null;
    legacy.proofs[0].evidence_contract_version = "ton_transaction_inclusion_v1";
    legacy.proofs[0].trust_level = 0;
    legacy.proofs[0].verifier_policy_id = "legacy_unpinned_v1";
    legacy.proofs[0].trusted_checkpoint = null;
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValue(capture());
    apiMocks.getWalletTransactionTraceBocVerification.mockResolvedValue(boc());
    apiMocks.getWalletTransactionInclusionProofs.mockResolvedValue(legacy);

    render(<GramTransactionProofCard runId={25} dataMode="real" transactions={[transaction()]} />);

    expect(await screen.findByText("Legacy · non-canonical")).toBeTruthy();
    expect(screen.getByText("Not pinned")).toBeTruthy();
    expect(screen.getByText(/Legacy unpinned evidence/)).toBeTruthy();
    expect(screen.queryByText(/canonical chain verified at capture/)).toBeNull();
  });

  it("labels the pre-strict checkpoint policy as legacy and non-canonical", async () => {
    const legacy = inclusion();
    legacy.verifier_policy_id = "ton_liteserver_checkpoint_2026_08_v1";
    legacy.proofs[0].trust_level = 0;
    legacy.proofs[0].verifier_policy_id =
      "ton_liteserver_checkpoint_2026_08_v1";
    legacy.proofs[0].canonical_block_chain_verified_at_capture = false;
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValue(capture());
    apiMocks.getWalletTransactionTraceBocVerification.mockResolvedValue(boc());
    apiMocks.getWalletTransactionInclusionProofs.mockResolvedValue(legacy);

    render(<GramTransactionProofCard runId={25} dataMode="real" transactions={[transaction()]} />);

    expect(await screen.findByText("Legacy checkpoint · non-canonical")).toBeTruthy();
    expect(screen.getByText(/predates strict proof-link verification/i)).toBeTruthy();
    expect(screen.queryByText(/canonical chain verified at capture/i)).toBeNull();
  });

  it("discloses the non-persisted checkpoint transcript for canonical trust-zero proof", async () => {
    const canonical = inclusion();
    canonical.proofs[0].trust_level = 0;
    canonical.proofs[0].canonical_block_chain_verified_at_capture = true;
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValue(capture());
    apiMocks.getWalletTransactionTraceBocVerification.mockResolvedValue(boc());
    apiMocks.getWalletTransactionInclusionProofs.mockResolvedValue(canonical);

    render(<GramTransactionProofCard runId={25} dataMode="real" transactions={[transaction()]} />);

    expect(await screen.findByText("Canonical · trust 0")).toBeTruthy();
    expect(screen.getByText(/checkpoint-to-head transcript was not persisted/i)).toBeTruthy();
  });

  it("never contacts proof endpoints for mock data", () => {
    render(<GramTransactionProofCard runId={25} dataMode="mock" transactions={[transaction()]} />);
    expect(screen.getByText("Live run required")).toBeTruthy();
    expect(apiMocks.getPersistedWalletTransactionTraceEvidence).not.toHaveBeenCalled();
  });

  it("fails closed when persisted evidence does not match the selected transaction", async () => {
    const changed = capture();
    changed.anchor.transaction_hash = "9".repeat(64);
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValue(changed);
    render(<GramTransactionProofCard runId={25} dataMode="real" transactions={[transaction()]} />);

    expect(await screen.findByText("Verification stopped")).toBeTruthy();
    expect(screen.queryByText(/Every captured transaction BOC/)).toBeNull();
    await waitFor(() => expect(apiMocks.getWalletTransactionTraceBocVerification).not.toHaveBeenCalled());
  });
});
