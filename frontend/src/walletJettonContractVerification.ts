import type {
  WalletJettonContractVerificationCatalogResponse,
  WalletJettonContractVerificationResponse,
} from "./types";

const HASH = /^[0-9a-f]{64}$/;
const ADDRESS = /^(?:-1|0):[0-9a-f]{64}$/;
const POSITIVE_ID = /^[1-9][0-9]*$/;
const BASE_UNITS = /^(?:0|[1-9][0-9]*)$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fail(): never {
  throw new Error("Jetton contract proof response is incoherent.");
}

export function validateWalletJettonContractVerification(
  value: unknown,
  expectedRunId: number,
  expectedNetwork: "ton-mainnet" | "ton-testnet",
): WalletJettonContractVerificationResponse {
  if (!isRecord(value)) fail();
  const row = value as unknown as WalletJettonContractVerificationResponse;
  if (
    row.contract_version !== "ton_jetton_contract_verification_v1" ||
    row.run_id !== String(expectedRunId) ||
    row.network !== expectedNetwork ||
    !POSITIVE_ID.test(row.verification_id) ||
    !POSITIVE_ID.test(row.balance_snapshot_id) ||
    row.verifier_name !== "pytoniq-pytvm" ||
    (row.trust_level !== 0 && row.trust_level !== 1) ||
    !ADDRESS.test(row.owner_account_canonical) ||
    !ADDRESS.test(row.jetton_wallet_account_canonical) ||
    !ADDRESS.test(row.jetton_master_account_canonical) ||
    row.jetton_wallet_account_canonical === row.jetton_master_account_canonical ||
    row.asset_identity_key !==
      `ton_jetton_asset_v1|${expectedNetwork}|${row.jetton_master_account_canonical}` ||
    !BASE_UNITS.test(row.wallet_balance_base_units) ||
    !BASE_UNITS.test(row.total_supply_base_units) ||
    typeof row.mintable !== "boolean" ||
    !HASH.test(row.wallet_code_hash) ||
    !HASH.test(row.wallet_data_hash) ||
    !HASH.test(row.master_code_hash) ||
    !HASH.test(row.master_data_hash) ||
    !HASH.test(row.jetton_content_hash) ||
    !HASH.test(row.evidence_digest_sha256) ||
    row.account_state_proof_verified !== true ||
    row.local_tvm_execution_applied !== true ||
    row.wallet_owner_master_verified !== true ||
    row.master_wallet_address_verified !== true ||
    row.wallet_code_consistency_verified !== true ||
    row.jetton_asset_identity_applied !== true ||
    row.raw_account_state_bocs_persisted !== true ||
    row.raw_account_state_bocs_returned !== false ||
    row.eligible_for_cost_basis !== false ||
    row.used_by_pnl !== false ||
    row.is_ownership_proof !== false ||
    row.masterchain_checkpoint_chain_verified !== (row.trust_level === 0) ||
    row.is_blockchain_inclusion_proof_verified !== (row.trust_level === 0) ||
    !isRecord(row.anchor) ||
    (row.anchor.workchain !== -1 && row.anchor.workchain !== 0) ||
    !/^-?[0-9]{1,20}$/.test(row.anchor.shard) ||
    !Number.isSafeInteger(row.anchor.seqno) ||
    row.anchor.seqno < 1 ||
    !HASH.test(row.anchor.root_hash) ||
    !HASH.test(row.anchor.file_hash) ||
    !isRecord(row.account_state_boc_hashes) ||
    typeof row.message !== "string" ||
    row.message.length === 0
  ) {
    fail();
  }
  const expectedBocKeys = [
    "master_code_boc_hex",
    "master_data_boc_hex",
    "wallet_code_boc_hex",
    "wallet_data_boc_hex",
  ];
  if (
    Object.keys(row.account_state_boc_hashes).sort().join("|") !==
      expectedBocKeys.join("|") ||
    Object.values(row.account_state_boc_hashes).some(
      (digest) => typeof digest !== "string" || !HASH.test(digest),
    )
  ) {
    fail();
  }
  return row;
}

export function validateWalletJettonContractVerificationCatalog(
  value: unknown,
  expectedRunId: number,
  expectedNetwork: "ton-mainnet" | "ton-testnet",
): WalletJettonContractVerificationCatalogResponse {
  if (!isRecord(value)) fail();
  const catalog = value as unknown as WalletJettonContractVerificationCatalogResponse;
  if (
    catalog.contract_version !== "ton_jetton_contract_verification_v1" ||
    catalog.run_id !== String(expectedRunId) ||
    catalog.network !== expectedNetwork ||
    !Number.isSafeInteger(catalog.verification_count) ||
    catalog.verification_count < 0 ||
    catalog.verification_count > 500 ||
    !Array.isArray(catalog.verification_digests) ||
    !Array.isArray(catalog.verifications) ||
    catalog.provider_requests_performed !== false ||
    catalog.raw_account_state_bocs_returned !== false ||
    !HASH.test(catalog.catalog_digest_sha256) ||
    typeof catalog.message !== "string" ||
    catalog.verification_count !== catalog.verifications.length ||
    catalog.verification_digests.length !== catalog.verifications.length
  ) {
    fail();
  }
  catalog.verifications.forEach((row, index) => {
    const validated = validateWalletJettonContractVerification(
      row,
      expectedRunId,
      expectedNetwork,
    );
    if (catalog.verification_digests[index] !== validated.evidence_digest_sha256) {
      fail();
    }
  });
  return catalog;
}
