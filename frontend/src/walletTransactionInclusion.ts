import type {
  WalletTraceBocVerificationResponse,
  WalletTransactionInclusionBlockRecord,
  WalletTransactionInclusionCatalogResponse,
  WalletTransactionInclusionVerifierPolicy,
} from "./types";
import { parseRfc3339Instant } from "./rfc3339";

const HASH = /^[0-9a-f]{64}$/;
const ACCOUNT = /^(?:-1|0):[0-9a-f]{64}$/;
const POSITIVE_INTEGER = /^[1-9][0-9]{0,19}$/;
const VERIFICATION_ID = /^[1-9][0-9]{0,18}$/;
const MAX_UINT64 = 18_446_744_073_709_551_615n;
const MIN_INT64 = -9_223_372_036_854_775_808n;
const MAX_INT64 = 9_223_372_036_854_775_807n;

export const LEGACY_TRANSACTION_INCLUSION_POLICY = "legacy_unpinned_v1" as const;
export const LEGACY_CHECKPOINT_TRANSACTION_INCLUSION_POLICY =
  "ton_liteserver_checkpoint_2026_08_v1" as const;
export const CURRENT_TRANSACTION_INCLUSION_POLICY =
  "ton_liteserver_checkpoint_strict_2026_08_v2" as const;

const CATALOG_KEYS = [
  "all_transaction_bocs_included_in_blocks",
  "boc_verification_id",
  "catalog_digest_sha256",
  "contract_version",
  "message",
  "proof_count",
  "proof_digests",
  "proofs",
  "provider_requests_performed",
  "raw_bocs_returned",
  "trusted_checkpoint",
  "verifier_policy_id",
] as const;
const PROOF_KEYS = [
  "account_address_canonical",
  "block",
  "block_merkle_proof_verified",
  "block_proof_boc_sha256",
  "canonical_block_chain_verified_at_capture",
  "checkpoint_to_observed_head_transcript_persisted",
  "contract_version",
  "evidence_contract_version",
  "evidence_digest_sha256",
  "logical_time",
  "masterchain_anchor",
  "network",
  "provider_free_revalidated",
  "raw_bocs_returned",
  "transaction_boc_sha256",
  "transaction_hash",
  "trust_level",
  "trusted_checkpoint",
  "verified_at",
  "verifier_policy_id",
] as const;
const BLOCK_KEYS = ["file_hash", "root_hash", "seqno", "shard", "workchain"] as const;

const TRUSTED_CHECKPOINTS: Record<
  WalletTraceBocVerificationResponse["network"],
  WalletTransactionInclusionBlockRecord
> = {
  "ton-mainnet": {
    workchain: -1,
    shard: "-9223372036854775808",
    seqno: 46_894_135,
    root_hash: "3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f",
    file_hash: "bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed",
  },
  "ton-testnet": {
    workchain: -1,
    shard: "-9223372036854775808",
    seqno: 58_834_988,
    root_hash: "8c711614c06a513e026dd1456f2f01a3b5b412f5a99ff1b050e23e9b103231d9",
    file_hash: "898c25a4599a33bea0b442e80ec3877461eaac824b497ebbbc670f7d077925d7",
  },
};

export function validateWalletTransactionInclusionCatalog(
  value: unknown,
  expected: WalletTraceBocVerificationResponse,
): WalletTransactionInclusionCatalogResponse {
  if (!isRecord(value) || !hasExactKeys(value, CATALOG_KEYS)) {
    throw new Error("Transaction inclusion catalog contract changed.");
  }
  const catalog = value;
  const proofs = catalog.proofs;
  const proofDigests = catalog.proof_digests;
  const policy = catalog.verifier_policy_id;
  const checkpoint = catalog.trusted_checkpoint;
  if (
    catalog.contract_version !== "ton_transaction_inclusion_v2" ||
    !isVerifierPolicy(policy) ||
    !validPolicyCheckpoint(policy, checkpoint, expected.network) ||
    catalog.boc_verification_id !== expected.verification_id ||
    !VERIFICATION_ID.test(String(catalog.boc_verification_id ?? "")) ||
    catalog.provider_requests_performed !== false ||
    catalog.all_transaction_bocs_included_in_blocks !== true ||
    catalog.raw_bocs_returned !== false ||
    typeof catalog.message !== "string" ||
    catalog.message.trim().length === 0 ||
    catalog.message.length > 400 ||
    !HASH.test(String(catalog.catalog_digest_sha256 ?? "")) ||
    !Array.isArray(proofs) ||
    !Array.isArray(proofDigests) ||
    !Number.isSafeInteger(catalog.proof_count) ||
    (catalog.proof_count as number) < 1 ||
    (catalog.proof_count as number) > 256 ||
    catalog.proof_count !== proofs.length ||
    catalog.proof_count !== expected.summary.transaction_count ||
    proofDigests.length !== proofs.length ||
    proofDigests.some((digest) => typeof digest !== "string" || !HASH.test(digest))
  ) {
    throw new Error("Transaction inclusion catalog contract changed.");
  }

  let catalogTrustLevel: 0 | 1 | null = null;
  proofs.forEach((proofValue, index) => {
    if (!isRecord(proofValue) || !hasExactKeys(proofValue, PROOF_KEYS)) {
      throw new Error("Transaction inclusion proof contract changed.");
    }
    const proof = proofValue;
    const trustLevel = proof.trust_level;
    const currentPolicy = policy === CURRENT_TRANSACTION_INCLUSION_POLICY;
    const legacyCheckpointPolicy =
      policy === LEGACY_CHECKPOINT_TRANSACTION_INCLUSION_POLICY;
    if (
      proof.contract_version !== "ton_transaction_inclusion_v2" ||
      proof.network !== expected.network ||
      (trustLevel !== 0 && trustLevel !== 1) ||
      proof.verifier_policy_id !== policy ||
      !sameNullableBlock(proof.trusted_checkpoint, checkpoint) ||
      (currentPolicy
        ? proof.evidence_contract_version !== "ton_transaction_inclusion_v2" ||
          !isCurrentTransactionInclusionCheckpoint(expected.network, proof.trusted_checkpoint) ||
          proof.canonical_block_chain_verified_at_capture !== (trustLevel === 0)
        : legacyCheckpointPolicy
          ? proof.evidence_contract_version !== "ton_transaction_inclusion_v2" ||
            !isCurrentTransactionInclusionCheckpoint(expected.network, proof.trusted_checkpoint) ||
            proof.canonical_block_chain_verified_at_capture !== false
        : proof.evidence_contract_version !== "ton_transaction_inclusion_v1" ||
          proof.trusted_checkpoint !== null ||
          proof.canonical_block_chain_verified_at_capture !== false) ||
      proof.checkpoint_to_observed_head_transcript_persisted !== false ||
      proof.block_merkle_proof_verified !== true ||
      proof.provider_free_revalidated !== true ||
      proof.raw_bocs_returned !== false ||
      typeof proof.account_address_canonical !== "string" ||
      !ACCOUNT.test(proof.account_address_canonical) ||
      !isCanonicalUint64(proof.logical_time) ||
      typeof proof.transaction_hash !== "string" ||
      !HASH.test(proof.transaction_hash) ||
      typeof proof.transaction_boc_sha256 !== "string" ||
      !HASH.test(proof.transaction_boc_sha256) ||
      typeof proof.block_proof_boc_sha256 !== "string" ||
      !HASH.test(proof.block_proof_boc_sha256) ||
      typeof proof.evidence_digest_sha256 !== "string" ||
      !HASH.test(proof.evidence_digest_sha256) ||
      !isUtcIsoTimestamp(proof.verified_at) ||
      proof.transaction_hash !== expected.transactions[index]?.transaction_hash ||
      proofDigests[index] !== proof.evidence_digest_sha256 ||
      !validBlock(proof.block) ||
      !validBlock(proof.masterchain_anchor)
    ) {
      throw new Error("Transaction inclusion proof contract changed.");
    }
    if (catalogTrustLevel === null) catalogTrustLevel = trustLevel;
    if (catalogTrustLevel !== trustLevel) {
      throw new Error("Transaction inclusion proof contract changed.");
    }
  });

  return value as unknown as WalletTransactionInclusionCatalogResponse;
}

