import type {
  WalletTraceBocVerificationResponse,
  WalletTransactionInclusionCatalogResponse,
} from "./types";

const HASH = /^[0-9a-f]{64}$/;
const ACCOUNT = /^(?:-1|0):[0-9a-f]{64}$/;
const POSITIVE_INTEGER = /^[1-9][0-9]*$/;

export function validateWalletTransactionInclusionCatalog(
  value: unknown,
  expected: WalletTraceBocVerificationResponse,
): WalletTransactionInclusionCatalogResponse {
  if (!value || typeof value !== "object") {
    throw new Error("Transaction inclusion response is invalid.");
  }
  const catalog = value as WalletTransactionInclusionCatalogResponse;
  if (
    catalog.contract_version !== "ton_transaction_inclusion_v1" ||
    catalog.boc_verification_id !== expected.verification_id ||
    catalog.provider_requests_performed !== false ||
    catalog.all_transaction_bocs_included_in_blocks !== true ||
    catalog.raw_bocs_returned !== false ||
    typeof catalog.message !== "string" ||
    catalog.message.trim().length === 0 ||
    catalog.message.length > 400 ||
    !HASH.test(catalog.catalog_digest_sha256 ?? "") ||
    !Array.isArray(catalog.proofs) ||
    !Array.isArray(catalog.proof_digests) ||
    catalog.proof_count !== catalog.proofs.length ||
    catalog.proof_count !== expected.summary.transaction_count ||
    catalog.proof_count < 1 ||
    catalog.proof_digests.length !== catalog.proofs.length
  ) {
    throw new Error("Transaction inclusion catalog contract changed.");
  }

  catalog.proofs.forEach((proof, index) => {
    if (!proof || typeof proof !== "object") {
      throw new Error("Transaction inclusion proof contract changed.");
    }
    if (
      proof.contract_version !== "ton_transaction_inclusion_v1" ||
      proof.network !== expected.network ||
      (proof.trust_level !== 0 && proof.trust_level !== 1) ||
      proof.canonical_block_chain_verified_at_capture !==
        (proof.trust_level === 0) ||
      proof.block_merkle_proof_verified !== true ||
      proof.provider_free_revalidated !== true ||
      proof.raw_bocs_returned !== false ||
      !ACCOUNT.test(proof.account_address_canonical ?? "") ||
      !POSITIVE_INTEGER.test(proof.logical_time ?? "") ||
      !HASH.test(proof.transaction_hash ?? "") ||
      !HASH.test(proof.transaction_boc_sha256 ?? "") ||
      !HASH.test(proof.block_proof_boc_sha256 ?? "") ||
      !HASH.test(proof.evidence_digest_sha256 ?? "") ||
      !isUtcIsoTimestamp(proof.verified_at) ||
      proof.transaction_hash !== expected.transactions[index]?.transaction_hash ||
      catalog.proof_digests[index] !== proof.evidence_digest_sha256 ||
      !validBlock(proof.block) ||
      !validBlock(proof.masterchain_anchor)
    ) {
      throw new Error("Transaction inclusion proof contract changed.");
    }
  });

  return catalog;
}

function isUtcIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$/.test(value) &&
    Number.isFinite(Date.parse(value))
  );
}

function validBlock(value: {
  workchain: number;
  shard: string;
  seqno: number;
  root_hash: string;
  file_hash: string;
}): boolean {
  return Boolean(
    value &&
      (value.workchain === -1 || value.workchain === 0) &&
      /^-?[0-9]{1,20}$/.test(value.shard) &&
      Number.isInteger(value.seqno) &&
      value.seqno > 0 &&
      HASH.test(value.root_hash) &&
      HASH.test(value.file_hash),
  );
}
