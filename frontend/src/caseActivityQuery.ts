import {
  isWalletCaseActivityPublicId,
  isWalletCaseAssetPublicId,
  isWalletCaseSnapshotPublicId,
  type WalletCaseActivityDataOrigin,
  type WalletCaseActivityDirection,
  type WalletCaseActivityFilters,
  type WalletCaseActivityKind,
  type WalletCaseActivityOutcome,
  type WalletCaseActivitySort,
} from "./walletCaseActivity";
import { isCanonicalRawTonAddress } from "./tonAddress";
import { parseRfc3339Instant } from "./rfc3339";

export interface CaseActivityUrlState {
  snapshot: string | null;
  filters: WalletCaseActivityFilters;
  selectedActivityId: string | null;
}

const ALLOWED_KEYS = new Set([
  "snapshot",
  "kind",
  "direction",
  "outcome",
  "from_at",
  "to_at",
  "asset_id",
  "protocol_id",
  "counterparty",
  "data_origin",
  "sort",
  "activity",
]);
const KINDS = new Set<WalletCaseActivityKind>(["transaction", "transfer", "swap"]);
const DIRECTIONS = new Set<WalletCaseActivityDirection>(["in", "out", "unknown"]);
const OUTCOMES = new Set<WalletCaseActivityOutcome>(["success", "failed", "unknown"]);
const ORIGINS = new Set<WalletCaseActivityDataOrigin>(["demo_fixture", "provider_observed"]);

export const CASE_ACTIVITY_PROTOCOL_IDS = [
  "dedust",
  "dedust_v3",
  "dedust_v3_memepad",
  "memeslab",
  "stonfi_v1",
  "stonfi_v2",
  "tonco",
  "tonfun",
] as const;
const PROTOCOL_IDS = new Set<string>(CASE_ACTIVITY_PROTOCOL_IDS);

export const DEFAULT_CASE_ACTIVITY_FILTERS: WalletCaseActivityFilters = {
  kinds: [],
  directions: [],
  outcomes: [],
  from_at: null,
  to_at: null,
  asset_id: null,
  protocol_id: null,
  counterparty: null,
  data_origins: [],
  sort: "newest",
};

export function canonicalizeCaseActivityFilters(
  filters: WalletCaseActivityFilters,
): WalletCaseActivityFilters {
  return {
    ...filters,
    kinds: [...KINDS].filter((value) => filters.kinds.includes(value)),
    directions: [...DIRECTIONS].filter((value) => filters.directions.includes(value)),
    outcomes: [...OUTCOMES].filter((value) => filters.outcomes.includes(value)),
    data_origins: [...ORIGINS].filter((value) => filters.data_origins.includes(value)),
  };
}

function one(params: URLSearchParams, key: string): string | null {
  const values = params.getAll(key);
  if (values.length > 1) throw new Error(`Activity query parameter ${key} cannot be repeated`);
  return values[0] ?? null;
}

function repeated<T extends string>(params: URLSearchParams, key: string, allowed: Set<T>): T[] {
  const values = params.getAll(key) as T[];
  if (values.some((value) => !allowed.has(value)) || new Set(values).size !== values.length) {
    throw new Error(`Activity query parameter ${key} is invalid`);
  }
  return [...allowed].filter((value) => values.includes(value));
}