function isVerifierPolicy(value: unknown): value is WalletTransactionInclusionVerifierPolicy {
  return (
    value === LEGACY_TRANSACTION_INCLUSION_POLICY ||
    value === LEGACY_CHECKPOINT_TRANSACTION_INCLUSION_POLICY ||
    value === CURRENT_TRANSACTION_INCLUSION_POLICY
  );
}

function validPolicyCheckpoint(
  policy: WalletTransactionInclusionVerifierPolicy,
  checkpoint: unknown,
  network: WalletTraceBocVerificationResponse["network"],
): boolean {
  return policy === LEGACY_TRANSACTION_INCLUSION_POLICY
    ? checkpoint === null
    : isCurrentTransactionInclusionCheckpoint(network, checkpoint);
}

export function isCurrentTransactionInclusionCheckpoint(
  network: WalletTraceBocVerificationResponse["network"],
  value: unknown,
): value is WalletTransactionInclusionBlockRecord {
  return sameBlock(value, TRUSTED_CHECKPOINTS[network]);
}

export function currentTransactionInclusionCheckpoint(
  network: WalletTraceBocVerificationResponse["network"],
): WalletTransactionInclusionBlockRecord {
  return { ...TRUSTED_CHECKPOINTS[network] };
}

function isUtcIsoTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 40 &&
    parseRfc3339Instant(value, { requireUtc: true, maximumFractionDigits: 6 }) !== null
  );
}

function isCanonicalUint64(value: unknown): value is string {
  return (
    typeof value === "string" &&
    POSITIVE_INTEGER.test(value) &&
    BigInt(value) <= MAX_UINT64
  );
}

function isCanonicalInt64(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !/^(?:0|[1-9][0-9]*|-[1-9][0-9]*)$/.test(value) ||
    value.length > 20
  ) {
    return false;
  }
  const parsed = BigInt(value);
  return parsed >= MIN_INT64 && parsed <= MAX_INT64;
}

function validBlock(value: unknown): value is WalletTransactionInclusionBlockRecord {
  if (!isRecord(value) || !hasExactKeys(value, BLOCK_KEYS)) return false;
  return (
    (value.workchain === -1 || value.workchain === 0) &&
    isCanonicalInt64(value.shard) &&
    Number.isInteger(value.seqno) &&
    (value.seqno as number) >= 1 &&
    (value.seqno as number) <= 2_147_483_647 &&
    typeof value.root_hash === "string" &&
    HASH.test(value.root_hash) &&
    typeof value.file_hash === "string" &&
    HASH.test(value.file_hash)
  );
}

function sameNullableBlock(left: unknown, right: unknown): boolean {
  if (left === null || right === null) return left === right;
  return sameBlock(left, right);
}

function sameBlock(left: unknown, right: unknown): boolean {
  return (
    validBlock(left) &&
    validBlock(right) &&
    left.workchain === right.workchain &&
    left.shard === right.shard &&
    left.seqno === right.seqno &&
    left.root_hash === right.root_hash &&
    left.file_hash === right.file_hash
  );
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  const keys = Object.keys(value).sort();
  const expected = [...allowed].sort();
  return (
    keys.length === expected.length &&
    keys.every((key, index) => key === expected[index])
  );
}
