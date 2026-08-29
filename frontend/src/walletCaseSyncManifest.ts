import type {
  WalletCaseNetwork,
  WalletCaseSyncMode,
  WalletCaseSyncState,
} from "./walletCase";
import type { WalletIngestionSurface } from "./types";

export interface WalletCaseSyncManifestDescriptor {
  public_id: string;
  contract_version: "wallet_case_sync_manifest_v1";
  content_hash_sha256: string;
  stream_count: number;
  page_count: number;
  response_digest_count: number;
  created_at: string;
}

export interface WalletCaseSyncManifestPeriod {
  start_at: string | null;
  end_at: string | null;
}

export interface WalletCaseSyncManifestPage {
  page_index: number;
  request_cursor: string | null;
  response_cursor: string | null;
  requested_limit: number;
  raw_count: number;
  normalized_count: number;
  duplicate_count: number;
  min_logical_time: string | null;
  max_logical_time: string | null;
  min_timestamp: string | null;
  max_timestamp: string | null;
  response_digest_sha256: string | null;
  attempt_count: number;
  error_code: string | null;
  fetched_at: string | null;
}

export interface WalletCaseSyncManifestStream {
  provider: string;
  stream_key: string;
  contract_version: string;
  scope_kind: string;
  requested_period: WalletCaseSyncManifestPeriod;
  sort_order: string | null;
  page_size: number;
  page_cap: number;
  completion_state: string;
  termination_reason: string | null;
  page_count: number;
  pages_succeeded: number;
  raw_count: number;
  normalized_count: number;
  duplicate_count: number;
  first_cursor: string | null;
  terminal_cursor: string | null;
  bounds_verified: boolean;
  error_code: string | null;
  started_at: string | null;
  finished_at: string | null;
  pages: WalletCaseSyncManifestPage[];
}

export interface WalletCaseSyncManifestDocument {
  contract_version: "wallet_case_sync_manifest_v1";
  case_public_id: string;
  sync_public_id: string;
  network: WalletCaseNetwork;
  data_mode: "mock" | "real";
  provider: string;
  sync_state: WalletCaseSyncState;
  snapshot_period: WalletCaseSyncManifestPeriod;
  acquisition_period: WalletCaseSyncManifestPeriod;
  acquisition_mode: WalletCaseSyncMode;
  overlap_seconds: number;
  base_snapshot_public_id: string | null;
  requested_surfaces: WalletIngestionSurface[];
  streams: WalletCaseSyncManifestStream[];
}

export interface WalletCaseSyncManifestResponse {
  manifest: WalletCaseSyncManifestDescriptor;
  document: WalletCaseSyncManifestDocument;
}

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const MANIFEST_ID = /^smf_([0-9a-f]{64})$/;
const SURFACES = new Set<WalletIngestionSurface>([
  "transfers", "transactions", "swaps", "balances", "jettons",
]);
const SYNC_STATES = new Set<WalletCaseSyncState>([
  "queued", "running", "partial", "succeeded", "failed", "cancelled",
]);

function fail(message: string): never {
  throw new Error(message);
}

function exactRecord(
  value: unknown,
  keys: readonly string[],
  label: string,
): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(`${label} is invalid`);
  }
  const item = value as Record<string, unknown>;
  if (
    Object.keys(item).length !== keys.length ||
    keys.some((key) => !Object.prototype.hasOwnProperty.call(item, key))
  ) fail(`${label} shape is invalid`);
  return item;
}

function text(value: unknown, label: string, maximum = Number.MAX_SAFE_INTEGER): string {
  if (typeof value !== "string" || !value || value.length > maximum) {
    fail(`${label} is invalid`);
  }
  return value;
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) fail(`${label} is invalid`);
  return value as number;
}

function timestamp(value: unknown, label: string): string {
  const parsed = text(value, label);
  if (!Number.isFinite(Date.parse(parsed))) fail(`${label} is invalid`);
  return parsed;
}

function nullableText(value: unknown, label: string, maximum: number): string | null {
  return value === null ? null : text(value, label, maximum);
}

function nullableTimestamp(value: unknown, label: string): string | null {
  return value === null ? null : timestamp(value, label);
}