function date(value: string | null, label: string): string | null {
  if (value === null) return null;
  if (parseRfc3339Instant(value, { requireUtc: true, maximumFractionDigits: 6 }) === null) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

function instantNanoseconds(value: string, label: string): bigint {
  const parsed = parseRfc3339Instant(value, { requireUtc: true, maximumFractionDigits: 6 });
  if (parsed === null) throw new Error(`${label} is invalid`);
  return parsed;
}

function boundedText(value: string | null, label: string, maximum: number): string | null {
  if (value === null) return null;
  if (!value || value.length > maximum || value !== value.trim()) throw new Error(`${label} is invalid`);
  return value;
}

function boundedRangeText(
  value: string | null,
  label: string,
  minimum: number,
  maximum: number,
): string | null {
  const parsed = boundedText(value, label, maximum);
  if (parsed !== null && parsed.length < minimum) throw new Error(`${label} is invalid`);
  return parsed;
}

export function parseCaseActivitySearch(search: string): CaseActivityUrlState {
  const params = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);
  for (const key of params.keys()) {
    if (!ALLOWED_KEYS.has(key)) throw new Error(`Unsupported Activity query parameter: ${key}`);
  }
  const snapshot = one(params, "snapshot");
  if (snapshot !== null && !isWalletCaseSnapshotPublicId(snapshot)) {
    throw new Error("Activity snapshot id must be a canonical UUIDv4");
  }
  const selectedActivityId = one(params, "activity");
  if (selectedActivityId !== null && !isWalletCaseActivityPublicId(selectedActivityId)) {
    throw new Error("Selected Activity id is invalid");
  }
  if (selectedActivityId !== null && snapshot === null) {
    throw new Error("Selected Activity requires an explicit snapshot");
  }
  const fromAt = date(one(params, "from_at"), "Activity start time");
  const toAt = date(one(params, "to_at"), "Activity end time");
  if (
    (fromAt === null) !== (toAt === null) ||
    (fromAt && toAt && instantNanoseconds(fromAt, "Activity start time") >= instantNanoseconds(toAt, "Activity end time"))
  ) {
    throw new Error("Activity time filters must form one increasing interval");
  }
  const assetId = one(params, "asset_id");
  if (assetId !== null && !isWalletCaseAssetPublicId(assetId)) {
    throw new Error("Activity asset filter must use a server asset id");
  }
  const sortValue = one(params, "sort") ?? "newest";
  if (sortValue !== "newest" && sortValue !== "oldest") throw new Error("Activity sort is invalid");
  const protocolId = boundedText(one(params, "protocol_id"), "Activity protocol filter", 32);
  if (protocolId !== null && !PROTOCOL_IDS.has(protocolId)) {
    throw new Error("Activity protocol filter is not recognized");
  }
  const counterparty = boundedRangeText(one(params, "counterparty"), "Activity counterparty filter", 66, 76);
  if (counterparty !== null && !isCanonicalRawTonAddress(counterparty)) {
    throw new Error("Activity counterparty filter must be a canonical raw TON address");
  }
  return {
    snapshot,
    selectedActivityId,
    filters: {
      kinds: repeated(params, "kind", KINDS),
      directions: repeated(params, "direction", DIRECTIONS),
      outcomes: repeated(params, "outcome", OUTCOMES),
      from_at: fromAt,
      to_at: toAt,
      asset_id: assetId,
      protocol_id: protocolId,
      counterparty,
      data_origins: repeated(params, "data_origin", ORIGINS),
      sort: sortValue as WalletCaseActivitySort,
    },
  };
}

export function caseActivitySearch(state: CaseActivityUrlState): string {
  const filters = canonicalizeCaseActivityFilters(state.filters);
  const params = new URLSearchParams();
  if (state.snapshot) params.set("snapshot", state.snapshot);
  filters.kinds.forEach((value) => params.append("kind", value));
  filters.directions.forEach((value) => params.append("direction", value));
  filters.outcomes.forEach((value) => params.append("outcome", value));
  if (filters.from_at) params.set("from_at", filters.from_at);
  if (filters.to_at) params.set("to_at", filters.to_at);
  if (filters.asset_id) params.set("asset_id", filters.asset_id);
  if (filters.protocol_id) params.set("protocol_id", filters.protocol_id);
  if (filters.counterparty) params.set("counterparty", filters.counterparty);
  filters.data_origins.forEach((value) => params.append("data_origin", value));
  params.set("sort", filters.sort);
  if (state.selectedActivityId) params.set("activity", state.selectedActivityId);
  const value = params.toString();
  return value ? `?${value}` : "";
}

export function sameCaseActivityFilters(
  left: WalletCaseActivityFilters,
  right: WalletCaseActivityFilters,
): boolean {
  return JSON.stringify(canonicalizeCaseActivityFilters(left)) === JSON.stringify(canonicalizeCaseActivityFilters(right));
}
