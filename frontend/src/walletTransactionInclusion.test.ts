import { describe, expect, it } from "vitest";

import type {
  WalletTraceBocVerificationResponse,
  WalletTransactionInclusionBlockRecord,
  WalletTransactionInclusionCatalogResponse,
  WalletTransactionInclusionVerifierPolicy,
} from "./types";
import {
  CURRENT_TRANSACTION_INCLUSION_POLICY,
  LEGACY_CHECKPOINT_TRANSACTION_INCLUSION_POLICY,
  LEGACY_TRANSACTION_INCLUSION_POLICY,
  validateWalletTransactionInclusionCatalog,
} from "./walletTransactionInclusion";

const FIRST_HASH = "1".repeat(64);
const SECOND_HASH = "2".repeat(64);
const MAINNET_CHECKPOINT: WalletTransactionInclusionBlockRecord = {
  workchain: -1,
  shard: "-9223372036854775808",
  seqno: 46_894_135,
  root_hash: "3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f",
  file_hash: "bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed",
};
const TESTNET_CHECKPOINT: WalletTransactionInclusionBlockRecord = {
  workchain: -1,
  shard: "-9223372036854775808",
  seqno: 58_834_988,
  root_hash: "8c711614c06a513e026dd1456f2f01a3b5b412f5a99ff1b050e23e9b103231d9",
  file_hash: "898c25a4599a33bea0b442e80ec3877461eaac824b497ebbbc670f7d077925d7",
};

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

