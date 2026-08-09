import type { TimeWindow, WalletIngestionSurface } from "./types";

export type WalletCaseNetwork = "ton-mainnet" | "ton-testnet";
export type WalletCaseDataEnvironment = "demo" | "live";
export type WalletCaseSyncState =
  | "queued"
  | "running"
  | "partial"
  | "succeeded"
  | "failed"
  | "cancelled";
export type WalletCaseCoverageState =
  | "unknown"
  | "bounded_partial"
  | "bounded_complete";

export interface WalletCaseLimitation {
  code: string;
  message: string;
}

export interface WalletCaseActivityCounts {
  transfers: number;
  transactions: number;
  swaps: number;
  balances: number;
}

export interface WalletCasePortfolioSnapshot {
  total_balance_usd: string | null;
  priced_assets: number;
  unpriced_assets: number;
}

export interface WalletCaseSummary {
  activity_counts: WalletCaseActivityCounts;
  failed_transaction_count: number;
  warning_count: number;
  portfolio_snapshot: WalletCasePortfolioSnapshot;
}

export interface WalletCaseCoverageStream {
  provider: string;
  stream_key: string;
  completion_state: string;
  error_code: string | null;
}

export interface WalletCaseCoverage {
  state: WalletCaseCoverageState;
  requested_start_at: string;
  requested_end_at: string;
  requested_surfaces: WalletIngestionSurface[];
  unavailable_surfaces: WalletIngestionSurface[];
  incomplete_surfaces: WalletIngestionSurface[];
  streams: WalletCaseCoverageStream[];
  full_history_proven: false;
}

