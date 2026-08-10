import {
  parseWalletCaseCoverage,
  type WalletCaseCoverage,
  type WalletCaseLimitation,
} from "./walletCase";
import { isCanonicalRawTonAddress } from "./tonAddress";
import { parseRfc3339Instant } from "./rfc3339";

export type WalletCaseActivityKind = "transaction" | "transfer" | "swap";
export type WalletCaseActivityDirection = "in" | "out" | "unknown";
export type WalletCaseActivityOutcome = "success" | "failed" | "unknown";
export type WalletCaseActivityDataOrigin = "demo_fixture" | "provider_observed";
export type WalletCaseActivitySort = "newest" | "oldest";

export interface WalletCaseActivityFilters {
  kinds: WalletCaseActivityKind[];
  directions: WalletCaseActivityDirection[];
  outcomes: WalletCaseActivityOutcome[];
  from_at: string | null;
  to_at: string | null;
  asset_id: string | null;
  protocol_id: string | null;
  counterparty: string | null;
  data_origins: WalletCaseActivityDataOrigin[];
  sort: WalletCaseActivitySort;
}

export interface WalletCaseActivityQuery extends WalletCaseActivityFilters {
  snapshot: string | null;
  limit: number;
  cursor?: string | null;
}

export interface WalletCaseActivitySnapshot {
  public_id: string;
  state: "partial" | "succeeded";
  completed_at: string;
  data_mode: "mock" | "real";
  provider: string;
  requested_period: { start_at: string; end_at: string };
  coverage: WalletCaseCoverage;
}

export interface WalletCaseActivityAsset {
  role: "asset" | "in" | "out";
  asset_id: string | null;
  identity_status: "network_scoped" | "unavailable";
  network: "ton-mainnet" | "ton-testnet";
  standard: "native" | "jetton" | "unknown";
  contract_address: string | null;
  symbol: string | null;
}

export interface WalletCaseActivityCounterparty {
  display_address: string;
  canonical_address: string | null;
  identity_status: "network_scoped" | "unavailable";
}

export interface WalletCaseActivityProtocol {
  status: "recognized" | "unknown" | "missing";
  id: string | null;
  family: string | null;
  version: string | null;
  label: string | null;
}

export type WalletCaseActivityDetails =
  | { kind: "transaction"; fee_ton: string | null }
  | { kind: "transfer"; amount: string | null }
  | {
      kind: "swap";
      amount_in: string | null;
      amount_out: string | null;
      estimated_usd: string | null;
    };

export interface WalletCaseActivityItem {
  public_id: string;
  kind: WalletCaseActivityKind;
  occurred_at: string | null;
  logical_time: string | null;
  direction: WalletCaseActivityDirection | null;
  outcome: WalletCaseActivityOutcome | null;
  counterparty: WalletCaseActivityCounterparty | null;
  assets: WalletCaseActivityAsset[];
  protocol: WalletCaseActivityProtocol | null;
  transaction: {
    linkage: "self" | "unknown";
    hash: string | null;
    event_id: string | null;
  };
  details: WalletCaseActivityDetails;
  provenance: {
    data_origin: WalletCaseActivityDataOrigin;
    evidence_level: "fixture" | "normalized_provider_observation";
    provider: string;
    source_status: string;
    identity_assurance: "network_scoped" | "provider_scoped" | "unavailable";
    deduplication_basis: "transaction_identity" | "event_action_identity" | "none";
    observation_count: number;
    suppressed_count: number;
    first_seen_sync_public_id: string;
    last_seen_sync_public_id: string;
  };
  limitations: WalletCaseLimitation[];
}

export interface WalletCaseActivityResponse {
  case_public_id: string;
  snapshot: WalletCaseActivitySnapshot | null;
  filters: WalletCaseActivityFilters;
  aggregate: {
    total_items: number;
    transactions: number;
    transfers: number;
    swaps: number;
    failed_transactions: number;
    source_sync_count: number;
    suppressed_duplicate_observations: number;
    conflicted_identity_count: number;
  };
  observed_period: { start_at: string; end_at: string } | null;
  gaps: Array<{
    code: string;
    surface: string | null;
    start_at: string | null;
    end_at: string | null;
    message: string;
  }>;
  limitations: WalletCaseLimitation[];
  items: WalletCaseActivityItem[];
  page: { limit: number; has_more: boolean; next_cursor: string | null };
}

