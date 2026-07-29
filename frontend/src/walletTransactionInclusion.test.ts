import { describe, expect, it } from "vitest";

import type {
  WalletTraceBocVerificationResponse,
  WalletTransactionInclusionCatalogResponse,
} from "./types";
import { validateWalletTransactionInclusionCatalog } from "./walletTransactionInclusion";

const FIRST_HASH = "1".repeat(64);
const SECOND_HASH = "2".repeat(64);

function boc(): WalletTraceBocVerificationResponse {
  return {
    contract_version: "ton_boc_trace_verification_v1",
    verification_id: "4",
    capture_id: "3",
    run_id: "25",
    provider: "tonapi",
    source_status: "live",
    network: "ton-mainnet",
    verified_at: "2026-07-29T12:00:00Z",
    verifier: { name: "pytoniq-core", version: "0.1.46" },
    anchor: {
      transaction_hash: FIRST_HASH,
      logical_time: "46000000000001",
      account_canonical: `0:${"a".repeat(64)}`,
      matches_stored_transaction: true,
    },
    capture_evidence_digest_sha256: "b".repeat(64),
    evidence_digest_sha256: "c".repeat(64),
    summary: {
      transaction_count: 2,
      message_count: 2,
      total_boc_bytes: 200,
      normalized_external_in_hash_count: 0,
      direct_cell_hash_message_count: 2,
      body_hash_count: 2,
      opcode_count: 0,
    },
    transactions: [FIRST_HASH, SECOND_HASH].map((hash, index) => ({
      preorder_index: index,
      transaction_hash: hash,
      transaction_boc_bytes: 100,
      transaction_cell_hash: hash,
      raw_out_message_count: 0,
      message_count: 1,
      body_hash_count: 1,
      opcode_count: 0,
      message_evidence_digest_sha256: `${index + 3}`.repeat(64),
    })),
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
    message: "Local BOC verification.",
  };
}

function catalog(): WalletTransactionInclusionCatalogResponse {
  const proofs = [FIRST_HASH, SECOND_HASH].map((hash, index) => ({
    contract_version: "ton_transaction_inclusion_v1" as const,
    network: "ton-mainnet" as const,
    trust_level: 1 as const,
    account_address_canonical: `0:${"a".repeat(64)}`,
    logical_time: String(46000000000001 + index),
    transaction_hash: hash,
    block: {
      workchain: 0 as const,
      shard: "-9223372036854775808",
      seqno: 100 + index,
      root_hash: "d".repeat(64),
      file_hash: "e".repeat(64),
    },
    masterchain_anchor: {
      workchain: -1 as const,
      shard: "-9223372036854775808",
      seqno: 200,
      root_hash: "f".repeat(64),
      file_hash: "a".repeat(64),
    },
    transaction_boc_sha256: "b".repeat(64),
    block_proof_boc_sha256: "c".repeat(64),
    evidence_digest_sha256: `${index + 5}`.repeat(64),
    verified_at: "2026-07-29T12:00:00.123456Z",
    block_merkle_proof_verified: true as const,
    canonical_block_chain_verified_at_capture: false,
    provider_free_revalidated: true as const,
    raw_bocs_returned: false as const,
  }));
  return {
    contract_version: "ton_transaction_inclusion_v1",
    boc_verification_id: "4",
    proof_count: 2,
    proof_digests: proofs.map((row) => row.evidence_digest_sha256),
    proofs,
    catalog_digest_sha256: "9".repeat(64),
    provider_requests_performed: false,
    all_transaction_bocs_included_in_blocks: true,
    raw_bocs_returned: false,
    message: "Every BOC is included and provider-free revalidated.",
  };
}

describe("validateWalletTransactionInclusionCatalog", () => {
  it("accepts a complete BOC-bound inclusion catalog", () => {
    const value = catalog();
    expect(validateWalletTransactionInclusionCatalog(value, boc())).toBe(value);
  });

  it("rejects a proof set that swaps or omits BOC transaction identities", () => {
    const swapped = catalog();
    swapped.proofs.reverse();
    swapped.proof_digests = swapped.proofs.map((row) => row.evidence_digest_sha256);
    expect(() => validateWalletTransactionInclusionCatalog(swapped, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );

    const partial = catalog();
    partial.proofs.pop();
    partial.proof_digests.pop();
    partial.proof_count = 1;
    expect(() => validateWalletTransactionInclusionCatalog(partial, boc())).toThrow(
      "Transaction inclusion catalog contract changed.",
    );
  });

  it("rejects an overstated trust boundary", () => {
    const value = catalog();
    value.proofs[0].canonical_block_chain_verified_at_capture = true;
    expect(() => validateWalletTransactionInclusionCatalog(value, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });
});
