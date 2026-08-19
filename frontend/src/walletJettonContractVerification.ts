import { parseRfc3339Instant } from "./rfc3339";
import type {
  WalletAccountStateInclusionProofRecord,
  WalletJettonContractVerificationAnchorRecord,
  WalletJettonContractVerificationCatalogResponse,
  WalletJettonContractVerificationResponse,
} from "./types";

const HASH = /^[0-9a-f]{64}$/;
const ADDRESS = /^(?:-1|0):[0-9a-f]{64}$/;
const POSITIVE_ID = /^[1-9][0-9]{0,18}$/;
const BASE_UNITS = /^(?:0|[1-9][0-9]*)$/;
const MIN_INT64 = -9_223_372_036_854_775_808n;
const MAX_INT64 = 9_223_372_036_854_775_807n;
const CHECKPOINT_LIMITATION = "checkpoint_policy_not_persisted_v1" as const;

const RESPONSE_KEYS = [
  "account_state_boc_hashes",
  "account_state_inclusion_proofs",
  "account_state_proof_verified",
  "anchor",
  "asset_identity_key",
  "balance_snapshot_id",
  "contract_version",
  "eligible_for_cost_basis",
  "evidence_digest_sha256",
  "is_blockchain_inclusion_proof_verified",
  "is_ownership_proof",
  "jetton_asset_identity_applied",
  "jetton_content_hash",
  "jetton_master_account_canonical",
  "jetton_wallet_account_canonical",
  "limitations",
  "local_tvm_execution_applied",
  "master_code_hash",
  "master_data_hash",
  "master_wallet_address_verified",
  "masterchain_checkpoint_chain_verified",
  "message",
  "mintable",
  "network",
  "owner_account_canonical",
  "raw_account_state_bocs_persisted",
  "raw_account_state_bocs_returned",
  "run_id",
  "total_supply_base_units",
  "trust_level",
  "used_by_pnl",
  "verification_id",
  "verified_at",
  "verifier_name",
  "verifier_version",
  "wallet_balance_base_units",
  "wallet_code_consistency_verified",
  "wallet_code_hash",
  "wallet_data_hash",
  "wallet_owner_master_verified",
] as const;
const CATALOG_KEYS = [
  "catalog_digest_sha256",
  "contract_version",
  "message",
  "network",
  "provider_requests_performed",
  "raw_account_state_bocs_returned",
  "run_id",
  "verification_count",
  "verification_digests",
  "verifications",
] as const;
const ANCHOR_KEYS = ["file_hash", "root_hash", "seqno", "shard", "workchain"] as const;
const ACCOUNT_BOC_HASH_KEYS = [
  "master_code_boc_hex",
  "master_data_boc_hex",
  "wallet_code_boc_hex",
  "wallet_data_boc_hex",
] as const;
const PROOF_KEYS = [
  "account_address_canonical",
  "account_role",
  "boc_sha256",
  "contract_version",
  "evidence_digest_sha256",
  "provider_free_revalidated",
  "provider_requests_performed",
  "raw_bocs_returned",
  "shard_block",
  "verified_at",
] as const;
const PROOF_BOC_HASH_KEYS = [
  "account_proof_boc_hex",
  "shard_proof_boc_hex",
  "state_boc_hex",
] as const;

function fail(): never {
  throw new Error("Jetton contract proof response is incoherent.");
}

export function validateWalletJettonContractVerification(
  value: unknown,
  expectedRunId: number,
  expectedNetwork: "ton-mainnet" | "ton-testnet",
): WalletJettonContractVerificationResponse {
  if (!isRecord(value) || !hasExactKeys(value, RESPONSE_KEYS)) fail();
  const row = value;
  if (
    row.contract_version !== "ton_jetton_contract_verification_v1" ||
    row.run_id !== String(expectedRunId) ||
    row.network !== expectedNetwork ||
    !isPositiveId(row.verification_id) ||
    !isPositiveId(row.run_id) ||
    !isPositiveId(row.balance_snapshot_id) ||
    row.verifier_name !== "pytoniq-pytvm" ||
    typeof row.verifier_version !== "string" ||
    row.verifier_version.length < 1 ||
    row.verifier_version.length > 48 ||
    (row.trust_level !== 0 && row.trust_level !== 1) ||
    !validAnchor(row.anchor) ||
    !isAddress(row.owner_account_canonical) ||
    !isAddress(row.jetton_wallet_account_canonical) ||
    !isAddress(row.jetton_master_account_canonical) ||
    row.jetton_wallet_account_canonical === row.jetton_master_account_canonical ||
    row.asset_identity_key !==
      `ton_jetton_asset_v1|${expectedNetwork}|${row.jetton_master_account_canonical}` ||
    !isBaseUnits(row.wallet_balance_base_units) ||
    !isBaseUnits(row.total_supply_base_units) ||
    typeof row.mintable !== "boolean" ||
    !isHash(row.wallet_code_hash) ||
    !isHash(row.wallet_data_hash) ||
    !isHash(row.master_code_hash) ||
    !isHash(row.master_data_hash) ||
    !isHash(row.jetton_content_hash) ||
    !validHashRecord(row.account_state_boc_hashes, ACCOUNT_BOC_HASH_KEYS) ||
    !isHash(row.evidence_digest_sha256) ||
    !isUtcTimestamp(row.verified_at) ||
    row.account_state_proof_verified !== true ||
    row.masterchain_checkpoint_chain_verified !== false ||
    row.local_tvm_execution_applied !== true ||
    row.wallet_owner_master_verified !== true ||
    row.master_wallet_address_verified !== true ||
    row.wallet_code_consistency_verified !== true ||
    row.jetton_asset_identity_applied !== true ||
    typeof row.raw_account_state_bocs_persisted !== "boolean" ||
    row.raw_account_state_bocs_returned !== false ||
    row.is_blockchain_inclusion_proof_verified !== false ||
    row.eligible_for_cost_basis !== false ||
    row.used_by_pnl !== false ||
    row.is_ownership_proof !== false ||
    !Array.isArray(row.limitations) ||
    row.limitations.length !== 1 ||
    row.limitations[0] !== CHECKPOINT_LIMITATION ||
    typeof row.message !== "string" ||
    row.message.length < 1 ||
    row.message.length > 600 ||
    !Array.isArray(row.account_state_inclusion_proofs) ||
    (row.account_state_inclusion_proofs.length !== 0 &&
      row.account_state_inclusion_proofs.length !== 2) ||
    row.raw_account_state_bocs_persisted !==
      (row.account_state_inclusion_proofs.length === 2)
  ) {
    fail();
  }

  const expectedRoles = ["jetton_master", "jetton_wallet"] as const;
  row.account_state_inclusion_proofs.forEach((proof, index) => {
    const role = expectedRoles[index];
    const address = role === "jetton_master"
      ? row.jetton_master_account_canonical
      : row.jetton_wallet_account_canonical;
    if (!validAccountInclusionProof(proof, role, address, row.verified_at)) fail();
  });

  return value as unknown as WalletJettonContractVerificationResponse;
}