function catalog({
  policy = CURRENT_TRANSACTION_INCLUSION_POLICY,
  trustLevel = 0,
}: {
  policy?: WalletTransactionInclusionVerifierPolicy;
  trustLevel?: 0 | 1;
} = {}): WalletTransactionInclusionCatalogResponse {
  const current = policy === CURRENT_TRANSACTION_INCLUSION_POLICY;
  const checkpointed = policy !== LEGACY_TRANSACTION_INCLUSION_POLICY;
  const checkpoint = checkpointed ? { ...MAINNET_CHECKPOINT } : null;
  const proofs = [FIRST_HASH, SECOND_HASH].map((hash, index) => ({
    contract_version: "ton_transaction_inclusion_v2" as const,
    evidence_contract_version: checkpointed
      ? ("ton_transaction_inclusion_v2" as const)
      : ("ton_transaction_inclusion_v1" as const),
    network: "ton-mainnet" as const,
    trust_level: trustLevel,
    verifier_policy_id: policy,
    trusted_checkpoint: checkpoint ? { ...checkpoint } : null,
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
    canonical_block_chain_verified_at_capture: current && trustLevel === 0,
    checkpoint_to_observed_head_transcript_persisted: false as const,
    provider_free_revalidated: true as const,
    raw_bocs_returned: false as const,
  }));
  return {
    contract_version: "ton_transaction_inclusion_v2",
    verifier_policy_id: policy,
    trusted_checkpoint: checkpoint,
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
  it("accepts the exact current-policy v2 catalog anchored to the network checkpoint", () => {
    const value = catalog();
    expect(validateWalletTransactionInclusionCatalog(value, boc())).toBe(value);
    expect(value.proofs.every((proof) => proof.canonical_block_chain_verified_at_capture)).toBe(true);
  });

  it("accepts current-policy trust-1 inclusion without claiming a canonical chain", () => {
    const value = catalog({ trustLevel: 1 });
    expect(validateWalletTransactionInclusionCatalog(value, boc())).toBe(value);
    expect(value.proofs.every((proof) => !proof.canonical_block_chain_verified_at_capture)).toBe(true);
  });

  it("binds the current policy to the exact checkpoint for the selected network", () => {
    const expected = boc();
    expected.network = "ton-testnet";
    const value = catalog();
    value.trusted_checkpoint = { ...TESTNET_CHECKPOINT };
    value.proofs.forEach((proof) => {
      proof.network = "ton-testnet";
      proof.trusted_checkpoint = { ...TESTNET_CHECKPOINT };
    });
    expect(validateWalletTransactionInclusionCatalog(value, expected)).toBe(value);

    value.proofs[0].trusted_checkpoint = { ...MAINNET_CHECKPOINT };
    expect(() => validateWalletTransactionInclusionCatalog(value, expected)).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });

  it("accepts legacy v1 evidence only as unpinned and non-canonical", () => {
    const value = catalog({ policy: LEGACY_TRANSACTION_INCLUSION_POLICY, trustLevel: 0 });
    expect(validateWalletTransactionInclusionCatalog(value, boc())).toBe(value);
    expect(value.trusted_checkpoint).toBeNull();
    expect(value.proofs[0].evidence_contract_version).toBe("ton_transaction_inclusion_v1");
    expect(value.proofs[0].canonical_block_chain_verified_at_capture).toBe(false);
  });

  it("accepts the former checkpoint policy only as non-canonical v2 evidence", () => {
    const value = catalog({
      policy: LEGACY_CHECKPOINT_TRANSACTION_INCLUSION_POLICY,
      trustLevel: 0,
    });
    expect(validateWalletTransactionInclusionCatalog(value, boc())).toBe(value);
    expect(value.trusted_checkpoint).toEqual(MAINNET_CHECKPOINT);
    expect(value.proofs[0].evidence_contract_version).toBe(
      "ton_transaction_inclusion_v2",
    );
    expect(value.proofs[0].canonical_block_chain_verified_at_capture).toBe(false);
  });

  it("rejects a proof set that swaps, omits or mixes BOC transaction identities and trust", () => {
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

    const mixedTrust = catalog();
    mixedTrust.proofs[1].trust_level = 1;
    mixedTrust.proofs[1].canonical_block_chain_verified_at_capture = false;
    expect(() => validateWalletTransactionInclusionCatalog(mixedTrust, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });

  it("rejects policy, checkpoint, evidence-version and canonicality mismatches", () => {
    const wrongCheckpoint = catalog();
    wrongCheckpoint.trusted_checkpoint!.root_hash = "f".repeat(64);
    wrongCheckpoint.proofs.forEach((proof) => {
      proof.trusted_checkpoint!.root_hash = "f".repeat(64);
    });
    expect(() => validateWalletTransactionInclusionCatalog(wrongCheckpoint, boc())).toThrow(
      "Transaction inclusion catalog contract changed.",
    );

    const legacyWithCheckpoint = catalog({ policy: LEGACY_TRANSACTION_INCLUSION_POLICY });
    legacyWithCheckpoint.trusted_checkpoint = { ...MAINNET_CHECKPOINT };
    expect(() => validateWalletTransactionInclusionCatalog(legacyWithCheckpoint, boc())).toThrow(
      "Transaction inclusion catalog contract changed.",
    );

    const currentWithLegacyEvidence = catalog();
    currentWithLegacyEvidence.proofs[0].evidence_contract_version =
      "ton_transaction_inclusion_v1";
    expect(() => validateWalletTransactionInclusionCatalog(currentWithLegacyEvidence, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );

    const overstatedLegacy = catalog({ policy: LEGACY_TRANSACTION_INCLUSION_POLICY });
    overstatedLegacy.proofs[0].canonical_block_chain_verified_at_capture = true;
    expect(() => validateWalletTransactionInclusionCatalog(overstatedLegacy, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );

    const overstatedLegacyCheckpoint = catalog({
      policy: LEGACY_CHECKPOINT_TRANSACTION_INCLUSION_POLICY,
    });
    overstatedLegacyCheckpoint.proofs[0].canonical_block_chain_verified_at_capture =
      true;
    expect(() =>
      validateWalletTransactionInclusionCatalog(overstatedLegacyCheckpoint, boc()),
    ).toThrow("Transaction inclusion proof contract changed.");

    const oldCatalogEnvelope = catalog();
    Object.assign(oldCatalogEnvelope, { contract_version: "ton_transaction_inclusion_v1" });
    expect(() => validateWalletTransactionInclusionCatalog(oldCatalogEnvelope, boc())).toThrow(
      "Transaction inclusion catalog contract changed.",
    );

    const oldProofEnvelope = catalog();
    Object.assign(oldProofEnvelope.proofs[0], {
      contract_version: "ton_transaction_inclusion_v1",
    });
    expect(() => validateWalletTransactionInclusionCatalog(oldProofEnvelope, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });

  it("requires the public transcript flag and rejects raw or internal response fields", () => {
    const transcript = catalog();
    Object.assign(transcript.proofs[0], {
      checkpoint_to_observed_head_transcript_persisted: true,
    });
    expect(() => validateWalletTransactionInclusionCatalog(transcript, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );

    const rawCatalog = catalog() as WalletTransactionInclusionCatalogResponse & {
      transaction_boc_hex: string;
    };
    rawCatalog.transaction_boc_hex = "00";
    expect(() => validateWalletTransactionInclusionCatalog(rawCatalog, boc())).toThrow(
      "Transaction inclusion catalog contract changed.",
    );

    const rawProof = catalog();
    Object.assign(rawProof.proofs[0], { block_proof_boc_hex: "00" });
    expect(() => validateWalletTransactionInclusionCatalog(rawProof, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );

    const internalCheckpoint = catalog();
    Object.assign(internalCheckpoint.trusted_checkpoint!, { source_url: "https://example.test" });
    expect(() => validateWalletTransactionInclusionCatalog(internalCheckpoint, boc())).toThrow(
      "Transaction inclusion catalog contract changed.",
    );
  });

  it.each([
    "2026-02-30T12:00:00Z",
    "2026-07-29T24:00:00Z",
  ])("rejects a non-existent or out-of-range verification instant %s", (verifiedAt) => {
    const value = catalog();
    value.proofs[0].verified_at = verifiedAt;
    expect(() => validateWalletTransactionInclusionCatalog(value, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });

  it("rejects logical time above the uint64 ceiling", () => {
    const value = catalog();
    value.proofs[0].logical_time = "18446744073709551616";
    expect(() => validateWalletTransactionInclusionCatalog(value, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });

  it("accepts the uint64 logical-time and signed-int64 shard ceilings", () => {
    const value = catalog();
    value.proofs[0].logical_time = "18446744073709551615";
    value.proofs[0].block.shard = "9223372036854775807";
    value.proofs[0].block.seqno = 1;
    expect(validateWalletTransactionInclusionCatalog(value, boc())).toBe(value);
  });

  it.each([0, 2_147_483_648])("rejects a block seqno outside positive signed-int32 (%s)", (seqno) => {
    const value = catalog();
    value.proofs[0].block.seqno = seqno;
    expect(() => validateWalletTransactionInclusionCatalog(value, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });

  it.each([
    "-0",
    "00",
    "9223372036854775808",
    "-9223372036854775809",
  ])("rejects a non-canonical or out-of-int64 shard %s", (shard) => {
    const value = catalog();
    value.proofs[0].block.shard = shard;
    expect(() => validateWalletTransactionInclusionCatalog(value, boc())).toThrow(
      "Transaction inclusion proof contract changed.",
    );
  });
});
