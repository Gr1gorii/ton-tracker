import type {
  WalletClusterCompareResponse,
  WalletClusterPairRecord,
  WalletSignalsRecord,
} from "./types";

const HASH = /^[0-9a-f]{64}$/;
const NONNEGATIVE_DECIMAL = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const SIGNED_DECIMAL = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const BANDS = [
  "weak/no signal",
  "weak similarity",
  "possible cluster",
  "likely related behavior",
  "very high similarity, still not proof",
] as const;
const RESPONSE_KEYS = [
  "comparison_window_seconds",
  "is_cluster_proof",
  "note",
  "pairs",
  "signal_basis",
  "wallets",
];
const WALLET_KEYS = [
  "avg_ton_per_buy_swap",
  "buy_swap_count",
  "canonical_activity_count",
  "canonical_ledger_digest_sha256",
  "counterparties",
  "data_mode",
  "distinct_tokens_touched",
  "first_buy_at",
  "incoming_activity_count",
  "outgoing_activity_count",
  "portfolio_value_usd",
  "run_id",
  "sell_swap_count",
  "signal_basis",
  "ton_balance",
  "wallet_address",
  "warnings",
];
const PAIR_KEYS = [
  "band",
  "note",
  "score",
  "shared_counterparties",
  "shared_tokens",
  "wallet_a_address",
  "wallet_a_run_id",
  "wallet_b_address",
  "wallet_b_run_id",
];

export function validateWalletClusterComparison(
  value: unknown,
  selectedRunIds: number[],
): WalletClusterCompareResponse {
  const expectedIds = uniqueRunIds(selectedRunIds);
  if (expectedIds.length < 2 || expectedIds.length > 25) fail();
  if (
    !isRecord(value) ||
    !hasExactKeys(value, RESPONSE_KEYS) ||
    value.is_cluster_proof !== false ||
    (value.signal_basis !== "legacy_mock_fixture" && value.signal_basis !== "canonical_native_activity_ledger") ||
    typeof value.comparison_window_seconds !== "number" ||
    !Number.isFinite(value.comparison_window_seconds) ||
    value.comparison_window_seconds < 3_600 ||
    !validText(value.note, 2_000) ||
    !Array.isArray(value.wallets) ||
    !Array.isArray(value.pairs) ||
    value.wallets.length !== expectedIds.length ||
    value.pairs.length !== expectedIds.length * (expectedIds.length - 1) / 2
  ) {
    fail();
  }

  const basis = value.signal_basis as "legacy_mock_fixture" | "canonical_native_activity_ledger";
  const wallets = value.wallets.map((row) => validateWallet(row, basis));
  if (!sameSet(wallets.map((row) => row.run_id), expectedIds)) fail();
  const modes = new Set(wallets.map((row) => row.data_mode));
  if (
    modes.size !== 1 ||
    (basis === "canonical_native_activity_ledger") !== modes.has("real")
  ) {
    fail();
  }
  const walletByRun = new Map(wallets.map((row) => [row.run_id, row]));
  const pairs = value.pairs.map((row) => validatePair(row, walletByRun));
  const expectedPairKeys = new Set<string>();
  expectedIds.forEach((left, index) => {
    expectedIds.slice(index + 1).forEach((right) => expectedPairKeys.add(pairKey(left, right)));
  });
  if (!sameSet(pairs.map((row) => pairKey(row.wallet_a_run_id, row.wallet_b_run_id)), [...expectedPairKeys])) fail();

  return {
    wallets,
    comparison_window_seconds: value.comparison_window_seconds,
    pairs,
    is_cluster_proof: false,
    signal_basis: basis,
    note: value.note,
  };
}