export function validateWalletJettonContractVerificationCatalog(
  value: unknown,
  expectedRunId: number,
  expectedNetwork: "ton-mainnet" | "ton-testnet",
): WalletJettonContractVerificationCatalogResponse {
  if (!isRecord(value) || !hasExactKeys(value, CATALOG_KEYS)) fail();
  const catalog = value;
  const verificationDigests = catalog.verification_digests;
  const verifications = catalog.verifications;
  if (
    catalog.contract_version !== "ton_jetton_contract_verification_v1" ||
    catalog.run_id !== String(expectedRunId) ||
    !isPositiveId(catalog.run_id) ||
    catalog.network !== expectedNetwork ||
    !Number.isSafeInteger(catalog.verification_count) ||
    (catalog.verification_count as number) < 0 ||
    (catalog.verification_count as number) > 500 ||
    !Array.isArray(verificationDigests) ||
    !Array.isArray(verifications) ||
    catalog.provider_requests_performed !== false ||
    catalog.raw_account_state_bocs_returned !== false ||
    !isHash(catalog.catalog_digest_sha256) ||
    typeof catalog.message !== "string" ||
    catalog.message.length < 1 ||
    catalog.message.length > 400 ||
    catalog.verification_count !== verifications.length ||
    verificationDigests.length !== verifications.length ||
    verificationDigests.some((digest) => !isHash(digest))
  ) {
    fail();
  }
  verifications.forEach((proof, index) => {
    const validated = validateWalletJettonContractVerification(
      proof,
      expectedRunId,
      expectedNetwork,
    );
    if (verificationDigests[index] !== validated.evidence_digest_sha256) fail();
  });
  return value as unknown as WalletJettonContractVerificationCatalogResponse;
}

function validAccountInclusionProof(
  value: unknown,
  role: "jetton_master" | "jetton_wallet",
  address: unknown,
  verifiedAt: unknown,
): value is WalletAccountStateInclusionProofRecord {
  if (!isRecord(value) || !hasExactKeys(value, PROOF_KEYS)) return false;
  return (
    value.contract_version === "ton_account_state_inclusion_v1" &&
    value.account_role === role &&
    value.account_address_canonical === address &&
    isAddress(value.account_address_canonical) &&
    validAnchor(value.shard_block) &&
    validHashRecord(value.boc_sha256, PROOF_BOC_HASH_KEYS) &&
    isHash(value.evidence_digest_sha256) &&
    value.verified_at === verifiedAt &&
    isUtcTimestamp(value.verified_at) &&
    value.provider_requests_performed === false &&
    value.provider_free_revalidated === true &&
    value.raw_bocs_returned === false
  );
}

function validAnchor(value: unknown): value is WalletJettonContractVerificationAnchorRecord {
  if (!isRecord(value) || !hasExactKeys(value, ANCHOR_KEYS)) return false;
  return (
    (value.workchain === -1 || value.workchain === 0) &&
    isCanonicalInt64(value.shard) &&
    Number.isSafeInteger(value.seqno) &&
    (value.seqno as number) > 0 &&
    (value.seqno as number) <= 2_147_483_647 &&
    isHash(value.root_hash) &&
    isHash(value.file_hash)
  );
}

function validHashRecord(value: unknown, keys: readonly string[]): boolean {
  return (
    isRecord(value) &&
    hasExactKeys(value, keys) &&
    Object.values(value).every(isHash)
  );
}

function isPositiveId(value: unknown): value is string {
  return typeof value === "string" && POSITIVE_ID.test(value);
}

function isAddress(value: unknown): value is string {
  return typeof value === "string" && ADDRESS.test(value);
}

function isBaseUnits(value: unknown): value is string {
  return typeof value === "string" && BASE_UNITS.test(value);
}

function isHash(value: unknown): value is string {
  return typeof value === "string" && HASH.test(value);
}

function isUtcTimestamp(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= 40 &&
    parseRfc3339Instant(value, { requireUtc: true, maximumFractionDigits: 6 }) !== null
  );
}

function isCanonicalInt64(value: unknown): value is string {
  if (
    typeof value !== "string" ||
    !/^(?:0|[1-9][0-9]*|-[1-9][0-9]*)$/.test(value) ||
    value.length > 20
  ) return false;
  const parsed = BigInt(value);
  return parsed >= MIN_INT64 && parsed <= MAX_INT64;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  );
}