export interface WalletCaseSync {
  public_id: string;
  state: WalletCaseSyncState;
  stage: string;
  progress: { current: number; total: number | null };
  provider: string;
  data_mode: "mock" | "real";
  requested_scope: {
    time_window: TimeWindow;
    start_at: string;
    end_at: string;
    surfaces: WalletIngestionSurface[];
  };
  coverage: WalletCaseCoverage;
  summary: WalletCaseSummary;
  limitations: WalletCaseLimitation[];
  message: string;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface WalletCase {
  public_id: string;
  network: WalletCaseNetwork;
  data_environment: WalletCaseDataEnvironment;
  canonical_wallet_key: string;
  identity_version: string;
  display_address: string;
  label: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
  latest_sync: WalletCaseSync | null;
  summary: WalletCaseSummary;
  limitations: WalletCaseLimitation[];
}

export interface WalletCaseCreateRequest {
  wallet_address: string;
  network: WalletCaseNetwork;
  data_environment: WalletCaseDataEnvironment;
  label?: string;
  note?: string;
}

export interface WalletCaseUpsertResponse {
  created: boolean;
  case: WalletCase;
}

export interface WalletCaseListResponse {
  cases: WalletCase[];
  limit: number;
  truncated: boolean;
}

export interface WalletCaseSyncRequest {
  time_window: TimeWindow;
  custom_start?: string;
  custom_end?: string;
  surfaces: WalletIngestionSurface[];
}

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const NETWORKS = new Set<WalletCaseNetwork>(["ton-mainnet", "ton-testnet"]);
const ENVIRONMENTS = new Set<WalletCaseDataEnvironment>(["demo", "live"]);
const SYNC_STATES = new Set<WalletCaseSyncState>([
  "queued",
  "running",
  "partial",
  "succeeded",
  "failed",
  "cancelled",
]);
const TIME_WINDOWS = new Set<TimeWindow>(["24h", "3d", "7d", "custom"]);
const SURFACES = new Set<WalletIngestionSurface>([
  "transfers",
  "transactions",
  "swaps",
  "balances",
  "jettons",
]);
const STREAM_STATES = new Set(["complete", "incomplete", "error", "preview_only"]);

function record(value: unknown, label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string" || !value) throw new Error(`${label} is invalid`);
  return value;
}

function nonNegativeInteger(value: unknown, label: string): number {
  if (!Number.isInteger(value) || (value as number) < 0) {
    throw new Error(`${label} is invalid`);
  }
  return value as number;
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  return string(value, label);
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${label} is invalid`);
  }
  return value as string[];
}

function surfaceArray(value: unknown, label: string): WalletIngestionSurface[] {
  const values = stringArray(value, label) as WalletIngestionSurface[];
  if (values.some((item) => !SURFACES.has(item)) || new Set(values).size !== values.length) {
    throw new Error(`${label} is invalid`);
  }
  return values;
}

function parseSummary(value: unknown): WalletCaseSummary {
  const summary = record(value, "case summary");
  const counts = record(summary.activity_counts, "case activity counts");
  const portfolio = record(summary.portfolio_snapshot, "case portfolio snapshot");
  return {
    activity_counts: {
      transfers: nonNegativeInteger(counts.transfers, "transfer count"),
      transactions: nonNegativeInteger(counts.transactions, "transaction count"),
      swaps: nonNegativeInteger(counts.swaps, "swap count"),
      balances: nonNegativeInteger(counts.balances, "balance count"),
    },
    failed_transaction_count: nonNegativeInteger(
      summary.failed_transaction_count,
      "failed transaction count",
    ),
    warning_count: nonNegativeInteger(summary.warning_count, "warning count"),
    portfolio_snapshot: {
      total_balance_usd:
        portfolio.total_balance_usd === null
          ? null
          : string(portfolio.total_balance_usd, "portfolio total"),
      priced_assets: nonNegativeInteger(portfolio.priced_assets, "priced assets"),
      unpriced_assets: nonNegativeInteger(portfolio.unpriced_assets, "unpriced assets"),
    },
  };
}

function isZeroSummary(summary: WalletCaseSummary): boolean {
  return Object.values(summary.activity_counts).every((count) => count === 0) &&
    summary.failed_transaction_count === 0 &&
    summary.warning_count === 0 &&
    summary.portfolio_snapshot.total_balance_usd === null &&
    summary.portfolio_snapshot.priced_assets === 0 &&
    summary.portfolio_snapshot.unpriced_assets === 0;
}

function parseLimitations(value: unknown): WalletCaseLimitation[] {
  if (!Array.isArray(value)) throw new Error("case limitations must be an array");
  return value.map((item, index) => {
    const limitation = record(item, `case limitation ${index}`);
    return {
      code: string(limitation.code, `case limitation ${index} code`),
      message: string(limitation.message, `case limitation ${index} message`),
    };
  });
}

function parseCoverage(value: unknown): WalletCaseCoverage {
  const coverage = record(value, "case coverage");
  const state = string(coverage.state, "coverage state") as WalletCaseCoverageState;
  if (!["unknown", "bounded_partial", "bounded_complete"].includes(state)) {
    throw new Error("coverage state is invalid");
  }
  if (coverage.full_history_proven !== false) {
    throw new Error("bounded case coverage cannot claim full wallet history");
  }
  if (!Array.isArray(coverage.streams)) throw new Error("coverage streams are invalid");
  const requestedSurfaces = surfaceArray(
    coverage.requested_surfaces,
    "coverage requested surfaces",
  );
  const unavailableSurfaces = surfaceArray(
    coverage.unavailable_surfaces,
    "coverage unavailable surfaces",
  );
  const incompleteSurfaces = surfaceArray(
    coverage.incomplete_surfaces,
    "coverage incomplete surfaces",
  );
  if (requestedSurfaces.length === 0) {
    throw new Error("coverage requested surfaces cannot be empty");
  }
  const requested = new Set(requestedSurfaces);
  if (
    unavailableSurfaces.some((surface) => !requested.has(surface)) ||
    incompleteSurfaces.some((surface) => !requested.has(surface)) ||
    unavailableSurfaces.some((surface) => incompleteSurfaces.includes(surface))
  ) {
    throw new Error("coverage gaps do not match the requested surfaces");
  }
  const streams = coverage.streams.map((item, index) => {
    const stream = record(item, `coverage stream ${index}`);
    const completionState = string(
      stream.completion_state,
      `coverage stream ${index} state`,
    );
    if (!STREAM_STATES.has(completionState)) {
      throw new Error(`coverage stream ${index} state is invalid`);
    }
    return {
      provider: string(stream.provider, `coverage stream ${index} provider`),
      stream_key: string(stream.stream_key, `coverage stream ${index} key`),
      completion_state: completionState,
      error_code:
        stream.error_code === null
          ? null
          : string(stream.error_code, `coverage stream ${index} error`),
    };
  });
  if (
    state === "bounded_complete" &&
    (unavailableSurfaces.length > 0 ||
      incompleteSurfaces.length > 0 ||
      streams.some(
        (stream) => stream.completion_state !== "complete" || stream.error_code !== null,
      ))
  ) {
    throw new Error("complete coverage cannot contain incomplete evidence");
  }
  return {
    state,
    requested_start_at: string(coverage.requested_start_at, "coverage start"),
    requested_end_at: string(coverage.requested_end_at, "coverage end"),
    requested_surfaces: requestedSurfaces,
    unavailable_surfaces: unavailableSurfaces,
    incomplete_surfaces: incompleteSurfaces,
    streams,
    full_history_proven: false,
  };
}

export function parseWalletCaseSync(value: unknown): WalletCaseSync {
  const sync = record(value, "case sync");
  const publicId = string(sync.public_id, "case sync id");
  if (!UUID_V4.test(publicId)) throw new Error("case sync id is invalid");
  const state = string(sync.state, "case sync state") as WalletCaseSyncState;
  if (!SYNC_STATES.has(state)) throw new Error("case sync state is invalid");
  const progress = record(sync.progress, "case sync progress");
  const requestedScope = record(sync.requested_scope, "case sync requested scope");
  const dataMode = string(sync.data_mode, "case sync data mode");
  if (dataMode !== "mock" && dataMode !== "real") {
    throw new Error("case sync data mode is invalid");
  }
  const timeWindow = string(requestedScope.time_window, "case sync window") as TimeWindow;
  if (!TIME_WINDOWS.has(timeWindow)) throw new Error("case sync window is invalid");
  const startAt = string(requestedScope.start_at, "case sync start");
  const endAt = string(requestedScope.end_at, "case sync end");
  const surfaces = surfaceArray(requestedScope.surfaces, "case sync surfaces");
  const startTime = Date.parse(startAt);
  const endTime = Date.parse(endAt);
  if (
    surfaces.length === 0 ||
    !Number.isFinite(startTime) ||
    !Number.isFinite(endTime) ||
    startTime >= endTime
  ) {
    throw new Error("case sync requested scope is invalid");
  }
  const coverage = parseCoverage(sync.coverage);
  if (
    coverage.requested_start_at !== startAt ||
    coverage.requested_end_at !== endAt ||
    JSON.stringify(coverage.requested_surfaces) !== JSON.stringify(surfaces)
  ) {
    throw new Error("case sync coverage does not match its requested scope");
  }
  if (
    (dataMode === "mock" && coverage.state !== "unknown") ||
    (coverage.state === "bounded_complete" &&
      (dataMode !== "real" || state !== "succeeded")) ||
    (coverage.state === "bounded_partial" && dataMode !== "real")
  ) {
    throw new Error("case sync coverage state contradicts its evidence mode");
  }
  const progressCurrent = nonNegativeInteger(progress.current, "case sync progress current");
  const progressTotal = progress.total === null
    ? null
    : nonNegativeInteger(progress.total, "case sync progress total");
  if (progressTotal !== null && progressCurrent > progressTotal) {
    throw new Error("case sync progress exceeds its total");
  }
  return {
    public_id: publicId,
    state,
    stage: string(sync.stage, "case sync stage"),
    progress: {
      current: progressCurrent,
      total: progressTotal,
    },
    provider: string(sync.provider, "case sync provider"),
    data_mode: dataMode,
    requested_scope: {
      time_window: timeWindow,
      start_at: startAt,
      end_at: endAt,
      surfaces,
    },
    coverage,
    summary: parseSummary(sync.summary),
    limitations: parseLimitations(sync.limitations),
    message: string(sync.message, "case sync message"),
    created_at: string(sync.created_at, "case sync created time"),
    started_at: nullableString(sync.started_at, "case sync start time"),
    completed_at: nullableString(sync.completed_at, "case sync completion time"),
  };
}

export function parseWalletCase(value: unknown): WalletCase {
  const item = record(value, "wallet case");
  const publicId = string(item.public_id, "wallet case id");
  if (!UUID_V4.test(publicId)) throw new Error("wallet case id is invalid");
  const network = string(item.network, "wallet case network") as WalletCaseNetwork;
  const environment = string(
    item.data_environment,
    "wallet case data environment",
  ) as WalletCaseDataEnvironment;
  if (!NETWORKS.has(network)) throw new Error("wallet case network is invalid");
  if (!ENVIRONMENTS.has(environment)) {
    throw new Error("wallet case data environment is invalid");
  }
  const latestSync = item.latest_sync === null ? null : parseWalletCaseSync(item.latest_sync);
  if (
    latestSync &&
    ((environment === "demo" && latestSync.data_mode !== "mock") ||
      (environment === "live" && latestSync.data_mode !== "real"))
  ) {
    throw new Error("wallet case environment does not match its latest sync evidence");
  }
  const summary = parseSummary(item.summary);
  const limitations = parseLimitations(item.limitations);
  if (
    latestSync !== null &&
    (JSON.stringify(summary) !== JSON.stringify(latestSync.summary) ||
      JSON.stringify(limitations) !== JSON.stringify(latestSync.limitations))
  ) {
    throw new Error("wallet case summary provenance does not match its latest sync");
  }
  if (
    latestSync === null &&
    (!isZeroSummary(summary) || !limitations.some((item) => item.code === "not_synchronized"))
  ) {
    throw new Error("unsynchronized wallet case cannot publish evidence summary data");
  }
  return {
    public_id: publicId,
    network,
    data_environment: environment,
    canonical_wallet_key: string(item.canonical_wallet_key, "canonical wallet key"),
    identity_version: string(item.identity_version, "wallet identity version"),
    display_address: string(item.display_address, "wallet display address"),
    label: nullableString(item.label, "wallet case label"),
    note: nullableString(item.note, "wallet case note"),
    created_at: string(item.created_at, "wallet case created time"),
    updated_at: string(item.updated_at, "wallet case updated time"),
    latest_sync: latestSync,
    summary,
    limitations,
  };
}

export function parseWalletCaseUpsertResponse(value: unknown): WalletCaseUpsertResponse {
  const response = record(value, "wallet case upsert response");
  if (typeof response.created !== "boolean") {
    throw new Error("wallet case created flag is invalid");
  }
  return { created: response.created, case: parseWalletCase(response.case) };
}

export function parseWalletCaseListResponse(value: unknown): WalletCaseListResponse {
  const response = record(value, "wallet case list response");
  if (!Array.isArray(response.cases)) throw new Error("wallet case list is invalid");
  return {
    cases: response.cases.map(parseWalletCase),
    limit: nonNegativeInteger(response.limit, "wallet case list limit"),
    truncated:
      typeof response.truncated === "boolean"
        ? response.truncated
        : (() => {
            throw new Error("wallet case list truncated flag is invalid");
          })(),
  };
}

export function walletCaseEnvironmentLabel(environment: WalletCaseDataEnvironment): string {
  return environment === "live" ? "Live data" : "Demo data";
}