function validateWallet(value: unknown, basis: "legacy_mock_fixture" | "canonical_native_activity_ledger"): WalletSignalsRecord {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, WALLET_KEYS) ||
    !positiveInteger(value.run_id) ||
    !validText(value.wallet_address, 256) ||
    (value.data_mode !== "mock" && value.data_mode !== "real") ||
    value.signal_basis !== basis ||
    !signedDecimal(value.ton_balance) ||
    !(value.portfolio_value_usd === null || decimal(value.portfolio_value_usd)) ||
    !stringArray(value.distinct_tokens_touched, 500) ||
    !nonnegativeInteger(value.buy_swap_count) ||
    !nonnegativeInteger(value.sell_swap_count) ||
    !(value.avg_ton_per_buy_swap === null || decimal(value.avg_ton_per_buy_swap)) ||
    !(value.first_buy_at === null || utcTimestamp(value.first_buy_at)) ||
    !nonnegativeInteger(value.canonical_activity_count) ||
    !nonnegativeInteger(value.incoming_activity_count) ||
    !nonnegativeInteger(value.outgoing_activity_count) ||
    value.canonical_activity_count < value.incoming_activity_count + value.outgoing_activity_count ||
    !stringArray(value.counterparties, 2_304) ||
    !stringArray(value.warnings, 50, false)
  ) {
    fail();
  }
  if (basis === "canonical_native_activity_ledger") {
    if (
      value.data_mode !== "real" ||
      typeof value.canonical_ledger_digest_sha256 !== "string" ||
      !HASH.test(value.canonical_ledger_digest_sha256)
    ) fail();
  } else if (
    value.data_mode !== "mock" ||
    value.canonical_ledger_digest_sha256 !== null ||
    value.canonical_activity_count !== 0 ||
    value.incoming_activity_count !== 0 ||
    value.outgoing_activity_count !== 0 ||
    value.counterparties.length !== 0
  ) {
    fail();
  }
  return value as unknown as WalletSignalsRecord;
}

function validatePair(
  value: unknown,
  wallets: Map<number, WalletSignalsRecord>,
): WalletClusterPairRecord {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, PAIR_KEYS) ||
    !positiveInteger(value.wallet_a_run_id) ||
    !positiveInteger(value.wallet_b_run_id) ||
    value.wallet_a_run_id === value.wallet_b_run_id ||
    wallets.get(value.wallet_a_run_id)?.wallet_address !== value.wallet_a_address ||
    wallets.get(value.wallet_b_run_id)?.wallet_address !== value.wallet_b_address ||
    typeof value.score !== "number" ||
    !Number.isFinite(value.score) ||
    value.score < 0 ||
    value.score > 100 ||
    value.band !== expectedBand(value.score) ||
    !stringArray(value.shared_tokens, 500) ||
    !stringArray(value.shared_counterparties, 2_304) ||
    !validText(value.note, 2_000)
  ) {
    fail();
  }
  return value as unknown as WalletClusterPairRecord;
}

function expectedBand(score: number): (typeof BANDS)[number] {
  if (score >= 86) return BANDS[4];
  if (score >= 71) return BANDS[3];
  if (score >= 51) return BANDS[2];
  if (score >= 26) return BANDS[1];
  return BANDS[0];
}

function uniqueRunIds(values: number[]): number[] {
  if (!Array.isArray(values) || values.some((id) => !positiveInteger(id))) fail();
  return [...new Set(values)];
}

function pairKey(left: number, right: number): string {
  return left < right ? `${left}:${right}` : `${right}:${left}`;
}

function decimal(value: unknown): value is string {
  return typeof value === "string" && NONNEGATIVE_DECIMAL.test(value);
}

function signedDecimal(value: unknown): value is string {
  return typeof value === "string" && SIGNED_DECIMAL.test(value);
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}

function nonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function utcTimestamp(value: unknown): value is string {
  return typeof value === "string" && value.endsWith("Z") && Number.isFinite(Date.parse(value));
}

function stringArray(value: unknown, maximum: number, unique = true): value is string[] {
  return Array.isArray(value) && value.length <= maximum && value.every((row) => typeof row === "string" && row.trim().length > 0 && row.length <= 500) && (!unique || new Set(value).size === value.length);
}

function validText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maximum;
}

function sameSet<T>(left: T[], right: T[]): boolean {
  return left.length === right.length && left.every((value) => right.includes(value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: string[]): boolean {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  return actual.length === keys.length && actual.every((key, index) => key === keys[index]);
}

function fail(): never {
  throw new Error("Wallet comparison response is incoherent.");
}
