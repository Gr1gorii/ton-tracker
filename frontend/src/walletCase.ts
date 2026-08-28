import type { TimeWindow, WalletIngestionSurface } from "./types";
import {
  parseWalletCaseSyncManifestDescriptor,
  type WalletCaseSyncManifestDescriptor,
} from "./walletCaseSyncManifest";

export type WalletCaseNetwork = "ton-mainnet" | "ton-testnet";
export type WalletCaseDataEnvironment = "demo" | "live";
export type WalletCaseCatalogState = "active" | "archived";
export type WalletCaseSyncState =
  | "queued"
  | "running"
  | "partial"
  | "succeeded"
  | "failed"
  | "cancelled";
export type WalletCaseSyncMode = "bounded" | "incremental" | "resume";
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

export interface WalletCaseSyncRetry {
  attempt: number;
  max_attempts: number;
  retry_at: string;
  reason_code: string;
  message_safe: string;
}

export interface WalletCaseSyncError {
  code: string;
  message_safe: string;
  retryable: boolean;
}

export interface WalletCaseSyncResult {
  summary: WalletCaseSummary;
  coverage: WalletCaseCoverage;
  limitations: WalletCaseLimitation[];
  message: string;
}

export interface WalletCaseSync {
  public_id: string;
  case_public_id: string;
  state: WalletCaseSyncState;
  stage: string;
  status_version: number;
  poll_after_ms: number;
  cancel_requested: boolean;
  progress: { current: number; total: number | null };
  provider: string;
  data_mode: "mock" | "real";
  requested_scope: {
    mode: WalletCaseSyncMode;
    time_window: TimeWindow;
    start_at: string;
    end_at: string;
    surfaces: WalletIngestionSurface[];
    acquisition_start_at: string;
    acquisition_end_at: string;
    overlap_seconds: number;
    base_snapshot_public_id: string | null;
    source_checkpoint_public_id: string | null;
  };
  coverage: WalletCaseCoverage;
  summary: WalletCaseSummary;
  limitations: WalletCaseLimitation[];
  message: string;
  retry: WalletCaseSyncRetry | null;
  error: WalletCaseSyncError | null;
  result: WalletCaseSyncResult | null;
  acquisition_manifest: WalletCaseSyncManifestDescriptor | null;
  created_at: string;
  updated_at: string;
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
  metadata_version: number;
  created_at: string;
  updated_at: string;
  archived_at: string | null;
  latest_sync: WalletCaseSync | null;
  latest_sync_attempt: WalletCaseSync | null;
  active_sync: WalletCaseSync | null;
  current_snapshot: WalletCaseSync | null;
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

export interface WalletCaseMetadataUpdateRequest {
  expected_metadata_version: number;
  label?: string | null;
  note?: string | null;
}

export interface WalletCaseListResponse {
  cases: WalletCase[];
  limit: number;
  state: WalletCaseCatalogState;
  query: string | null;
  network: WalletCaseNetwork | null;
  data_environment: WalletCaseDataEnvironment | null;
  truncated: boolean;
  next_cursor: string | null;
}

export interface WalletCaseDeletionResponse {
  deleted: true;
  case_public_id: string;
  audit_event_public_id: string;
  deleted_at: string;
  removed: {
    syncs: number;
    ingestion_runs: number;
    evidence_verifications: number;
    report_revisions: number;
  };
}

export interface WalletCaseSyncRequest {
  mode: "bounded" | "incremental";
  time_window: TimeWindow;
  custom_start?: string;
  custom_end?: string;
  surfaces: WalletIngestionSurface[];
}

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CHECKPOINT_ID = /^scp_[0-9a-f]{64}$/;
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

function positiveInteger(value: unknown, label: string): number {
  const parsed = nonNegativeInteger(value, label);
  if (parsed === 0) throw new Error(`${label} is invalid`);
  return parsed;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") throw new Error(`${label} is invalid`);
  return value;
}

function timestamp(value: unknown, label: string): string {
  const parsed = string(value, label);
  if (!Number.isFinite(Date.parse(parsed))) throw new Error(`${label} is invalid`);
  return parsed;
}

function nullableTimestamp(value: unknown, label: string): string | null {
  if (value === null) return null;
  return timestamp(value, label);
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  return string(value, label);
}

function boundedNullableString(
  value: unknown,
  label: string,
  maximumLength: number,
): string | null {
  const parsed = nullableString(value, label);
  if (parsed !== null && parsed.length > maximumLength) {
    throw new Error(`${label} is too long`);
  }
  return parsed;
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

export function parseWalletCaseCoverage(value: unknown): WalletCaseCoverage {
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
    requested_start_at: timestamp(coverage.requested_start_at, "coverage start"),
    requested_end_at: timestamp(coverage.requested_end_at, "coverage end"),
    requested_surfaces: requestedSurfaces,
    unavailable_surfaces: unavailableSurfaces,
    incomplete_surfaces: incompleteSurfaces,
    streams,
    full_history_proven: false,
  };
}

function samePersistedSyncView(
  left: WalletCaseSync | null,
  right: WalletCaseSync | null,
): boolean {
  if (left === null || right === null) return left === right;
  const { poll_after_ms: _leftPollAfter, ...leftPersisted } = left;
  const { poll_after_ms: _rightPollAfter, ...rightPersisted } = right;
  return JSON.stringify(leftPersisted) === JSON.stringify(rightPersisted);
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
  const mode = string(requestedScope.mode, "case sync mode") as WalletCaseSyncMode;
  if (mode !== "bounded" && mode !== "incremental" && mode !== "resume") {
    throw new Error("case sync mode is invalid");
  }
  const casePublicId = string(sync.case_public_id, "case sync case id");
  if (!UUID_V4.test(casePublicId)) throw new Error("case sync case id is invalid");
  const startAt = timestamp(requestedScope.start_at, "case sync start");
  const endAt = timestamp(requestedScope.end_at, "case sync end");
  const acquisitionStartAt = timestamp(
    requestedScope.acquisition_start_at,
    "case sync acquisition start",
  );
  const acquisitionEndAt = timestamp(
    requestedScope.acquisition_end_at,
    "case sync acquisition end",
  );
  const overlapSeconds = nonNegativeInteger(
    requestedScope.overlap_seconds,
    "case sync overlap seconds",
  );
  const baseSnapshotPublicId = requestedScope.base_snapshot_public_id === null
    ? null
    : string(requestedScope.base_snapshot_public_id, "case sync base snapshot id");
  if (baseSnapshotPublicId !== null && !UUID_V4.test(baseSnapshotPublicId)) {
    throw new Error("case sync base snapshot id is invalid");
  }
  const sourceCheckpointPublicId = requestedScope.source_checkpoint_public_id === null
    ? null
    : string(
        requestedScope.source_checkpoint_public_id,
        "case sync source checkpoint id",
      );
  if (
    sourceCheckpointPublicId !== null &&
    !CHECKPOINT_ID.test(sourceCheckpointPublicId)
  ) {
    throw new Error("case sync source checkpoint id is invalid");
  }
  const surfaces = surfaceArray(requestedScope.surfaces, "case sync surfaces");
  const startTime = Date.parse(startAt);
  const endTime = Date.parse(endAt);
  const acquisitionStartTime = Date.parse(acquisitionStartAt);
  const acquisitionEndTime = Date.parse(acquisitionEndAt);
  if (
    surfaces.length === 0 ||
    !Number.isFinite(startTime) ||
    !Number.isFinite(endTime) ||
    startTime >= endTime
  ) {
    throw new Error("case sync requested scope is invalid");
  }
  if (
    overlapSeconds > 86_400 ||
    acquisitionStartTime < startTime ||
    acquisitionStartTime >= acquisitionEndTime ||
    acquisitionEndTime !== endTime
  ) {
    throw new Error("case sync acquisition scope is invalid");
  }
  if (
    (mode === "bounded" && (
      acquisitionStartAt !== startAt ||
      acquisitionEndAt !== endAt ||
      overlapSeconds !== 0 ||
      baseSnapshotPublicId !== null ||
      sourceCheckpointPublicId !== null
    )) ||
    (mode === "incremental" && (
      timeWindow !== "custom" ||
      baseSnapshotPublicId === null ||
      sourceCheckpointPublicId !== null
    )) ||
    (mode === "resume" && (
      timeWindow !== "custom" ||
      overlapSeconds !== 0 ||
      baseSnapshotPublicId === null ||
      sourceCheckpointPublicId === null
    ))
  ) {
    throw new Error("case sync acquisition mode contradicts its scope");
  }
  const coverage = parseWalletCaseCoverage(sync.coverage);
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
      (dataMode !== "real" || state !== "succeeded" || mode !== "bounded")) ||
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
  const stage = string(sync.stage, "case sync stage");
  const statusVersion = positiveInteger(sync.status_version, "case sync status version");
  const pollAfterMs = nonNegativeInteger(sync.poll_after_ms, "case sync poll interval");
  if (pollAfterMs < 500 || pollAfterMs > 15_000) {
    throw new Error("case sync poll interval is outside the supported range");
  }
  const cancelRequested = boolean(sync.cancel_requested, "case sync cancel flag");
  const retry = sync.retry === null
    ? null
    : (() => {
        const item = record(sync.retry, "case sync retry");
        const attempt = positiveInteger(item.attempt, "case sync retry attempt");
        const maxAttempts = positiveInteger(item.max_attempts, "case sync retry maximum");
        if (attempt > maxAttempts) throw new Error("case sync retry attempt exceeds its maximum");
        return {
          attempt,
          max_attempts: maxAttempts,
          retry_at: timestamp(item.retry_at, "case sync retry time"),
          reason_code: string(item.reason_code, "case sync retry reason"),
          message_safe: string(item.message_safe, "case sync retry message"),
        };
      })();
  if ((retry !== null) !== (state === "queued" && stage === "retry_wait")) {
    throw new Error("case sync retry metadata contradicts its lifecycle");
  }
  const error = sync.error === null
    ? null
    : (() => {
        const item = record(sync.error, "case sync error");
        return {
          code: string(item.code, "case sync error code"),
          message_safe: string(item.message_safe, "case sync error message"),
          retryable: boolean(item.retryable, "case sync error retryable flag"),
        };
      })();
  if ((error !== null) !== (state === "failed")) {
    throw new Error("case sync error metadata contradicts its lifecycle");
  }
  const summary = parseSummary(sync.summary);
  const limitations = parseLimitations(sync.limitations);
  const acquisitionManifest = sync.acquisition_manifest === null
    ? null
    : parseWalletCaseSyncManifestDescriptor(sync.acquisition_manifest);
  if (
    (["queued", "running", "cancelled"] as WalletCaseSyncState[]).includes(state) &&
    acquisitionManifest !== null
  ) {
    throw new Error("case sync acquisition manifest contradicts its lifecycle");
  }
  if (
    (state === "partial" || state === "succeeded") &&
    acquisitionManifest === null &&
    !limitations.some((item) => item.code === "acquisition_manifest_unavailable")
  ) {
    throw new Error("usable case sync omits its acquisition manifest boundary");
  }
  if (
    mode === "incremental" &&
    !limitations.some((item) => item.code === "incremental_composite_not_full_history")
  ) {
    throw new Error("incremental case sync omits its composite-history limitation");
  }
  if (
    mode === "resume" &&
    !limitations.some(
      (item) => item.code === "checkpoint_resume_composite_not_full_history",
    )
  ) {
    throw new Error("resume case sync omits its composite-history limitation");
  }
  const coverageResult = coverage;
  const message = string(sync.message, "case sync message");
  const result = sync.result === null
    ? null
    : (() => {
        const item = record(sync.result, "case sync result");
        return {
          summary: parseSummary(item.summary),
          coverage: parseWalletCaseCoverage(item.coverage),
          limitations: parseLimitations(item.limitations),
          message: string(item.message, "case sync result message"),
        };
      })();
  const publishesResult = state === "partial" || state === "succeeded";
  if ((result !== null) !== publishesResult) {
    throw new Error("case sync result contradicts its lifecycle");
  }
  if (
    result &&
    (JSON.stringify(result.summary) !== JSON.stringify(summary) ||
      JSON.stringify(result.coverage) !== JSON.stringify(coverageResult) ||
      JSON.stringify(result.limitations) !== JSON.stringify(limitations) ||
      result.message !== message)
  ) {
    throw new Error("case sync result does not match compatibility fields");
  }
  const createdAt = timestamp(sync.created_at, "case sync created time");
  const updatedAt = timestamp(sync.updated_at, "case sync updated time");
  const startedAt = nullableTimestamp(sync.started_at, "case sync started time");
  const completedAt = nullableTimestamp(sync.completed_at, "case sync completion time");
  if (Date.parse(updatedAt) < Date.parse(createdAt)) {
    throw new Error("case sync update predates creation");
  }
  if (startedAt && Date.parse(startedAt) < Date.parse(createdAt)) {
    throw new Error("case sync start predates creation");
  }
  if (completedAt && Date.parse(completedAt) < Date.parse(createdAt)) {
    throw new Error("case sync completion predates creation");
  }
  const terminal = ["partial", "succeeded", "failed", "cancelled"].includes(state);
  if ((completedAt !== null) !== terminal || (state === "running" && startedAt === null)) {
    throw new Error("case sync timestamps contradict its lifecycle");
  }
  return {
    public_id: publicId,
    case_public_id: casePublicId,
    state,
    stage,
    status_version: statusVersion,
    poll_after_ms: pollAfterMs,
    cancel_requested: cancelRequested,
    progress: {
      current: progressCurrent,
      total: progressTotal,
    },
    provider: string(sync.provider, "case sync provider"),
    data_mode: dataMode,
    requested_scope: {
      mode,
      time_window: timeWindow,
      start_at: startAt,
      end_at: endAt,
      surfaces,
      acquisition_start_at: acquisitionStartAt,
      acquisition_end_at: acquisitionEndAt,
      overlap_seconds: overlapSeconds,
      base_snapshot_public_id: baseSnapshotPublicId,
      source_checkpoint_public_id: sourceCheckpointPublicId,
    },
    coverage,
    summary,
    limitations,
    message,
    retry,
    error,
    result,
    acquisition_manifest: acquisitionManifest,
    created_at: createdAt,
    updated_at: updatedAt,
    started_at: startedAt,
    completed_at: completedAt,
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
  const latestSyncAttempt = item.latest_sync_attempt === null
    ? null
    : parseWalletCaseSync(item.latest_sync_attempt);
  const activeSync = item.active_sync === null ? null : parseWalletCaseSync(item.active_sync);
  const currentSnapshot = item.current_snapshot === null
    ? null
    : parseWalletCaseSync(item.current_snapshot);
  const syncs = [latestSync, latestSyncAttempt, activeSync, currentSnapshot].filter(
    (sync): sync is WalletCaseSync => sync !== null,
  );
  if (
    syncs.some(
      (sync) =>
        sync.case_public_id !== publicId ||
        (environment === "demo" ? sync.data_mode !== "mock" : sync.data_mode !== "real"),
    )
  ) {
    throw new Error("wallet case environment or identity does not match its sync evidence");
  }
  if (!samePersistedSyncView(latestSync, latestSyncAttempt)) {
    throw new Error("wallet case latest sync compatibility view is inconsistent");
  }
  if (
    activeSync &&
    (!latestSyncAttempt ||
      !["queued", "running"].includes(activeSync.state) ||
      !samePersistedSyncView(activeSync, latestSyncAttempt))
  ) {
    throw new Error("wallet case active sync is inconsistent");
  }
  if (
    !activeSync &&
    latestSyncAttempt &&
    ["queued", "running"].includes(latestSyncAttempt.state)
  ) {
    throw new Error("wallet case omits its active sync");
  }
  if (
    currentSnapshot &&
    (!["partial", "succeeded"].includes(currentSnapshot.state) ||
      currentSnapshot.result === null)
  ) {
    throw new Error("wallet case current snapshot is not publishable");
  }
  if (currentSnapshot && !latestSyncAttempt) {
    throw new Error("wallet case snapshot provenance has no latest sync attempt");
  }
  if (
    latestSyncAttempt &&
    ["partial", "succeeded"].includes(latestSyncAttempt.state) &&
    !samePersistedSyncView(currentSnapshot, latestSyncAttempt)
  ) {
    throw new Error("wallet case snapshot provenance does not match its latest usable sync");
  }
  const summary = parseSummary(item.summary);
  const limitations = parseLimitations(item.limitations);
  if (
    currentSnapshot !== null &&
    (JSON.stringify(summary) !== JSON.stringify(currentSnapshot.result?.summary) ||
      JSON.stringify(limitations) !== JSON.stringify(currentSnapshot.result?.limitations))
  ) {
    throw new Error("wallet case summary provenance does not match its current snapshot");
  }
  if (
    currentSnapshot === null && !isZeroSummary(summary)
  ) {
    throw new Error("wallet case without a snapshot cannot publish evidence summary data");
  }
  return {
    public_id: publicId,
    network,
    data_environment: environment,
    canonical_wallet_key: string(item.canonical_wallet_key, "canonical wallet key"),
    identity_version: string(item.identity_version, "wallet identity version"),
    display_address: string(item.display_address, "wallet display address"),
    label: boundedNullableString(item.label, "wallet case label", 120),
    note: boundedNullableString(item.note, "wallet case note", 4_000),
    metadata_version: positiveInteger(
      item.metadata_version,
      "wallet case metadata version",
    ),
    created_at: string(item.created_at, "wallet case created time"),
    updated_at: string(item.updated_at, "wallet case updated time"),
    archived_at: nullableTimestamp(item.archived_at, "wallet case archived time"),
    latest_sync: latestSync,
    latest_sync_attempt: latestSyncAttempt,
    active_sync: activeSync,
    current_snapshot: currentSnapshot,
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
  const cases = response.cases.map(parseWalletCase);
  const limit = positiveInteger(response.limit, "wallet case list limit");
  if (limit > 50 || cases.length > limit) {
    throw new Error("wallet case list exceeds its bounded limit");
  }
  if (new Set(cases.map((walletCase) => walletCase.public_id)).size !== cases.length) {
    throw new Error("wallet case list contains duplicate cases");
  }
  if (typeof response.truncated !== "boolean") {
    throw new Error("wallet case list truncated flag is invalid");
  }
  const state = string(
    response.state,
    "wallet case list lifecycle state",
  ) as WalletCaseCatalogState;
  if (state !== "active" && state !== "archived") {
    throw new Error("wallet case list lifecycle state is invalid");
  }
  const query = boundedNullableString(
    response.query,
    "wallet case list query",
    120,
  );
  if (query !== null && (!query || query.trim() !== query)) {
    throw new Error("wallet case list query is not canonical");
  }
  const network = response.network === null
    ? null
    : string(response.network, "wallet case list network") as WalletCaseNetwork;
  if (network !== null && !NETWORKS.has(network)) {
    throw new Error("wallet case list network is invalid");
  }
  const dataEnvironment = response.data_environment === null
    ? null
    : string(
        response.data_environment,
        "wallet case list data environment",
      ) as WalletCaseDataEnvironment;
  if (dataEnvironment !== null && !ENVIRONMENTS.has(dataEnvironment)) {
    throw new Error("wallet case list data environment is invalid");
  }
  const nextCursor = nullableString(
    response.next_cursor,
    "wallet case list next cursor",
  );
  if (nextCursor !== null && nextCursor.length > 1_024) {
    throw new Error("wallet case list next cursor is too long");
  }
  if (response.truncated !== (nextCursor !== null)) {
    throw new Error("wallet case list cursor contradicts its truncated flag");
  }
  if (response.truncated && cases.length !== limit) {
    throw new Error("truncated wallet case list does not fill its bounded page");
  }
  return {
    cases,
    limit,
    state,
    query,
    network,
    data_environment: dataEnvironment,
    truncated: response.truncated,
    next_cursor: nextCursor,
  };
}

export function parseWalletCaseDeletionResponse(
  value: unknown,
): WalletCaseDeletionResponse {
  const response = record(value, "wallet case deletion response");
  const casePublicId = string(response.case_public_id, "deleted wallet case id");
  const auditEventPublicId = string(
    response.audit_event_public_id,
    "wallet case deletion audit id",
  );
  if (
    response.deleted !== true ||
    !UUID_V4.test(casePublicId) ||
    !UUID_V4.test(auditEventPublicId)
  ) {
    throw new Error("wallet case deletion identity is invalid");
  }
  const removed = record(response.removed, "wallet case deletion counts");
  return {
    deleted: true,
    case_public_id: casePublicId,
    audit_event_public_id: auditEventPublicId,
    deleted_at: timestamp(response.deleted_at, "wallet case deletion time"),
    removed: {
      syncs: nonNegativeInteger(removed.syncs, "deleted case sync count"),
      ingestion_runs: nonNegativeInteger(
        removed.ingestion_runs,
        "deleted ingestion run count",
      ),
      evidence_verifications: nonNegativeInteger(
        removed.evidence_verifications,
        "deleted evidence verification count",
      ),
      report_revisions: nonNegativeInteger(
        removed.report_revisions,
        "deleted report revision count",
      ),
    },
  };
}

export function walletCaseEnvironmentLabel(environment: WalletCaseDataEnvironment): string {
  return environment === "live" ? "Live data" : "Demo data";
}