function publicId(value: unknown, label: string): string {
  const parsed = text(value, label, 36);
  if (!UUID_V4.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function digest(value: unknown, label: string): string {
  const parsed = text(value, label, 64);
  if (!SHA256.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function parsePeriod(value: unknown, label: string): WalletCaseSyncManifestPeriod {
  const period = exactRecord(value, ["start_at", "end_at"], label);
  const start = nullableTimestamp(period.start_at, `${label} start`);
  const end = nullableTimestamp(period.end_at, `${label} end`);
  if ((start === null) !== (end === null) || (start && end && Date.parse(start) >= Date.parse(end))) {
    fail(`${label} bounds are invalid`);
  }
  return { start_at: start, end_at: end };
}

export function parseWalletCaseSyncManifestDescriptor(
  value: unknown,
): WalletCaseSyncManifestDescriptor {
  const item = exactRecord(value, [
    "public_id", "contract_version", "content_hash_sha256", "stream_count",
    "page_count", "response_digest_count", "created_at",
  ], "acquisition manifest descriptor");
  const hash = digest(item.content_hash_sha256, "acquisition manifest hash");
  const id = text(item.public_id, "acquisition manifest id", 68);
  const match = MANIFEST_ID.exec(id);
  if (!match || match[1] !== hash) fail("acquisition manifest identity is invalid");
  if (item.contract_version !== "wallet_case_sync_manifest_v1") {
    fail("acquisition manifest contract is unsupported");
  }
  const streamCount = integer(item.stream_count, "acquisition manifest stream count");
  const pageCount = integer(item.page_count, "acquisition manifest page count");
  const digestCount = integer(
    item.response_digest_count,
    "acquisition manifest response digest count",
  );
  if (digestCount > pageCount) fail("acquisition manifest digest count is invalid");
  return {
    public_id: id,
    contract_version: "wallet_case_sync_manifest_v1",
    content_hash_sha256: hash,
    stream_count: streamCount,
    page_count: pageCount,
    response_digest_count: digestCount,
    created_at: timestamp(item.created_at, "acquisition manifest creation time"),
  };
}

export function parseWalletCaseSyncManifestResponse(
  value: unknown,
): WalletCaseSyncManifestResponse {
  const response = exactRecord(value, ["manifest", "document"], "acquisition manifest response");
  const manifest = parseWalletCaseSyncManifestDescriptor(response.manifest);
  const document = parseDocument(response.document);
  const pages = document.streams.flatMap((stream) => stream.pages);
  if (
    manifest.stream_count !== document.streams.length ||
    manifest.page_count !== pages.length ||
    manifest.response_digest_count !== pages.filter(
      (page) => page.response_digest_sha256 !== null,
    ).length
  ) fail("acquisition manifest descriptor does not match its document");
  return { manifest, document };
}

function parseDocument(value: unknown): WalletCaseSyncManifestDocument {
  const item = exactRecord(value, [
    "contract_version", "case_public_id", "sync_public_id", "network", "data_mode",
    "provider", "sync_state", "snapshot_period", "acquisition_period",
    "acquisition_mode", "overlap_seconds", "base_snapshot_public_id",
    "requested_surfaces", "streams",
  ], "acquisition manifest document");
  if (item.contract_version !== "wallet_case_sync_manifest_v1") {
    fail("acquisition manifest document contract is unsupported");
  }
  const network = text(item.network, "acquisition manifest network") as WalletCaseNetwork;
  if (network !== "ton-mainnet" && network !== "ton-testnet") {
    fail("acquisition manifest network is invalid");
  }
  const dataMode = text(item.data_mode, "acquisition manifest data mode") as "mock" | "real";
  if (dataMode !== "mock" && dataMode !== "real") fail("acquisition manifest data mode is invalid");
  const state = text(item.sync_state, "acquisition manifest sync state") as WalletCaseSyncState;
  if (!SYNC_STATES.has(state)) fail("acquisition manifest sync state is invalid");
  const mode = text(item.acquisition_mode, "acquisition manifest mode") as WalletCaseSyncMode;
  if (mode !== "bounded" && mode !== "incremental" && mode !== "resume") {
    fail("acquisition manifest mode is invalid");
  }
  const snapshotPeriod = parsePeriod(item.snapshot_period, "acquisition manifest snapshot period");
  const acquisitionPeriod = parsePeriod(item.acquisition_period, "acquisition manifest acquisition period");
  if (!snapshotPeriod.start_at || !acquisitionPeriod.start_at) fail("acquisition manifest periods are required");
  const overlapSeconds = integer(item.overlap_seconds, "acquisition manifest overlap");
  if (overlapSeconds > 86_400) fail("acquisition manifest overlap is invalid");
  const baseId = item.base_snapshot_public_id === null
    ? null
    : publicId(item.base_snapshot_public_id, "acquisition manifest base snapshot id");
  if (
    (mode === "bounded" && (
      overlapSeconds !== 0 || baseId !== null ||
      JSON.stringify(snapshotPeriod) !== JSON.stringify(acquisitionPeriod)
    )) ||
    (mode === "incremental" && baseId === null) ||
    (mode === "resume" && (overlapSeconds !== 0 || baseId === null))
  ) fail("acquisition manifest lineage is invalid");
  if (!Array.isArray(item.requested_surfaces)) fail("acquisition manifest surfaces are invalid");
  const surfaces = item.requested_surfaces.map((surface) => text(surface, "acquisition manifest surface") as WalletIngestionSurface);
  if (
    surfaces.length === 0 || new Set(surfaces).size !== surfaces.length ||
    surfaces.some((surface) => !SURFACES.has(surface)) ||
    JSON.stringify(surfaces) !== JSON.stringify([...surfaces].sort())
  ) fail("acquisition manifest surfaces are invalid");
  if (!Array.isArray(item.streams)) fail("acquisition manifest streams are invalid");
  const streams = item.streams.map(parseStream);
  const streamKeys = streams.map((stream) => `${stream.provider}\0${stream.stream_key}`);
  if (
    new Set(streamKeys).size !== streamKeys.length ||
    JSON.stringify(streamKeys) !== JSON.stringify([...streamKeys].sort())
  ) fail("acquisition manifest stream order is invalid");
  return {
    contract_version: "wallet_case_sync_manifest_v1",
    case_public_id: publicId(item.case_public_id, "acquisition manifest case id"),
    sync_public_id: publicId(item.sync_public_id, "acquisition manifest sync id"),
    network,
    data_mode: dataMode,
    provider: text(item.provider, "acquisition manifest provider", 64),
    sync_state: state,
    snapshot_period: snapshotPeriod,
    acquisition_period: acquisitionPeriod,
    acquisition_mode: mode,
    overlap_seconds: overlapSeconds,
    base_snapshot_public_id: baseId,
    requested_surfaces: surfaces,
    streams,
  };
}

function parseStream(value: unknown, index: number): WalletCaseSyncManifestStream {
  const label = `acquisition manifest stream ${index}`;
  const item = exactRecord(value, [
    "provider", "stream_key", "contract_version", "scope_kind", "requested_period",
    "sort_order", "page_size", "page_cap", "completion_state", "termination_reason",
    "page_count", "pages_succeeded", "raw_count", "normalized_count", "duplicate_count",
    "first_cursor", "terminal_cursor", "bounds_verified", "error_code", "started_at",
    "finished_at", "pages",
  ], label);
  if (!Array.isArray(item.pages)) fail(`${label} pages are invalid`);
  const pages = item.pages.map(parsePage);
  if (new Set(pages.map((page) => page.page_index)).size !== pages.length) {
    fail(`${label} page indexes are invalid`);
  }
  const pageCount = integer(item.page_count, `${label} page count`);
  const pagesSucceeded = integer(item.pages_succeeded, `${label} pages succeeded`);
  if (pageCount !== pages.length || pagesSucceeded > pageCount) fail(`${label} page totals are invalid`);
  return {
    provider: text(item.provider, `${label} provider`, 64),
    stream_key: text(item.stream_key, `${label} key`, 40),
    contract_version: text(item.contract_version, `${label} contract`, 48),
    scope_kind: text(item.scope_kind, `${label} scope`, 24),
    requested_period: parsePeriod(item.requested_period, `${label} requested period`),
    sort_order: nullableText(item.sort_order, `${label} sort order`, 32),
    page_size: integer(item.page_size, `${label} page size`),
    page_cap: integer(item.page_cap, `${label} page cap`),
    completion_state: text(item.completion_state, `${label} completion state`, 24),
    termination_reason: nullableText(item.termination_reason, `${label} termination`, 48),
    page_count: pageCount,
    pages_succeeded: pagesSucceeded,
    raw_count: integer(item.raw_count, `${label} raw count`),
    normalized_count: integer(item.normalized_count, `${label} normalized count`),
    duplicate_count: integer(item.duplicate_count, `${label} duplicate count`),
    first_cursor: nullableText(item.first_cursor, `${label} first cursor`, 128),
    terminal_cursor: nullableText(item.terminal_cursor, `${label} terminal cursor`, 128),
    bounds_verified: typeof item.bounds_verified === "boolean"
      ? item.bounds_verified : fail(`${label} bounds verification is invalid`),
    error_code: nullableText(item.error_code, `${label} error`, 64),
    started_at: nullableTimestamp(item.started_at, `${label} start`),
    finished_at: nullableTimestamp(item.finished_at, `${label} finish`),
    pages,
  };
}

function parsePage(value: unknown, index: number): WalletCaseSyncManifestPage {
  const label = `acquisition manifest page ${index}`;
  const item = exactRecord(value, [
    "page_index", "request_cursor", "response_cursor", "requested_limit", "raw_count",
    "normalized_count", "duplicate_count", "min_logical_time", "max_logical_time",
    "min_timestamp", "max_timestamp", "response_digest_sha256", "attempt_count",
    "error_code", "fetched_at",
  ], label);
  return {
    page_index: integer(item.page_index, `${label} index`),
    request_cursor: nullableText(item.request_cursor, `${label} request cursor`, 128),
    response_cursor: nullableText(item.response_cursor, `${label} response cursor`, 128),
    requested_limit: integer(item.requested_limit, `${label} requested limit`),
    raw_count: integer(item.raw_count, `${label} raw count`),
    normalized_count: integer(item.normalized_count, `${label} normalized count`),
    duplicate_count: integer(item.duplicate_count, `${label} duplicate count`),
    min_logical_time: nullableText(item.min_logical_time, `${label} min LT`, 20),
    max_logical_time: nullableText(item.max_logical_time, `${label} max LT`, 20),
    min_timestamp: nullableTimestamp(item.min_timestamp, `${label} min timestamp`),
    max_timestamp: nullableTimestamp(item.max_timestamp, `${label} max timestamp`),
    response_digest_sha256: item.response_digest_sha256 === null
      ? null : digest(item.response_digest_sha256, `${label} response digest`),
    attempt_count: integer(item.attempt_count, `${label} attempt count`),
    error_code: nullableText(item.error_code, `${label} error`, 64),
    fetched_at: nullableTimestamp(item.fetched_at, `${label} fetched time`),
  };
}