export interface WalletCaseActivityDetailResponse {
  case_public_id: string;
  snapshot_public_id: string;
  item: WalletCaseActivityItem;
  source_observations: Array<{
    sync_public_id: string;
    observed_at: string | null;
    provider: string;
    source_status: string;
    data_origin: WalletCaseActivityDataOrigin;
  }>;
  sources_truncated: boolean;
}

const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const ACTIVITY_ID = /^act_[0-9a-f]{64}$/;
const ASSET_ID = /^asset_[0-9a-f]{64}$/;
const HASH = /^[0-9a-f]{64}$/;
const LOGICAL_TIME = /^(?:0|[1-9][0-9]{0,19})$/;
const MAX_UINT64 = 18_446_744_073_709_551_615n;
const DECIMAL = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const KINDS = new Set<WalletCaseActivityKind>(["transaction", "transfer", "swap"]);
const DIRECTIONS = new Set<WalletCaseActivityDirection>(["in", "out", "unknown"]);
const OUTCOMES = new Set<WalletCaseActivityOutcome>(["success", "failed", "unknown"]);
const ORIGINS = new Set<WalletCaseActivityDataOrigin>(["demo_fixture", "provider_observed"]);
const PROTOCOL_IDS = new Set([
  "dedust",
  "dedust_v3",
  "dedust_v3_memepad",
  "memeslab",
  "stonfi_v1",
  "stonfi_v2",
  "tonco",
  "tonfun",
]);

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${label} is invalid`);
  return value;
}

function nullableText(value: unknown, label: string): string | null {
  return value === null ? null : text(value, label);
}

function integer(value: unknown, label: string, minimum = 0): number {
  if (!Number.isInteger(value) || (value as number) < minimum) throw new Error(`${label} is invalid`);
  return value as number;
}

function timestamp(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (parseRfc3339Instant(parsed) === null) throw new Error(`${label} is invalid`);
  return parsed;
}

function nullableTimestamp(value: unknown, label: string): string | null {
  return value === null ? null : timestamp(value, label);
}

function instantNanoseconds(value: string, label: string): bigint {
  const parsed = parseRfc3339Instant(value);
  if (parsed === null) throw new Error(`${label} is invalid`);
  return parsed;
}

function uuid(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!UUID_V4.test(parsed)) throw new Error(`${label} is invalid`);
  return parsed;
}

function enumValue<T extends string>(value: unknown, values: Set<T>, label: string): T {
  const parsed = text(value, label) as T;
  if (!values.has(parsed)) throw new Error(`${label} is invalid`);
  return parsed;
}

function enumArray<T extends string>(value: unknown, values: Set<T>, label: string): T[] {
  if (!Array.isArray(value)) throw new Error(`${label} is invalid`);
  const parsed = value.map((item) => enumValue(item, values, label));
  if (new Set(parsed).size !== parsed.length) throw new Error(`${label} contains duplicates`);
  return parsed;
}

function limitations(value: unknown, label: string): WalletCaseLimitation[] {
  if (!Array.isArray(value)) throw new Error(`${label} is invalid`);
  return value.map((entry, index) => {
    const item = record(entry, `${label} ${index}`);
    return { code: text(item.code, `${label} code`), message: text(item.message, `${label} message`) };
  });
}

function nullableDecimal(value: unknown, label: string): string | null {
  if (value === null) return null;
  const parsed = text(value, label);
  if (!DECIMAL.test(parsed)) throw new Error(`${label} is invalid`);
  return parsed;
}

function boundedPeriod(value: unknown, label: string): { start_at: string; end_at: string } {
  const period = record(value, label);
  const startAt = timestamp(period.start_at, `${label} start`);
  const endAt = timestamp(period.end_at, `${label} end`);
  if (instantNanoseconds(startAt, label) >= instantNanoseconds(endAt, label)) throw new Error(`${label} is invalid`);
  return { start_at: startAt, end_at: endAt };
}

function parseFilters(value: unknown): WalletCaseActivityFilters {
  const filters = record(value, "activity filters");
  const fromAt = nullableTimestamp(filters.from_at, "activity filter start");
  const toAt = nullableTimestamp(filters.to_at, "activity filter end");
  if ((fromAt === null) !== (toAt === null) || (fromAt && toAt && instantNanoseconds(fromAt, "activity filter period") >= instantNanoseconds(toAt, "activity filter period"))) {
    throw new Error("activity filter period is invalid");
  }
  const assetId = nullableText(filters.asset_id, "activity asset filter");
  if (assetId !== null && !ASSET_ID.test(assetId)) throw new Error("activity asset filter is invalid");
  const protocolId = nullableText(filters.protocol_id, "activity protocol filter");
  if (protocolId !== null && !PROTOCOL_IDS.has(protocolId)) throw new Error("activity protocol filter is invalid");
  const counterparty = nullableText(filters.counterparty, "activity counterparty filter");
  if (counterparty !== null && !isCanonicalRawTonAddress(counterparty)) throw new Error("activity counterparty filter is invalid");
  return {
    kinds: enumArray(filters.kinds, KINDS, "activity kind filters"),
    directions: enumArray(filters.directions, DIRECTIONS, "activity direction filters"),
    outcomes: enumArray(filters.outcomes, OUTCOMES, "activity outcome filters"),
    from_at: fromAt,
    to_at: toAt,
    asset_id: assetId,
    protocol_id: protocolId,
    counterparty,
    data_origins: enumArray(filters.data_origins, ORIGINS, "activity origin filters"),
    sort: enumValue(filters.sort, new Set<WalletCaseActivitySort>(["newest", "oldest"]), "activity sort"),
  };
}

function parseAsset(value: unknown, index: number): WalletCaseActivityAsset {
  const asset = record(value, `activity asset ${index}`);
  const role = enumValue(asset.role, new Set<"asset" | "in" | "out">(["asset", "in", "out"]), `activity asset ${index} role`);
  const identityStatus = enumValue(
    asset.identity_status,
    new Set<"network_scoped" | "unavailable">(["network_scoped", "unavailable"]),
    `activity asset ${index} identity`,
  );
  const assetId = nullableText(asset.asset_id, `activity asset ${index} id`);
  if (assetId !== null && !ASSET_ID.test(assetId)) throw new Error(`activity asset ${index} id is invalid`);
  const standard = enumValue(asset.standard, new Set<"native" | "jetton" | "unknown">(["native", "jetton", "unknown"]), `activity asset ${index} standard`);
  const contractAddress = nullableText(asset.contract_address, `activity asset ${index} contract`);
  if (
    (identityStatus === "network_scoped" && (
      assetId === null || standard === "unknown" ||
      (standard === "native" && contractAddress !== null) ||
      (standard === "jetton" && (contractAddress === null || !isCanonicalRawTonAddress(contractAddress)))
    )) ||
    (identityStatus === "unavailable" && (
      assetId !== null || standard !== "unknown" || contractAddress !== null
    ))
  ) throw new Error(`activity asset ${index} identity is inconsistent`);
  return {
    role,
    asset_id: assetId,
    identity_status: identityStatus,
    network: enumValue(asset.network, new Set(["ton-mainnet", "ton-testnet"]), `activity asset ${index} network`),
    standard,
    contract_address: contractAddress,
    symbol: nullableText(asset.symbol, `activity asset ${index} symbol`),
  };
}

function parseItem(value: unknown): WalletCaseActivityItem {
  const item = record(value, "activity item");
  const publicId = text(item.public_id, "activity item id");
  if (!ACTIVITY_ID.test(publicId)) throw new Error("activity item id is invalid");
  const kind = enumValue(item.kind, KINDS, "activity item kind");
  const details = record(item.details, "activity item details");
  if (details.kind !== kind) throw new Error("activity details kind does not match its item");
  let parsedDetails: WalletCaseActivityDetails;
  if (kind === "transaction") {
    parsedDetails = { kind, fee_ton: nullableDecimal(details.fee_ton, "transaction fee") };
  } else if (kind === "transfer") {
    parsedDetails = { kind, amount: nullableDecimal(details.amount, "transfer amount") };
  } else {
    parsedDetails = {
      kind,
      amount_in: nullableDecimal(details.amount_in, "swap input amount"),
      amount_out: nullableDecimal(details.amount_out, "swap output amount"),
      estimated_usd: nullableDecimal(details.estimated_usd, "swap estimated value"),
    };
  }
  const counterparty = item.counterparty === null ? null : (() => {
    const party = record(item.counterparty, "activity counterparty");
    const identityStatus = enumValue(
      party.identity_status,
      new Set<"network_scoped" | "unavailable">(["network_scoped", "unavailable"]),
      "activity counterparty identity",
    );
    const canonicalAddress = nullableText(party.canonical_address, "activity counterparty canonical address");
    if (canonicalAddress !== null && !isCanonicalRawTonAddress(canonicalAddress)) {
      throw new Error("activity counterparty canonical address is invalid");
    }
    if ((identityStatus === "network_scoped") !== (canonicalAddress !== null)) {
      throw new Error("activity counterparty identity is inconsistent");
    }
    return {
      display_address: text(party.display_address, "activity counterparty display address"),
      canonical_address: canonicalAddress,
      identity_status: identityStatus,
    };
  })();
  const protocol = item.protocol === null ? null : (() => {
    const value = record(item.protocol, "activity protocol");
    const status = enumValue(value.status, new Set<"recognized" | "unknown" | "missing">(["recognized", "unknown", "missing"]), "activity protocol status");
    const id = nullableText(value.id, "activity protocol id");
    const family = nullableText(value.family, "activity protocol family");
    const version = nullableText(value.version, "activity protocol version");
    const label = nullableText(value.label, "activity protocol label");
    if (
      (status === "recognized" && (id === null || !PROTOCOL_IDS.has(id) || family === null || label === null)) ||
      (status === "unknown" && (id !== null || family !== null || version !== null || label === null)) ||
      (status === "missing" && (id !== null || family !== null || version !== null || label !== null))
    ) throw new Error("activity protocol identity is inconsistent");
    return {
      status,
      id,
      family,
      version,
      label,
    };
  })();
  const transaction = record(item.transaction, "activity transaction reference");
  const linkage = enumValue(transaction.linkage, new Set<"self" | "unknown">(["self", "unknown"]), "activity transaction linkage");
  const transactionHash = nullableText(transaction.hash, "activity transaction hash");
  if (transactionHash !== null && !HASH.test(transactionHash)) throw new Error("activity transaction hash is invalid");
  const eventId = nullableText(transaction.event_id, "activity event id");
  if (eventId !== null && !HASH.test(eventId)) throw new Error("activity event id is invalid");
  if (
    (linkage === "self" && (transactionHash === null || eventId !== null)) ||
    (linkage === "unknown" && transactionHash !== null) ||
    (transactionHash !== null && eventId !== null)
  ) throw new Error("activity transaction reference is inconsistent");
  const provenance = record(item.provenance, "activity provenance");
  const dataOrigin = enumValue(provenance.data_origin, ORIGINS, "activity data origin");
  const evidenceLevel = enumValue(
    provenance.evidence_level,
    new Set<"fixture" | "normalized_provider_observation">(["fixture", "normalized_provider_observation"]),
    "activity evidence level",
  );
  if ((dataOrigin === "demo_fixture") !== (evidenceLevel === "fixture")) {
    throw new Error("activity origin contradicts its evidence level");
  }
  const observationCount = integer(provenance.observation_count, "activity observation count", 1);
  const suppressedCount = integer(provenance.suppressed_count, "activity suppressed count");
  if (suppressedCount !== observationCount - 1) throw new Error("activity deduplication counts are inconsistent");
  const identityAssurance = enumValue(
    provenance.identity_assurance,
    new Set<"network_scoped" | "provider_scoped" | "unavailable">(["network_scoped", "provider_scoped", "unavailable"]),
    "activity identity assurance",
  );
  const deduplicationBasis = enumValue(
    provenance.deduplication_basis,
    new Set<"transaction_identity" | "event_action_identity" | "none">(["transaction_identity", "event_action_identity", "none"]),
    "activity deduplication basis",
  );
  if (identityAssurance === "unavailable" && (deduplicationBasis !== "none" || observationCount !== 1 || suppressedCount !== 0)) {
    throw new Error("unavailable Activity identity cannot be deduplicated");
  }
  const assets = Array.isArray(item.assets)
    ? item.assets.map(parseAsset)
    : (() => { throw new Error("activity assets are invalid"); })();
  const direction = item.direction === null ? null : enumValue(item.direction, DIRECTIONS, "activity direction");
  const outcome = item.outcome === null ? null : enumValue(item.outcome, OUTCOMES, "activity outcome");
  if (
    (kind === "transaction" && (
      assets.length !== 0 || direction !== null || outcome === null || counterparty !== null || protocol !== null ||
      !(
        (identityAssurance === "network_scoped" && deduplicationBasis === "transaction_identity" && linkage === "self") ||
        (identityAssurance === "unavailable" && deduplicationBasis === "none" && linkage === "unknown" && eventId === null)
      )
    )) ||
    (kind === "transfer" && (
      assets.length !== 1 || assets[0].role !== "asset" || direction === null || outcome !== null || protocol !== null ||
      linkage !== "unknown" || !(
        (identityAssurance === "provider_scoped" && deduplicationBasis === "event_action_identity" && eventId !== null) ||
        (identityAssurance === "unavailable" && deduplicationBasis === "none" && eventId === null)
      )
    )) ||
    (kind === "swap" && (
      assets.length !== 2 || assets[0].role !== "in" || assets[1].role !== "out" || direction !== null ||
      outcome !== null || counterparty !== null || protocol === null || linkage !== "unknown" || !(
        (identityAssurance === "provider_scoped" && deduplicationBasis === "event_action_identity" && eventId !== null) ||
        (identityAssurance === "unavailable" && deduplicationBasis === "none" && eventId === null)
      )
    ))
  ) throw new Error("activity item semantics are inconsistent");
  return {
    public_id: publicId,
    kind,
    occurred_at: nullableTimestamp(item.occurred_at, "activity occurrence time"),
    logical_time: item.logical_time === null ? null : (() => {
      const value = text(item.logical_time, "activity logical time");
      if (!LOGICAL_TIME.test(value) || BigInt(value) > MAX_UINT64) {
        throw new Error("activity logical time is invalid");
      }
      return value;
    })(),
    direction,
    outcome,
    counterparty,
    assets,
    protocol,
    transaction: {
      linkage,
      hash: transactionHash,
      event_id: eventId,
    },
    details: parsedDetails,
    provenance: {
      data_origin: dataOrigin,
      evidence_level: evidenceLevel,
      provider: text(provenance.provider, "activity provider"),
      source_status: text(provenance.source_status, "activity source status"),
      identity_assurance: identityAssurance,
      deduplication_basis: deduplicationBasis,
      observation_count: observationCount,
      suppressed_count: suppressedCount,
      first_seen_sync_public_id: uuid(provenance.first_seen_sync_public_id, "activity first-seen sync id"),
      last_seen_sync_public_id: uuid(provenance.last_seen_sync_public_id, "activity last-seen sync id"),
    },
    limitations: limitations(item.limitations, "activity item limitations"),
  };
}

export function parseWalletCaseActivityResponse(value: unknown): WalletCaseActivityResponse {
  const response = record(value, "Wallet Case Activity response");
  const casePublicId = uuid(response.case_public_id, "Wallet Case Activity case id");
  const snapshot = response.snapshot === null ? null : (() => {
    const item = record(response.snapshot, "Wallet Case Activity snapshot");
    const requestedPeriod = boundedPeriod(item.requested_period, "Wallet Case Activity requested period");
    const coverage = parseWalletCaseCoverage(item.coverage);
    if (coverage.requested_start_at !== requestedPeriod.start_at || coverage.requested_end_at !== requestedPeriod.end_at) {
      throw new Error("Wallet Case Activity snapshot coverage does not match its period");
    }
    return {
      public_id: uuid(item.public_id, "Wallet Case Activity snapshot id"),
      state: enumValue(item.state, new Set<"partial" | "succeeded">(["partial", "succeeded"]), "Wallet Case Activity snapshot state"),
      completed_at: timestamp(item.completed_at, "Wallet Case Activity snapshot completion"),
      data_mode: enumValue(item.data_mode, new Set<"mock" | "real">(["mock", "real"]), "Wallet Case Activity data mode"),
      provider: text(item.provider, "Wallet Case Activity provider"),
      requested_period: requestedPeriod,
      coverage,
    };
  })();
  const aggregateValue = record(response.aggregate, "Wallet Case Activity aggregate");
  const aggregate = {
    total_items: integer(aggregateValue.total_items, "activity total"),
    transactions: integer(aggregateValue.transactions, "activity transaction total"),
    transfers: integer(aggregateValue.transfers, "activity transfer total"),
    swaps: integer(aggregateValue.swaps, "activity swap total"),
    failed_transactions: integer(aggregateValue.failed_transactions, "activity failed transaction total"),
    source_sync_count: integer(aggregateValue.source_sync_count, "activity source sync total"),
    suppressed_duplicate_observations: integer(aggregateValue.suppressed_duplicate_observations, "activity suppressed duplicate total"),
    conflicted_identity_count: integer(aggregateValue.conflicted_identity_count, "activity conflict total"),
  };
  if (
    aggregate.transactions + aggregate.transfers + aggregate.swaps !== aggregate.total_items ||
    aggregate.failed_transactions > aggregate.transactions
  ) throw new Error("Wallet Case Activity aggregate is inconsistent");
  const parsedFilters = parseFilters(response.filters);
  const items = Array.isArray(response.items) ? response.items.map(parseItem) : (() => { throw new Error("Wallet Case Activity items are invalid"); })();
  if (items.length > aggregate.total_items || new Set(items.map((item) => item.public_id)).size !== items.length) {
    throw new Error("Wallet Case Activity page items are inconsistent");
  }
  if (snapshot && items.some((item) => (snapshot.data_mode === "mock") !== (item.provenance.data_origin === "demo_fixture"))) {
    throw new Error("Wallet Case Activity item origin contradicts its snapshot");
  }
  if (items.some((item) => !itemMatchesFilters(item, parsedFilters))) {
    throw new Error("Wallet Case Activity item does not match echoed filters");
  }
  const pageValue = record(response.page, "Wallet Case Activity page");
  const nextCursor = nullableText(pageValue.next_cursor, "Wallet Case Activity cursor");
  const hasMore = typeof pageValue.has_more === "boolean" ? pageValue.has_more : (() => { throw new Error("Wallet Case Activity pagination is invalid"); })();
  const page = { limit: integer(pageValue.limit, "Wallet Case Activity page limit", 1), has_more: hasMore, next_cursor: nextCursor };
  if (page.limit > 100 || items.length > page.limit || hasMore !== (nextCursor !== null) || (nextCursor && nextCursor.length > 1024)) {
    throw new Error("Wallet Case Activity pagination is inconsistent");
  }
  const observedPeriod = response.observed_period === null ? null : boundedPeriod(response.observed_period, "Wallet Case Activity observed period");
  if (!Array.isArray(response.gaps)) throw new Error("Wallet Case Activity gaps are invalid");
  const gaps = response.gaps.map((entry, index) => {
    const gap = record(entry, `Wallet Case Activity gap ${index}`);
    const startAt = nullableTimestamp(gap.start_at, `Wallet Case Activity gap ${index} start`);
    const endAt = nullableTimestamp(gap.end_at, `Wallet Case Activity gap ${index} end`);
    if ((startAt === null) !== (endAt === null) || (startAt && endAt && instantNanoseconds(startAt, `Wallet Case Activity gap ${index} period`) >= instantNanoseconds(endAt, `Wallet Case Activity gap ${index} period`))) {
      throw new Error(`Wallet Case Activity gap ${index} period is invalid`);
    }
    return {
      code: text(gap.code, `Wallet Case Activity gap ${index} code`),
      surface: nullableText(gap.surface, `Wallet Case Activity gap ${index} surface`),
      start_at: startAt,
      end_at: endAt,
      message: text(gap.message, `Wallet Case Activity gap ${index} message`),
    };
  });
  const parsedLimitations = limitations(response.limitations, "Wallet Case Activity limitations");
  if (snapshot === null) {
    if (
      aggregate.total_items !== 0 || aggregate.source_sync_count !== 0 || items.length !== 0 || observedPeriod !== null ||
      aggregate.suppressed_duplicate_observations !== 0 || aggregate.conflicted_identity_count !== 0 ||
      page.has_more || !gaps.some((item) => item.code === "not_synchronized") ||
      !parsedLimitations.some((item) => item.code === "not_synchronized")
    ) throw new Error("Unsynchronized Wallet Case Activity response published evidence");
  }
  return {
    case_public_id: casePublicId,
    snapshot,
    filters: parsedFilters,
    aggregate,
    observed_period: observedPeriod,
    gaps,
    limitations: parsedLimitations,
    items,
    page,
  };
}

function itemMatchesFilters(
  item: WalletCaseActivityItem,
  filters: WalletCaseActivityFilters,
): boolean {
  if (filters.kinds.length > 0 && !filters.kinds.includes(item.kind)) return false;
  if (filters.directions.length > 0 && (item.direction === null || !filters.directions.includes(item.direction))) return false;
  if (filters.outcomes.length > 0 && (item.outcome === null || !filters.outcomes.includes(item.outcome))) return false;
  if (filters.from_at !== null && filters.to_at !== null) {
    if (
      item.occurred_at === null ||
      instantNanoseconds(item.occurred_at, "activity occurrence time") < instantNanoseconds(filters.from_at, "activity filter start") ||
      instantNanoseconds(item.occurred_at, "activity occurrence time") >= instantNanoseconds(filters.to_at, "activity filter end")
    ) return false;
  }
  if (filters.asset_id !== null && !item.assets.some((asset) => asset.asset_id === filters.asset_id)) return false;
  if (filters.protocol_id !== null && item.protocol?.id !== filters.protocol_id) return false;
  if (filters.counterparty !== null && item.counterparty?.canonical_address !== filters.counterparty) return false;
  if (filters.data_origins.length > 0 && !filters.data_origins.includes(item.provenance.data_origin)) return false;
  return true;
}

export function parseWalletCaseActivityDetailResponse(value: unknown): WalletCaseActivityDetailResponse {
  const response = record(value, "Wallet Case Activity detail response");
  const sourceObservationsValue = response.source_observations;
  if (!Array.isArray(sourceObservationsValue) || sourceObservationsValue.length > 50) {
    throw new Error("Wallet Case Activity source observations are invalid");
  }
  const item = parseItem(response.item);
  const sourceObservations = sourceObservationsValue.map((entry, index) => {
    const observation = record(entry, `Wallet Case Activity source observation ${index}`);
    return {
      sync_public_id: uuid(observation.sync_public_id, `Wallet Case Activity source observation ${index} sync id`),
      observed_at: nullableTimestamp(observation.observed_at, `Wallet Case Activity source observation ${index} time`),
      provider: text(observation.provider, `Wallet Case Activity source observation ${index} provider`),
      source_status: text(observation.source_status, `Wallet Case Activity source observation ${index} status`),
      data_origin: enumValue(observation.data_origin, ORIGINS, `Wallet Case Activity source observation ${index} origin`),
    };
  });
  const sourcesTruncated = typeof response.sources_truncated === "boolean"
    ? response.sources_truncated
    : (() => { throw new Error("Wallet Case Activity source truncation flag is invalid"); })();
  if (
    (sourcesTruncated
      ? sourceObservations.length !== 50 || item.provenance.observation_count <= sourceObservations.length
      : sourceObservations.length !== item.provenance.observation_count) ||
    sourceObservations.some((observation) =>
      observation.data_origin !== item.provenance.data_origin ||
      observation.provider !== item.provenance.provider ||
      observation.source_status !== item.provenance.source_status
    ) ||
    new Set(sourceObservations.map((observation) => observation.sync_public_id)).size !== sourceObservations.length ||
    sourceObservations[0]?.sync_public_id !== item.provenance.first_seen_sync_public_id ||
    (!sourcesTruncated && (
      sourceObservations[sourceObservations.length - 1]?.sync_public_id !== item.provenance.last_seen_sync_public_id ||
      sourceObservations[sourceObservations.length - 1]?.provider !== item.provenance.provider ||
      sourceObservations[sourceObservations.length - 1]?.source_status !== item.provenance.source_status
    ))
  ) throw new Error("Wallet Case Activity detail provenance is inconsistent");
  return {
    case_public_id: uuid(response.case_public_id, "Wallet Case Activity detail case id"),
    snapshot_public_id: uuid(response.snapshot_public_id, "Wallet Case Activity detail snapshot id"),
    item,
    source_observations: sourceObservations,
    sources_truncated: sourcesTruncated,
  };
}

export function isWalletCaseActivityPublicId(value: string): boolean {
  return ACTIVITY_ID.test(value);
}

export function isWalletCaseSnapshotPublicId(value: string): boolean {
  return UUID_V4.test(value);
}

export function isWalletCaseAssetPublicId(value: string): boolean {
  return ASSET_ID.test(value);
}
