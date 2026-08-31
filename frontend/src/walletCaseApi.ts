import { API_BASE } from "./apiBase";
import {
  parseWalletCase,
  parseWalletCaseDeletionResponse,
  parseWalletCaseListResponse,
  parseWalletCaseSync,
  parseWalletCaseUpsertResponse,
  type WalletCase,
  type WalletCaseCatalogState,
  type WalletCaseCreateRequest,
  type WalletCaseDataEnvironment,
  type WalletCaseDeletionResponse,
  type WalletCaseListResponse,
  type WalletCaseMetadataUpdateRequest,
  type WalletCaseNetwork,
  type WalletCaseSync,
  type WalletCaseSyncRequest,
  type WalletCaseUpsertResponse,
} from "./walletCase";
import {
  parseWalletCaseSyncManifestResponse,
  type WalletCaseSyncManifestResponse,
} from "./walletCaseSyncManifest";
import {
  parseWalletCaseCheckpointContinuationReceipt,
  parseWalletCaseCheckpointContinuationPlan,
  parseWalletCaseStreamCheckpointCatalog,
  parseWalletCaseStreamCheckpointChain,
  parseWalletCaseStreamCheckpointDetail,
  parseWalletCaseStreamCheckpointHistory,
  type WalletCaseCheckpointContinuationReceiptResponse,
  type WalletCaseCheckpointContinuationPlanResponse,
  type WalletCaseStreamCheckpointCatalogResponse,
  type WalletCaseStreamCheckpointChainResponse,
  type WalletCaseStreamCheckpointDetailResponse,
  type WalletCaseStreamCheckpointHistoryResponse,
} from "./walletCaseStreamCheckpoint";
import {
  isWalletCaseAssetPublicId,
  isWalletCaseActivityPublicId,
  parseWalletCaseActivityDetailResponse,
  parseWalletCaseActivityResponse,
  type WalletCaseActivityDetailResponse,
  type WalletCaseActivityQuery,
  type WalletCaseActivityResponse,
} from "./walletCaseActivity";
import {
  CASE_ACTIVITY_PROTOCOL_IDS,
  canonicalizeCaseActivityFilters,
} from "./caseActivityQuery";
import { isCanonicalRawTonAddress } from "./tonAddress";
import { parseRfc3339Instant } from "./rfc3339";

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CHECKPOINT_ID = /^scp_[0-9a-f]{64}$/;
const CONTINUATION_PLAN_ID = /^cpl_[0-9a-f]{64}$/;
const ACTIVITY_KINDS = ["transaction", "transfer", "swap"] as const;
const ACTIVITY_DIRECTIONS = ["in", "out", "unknown"] as const;
const ACTIVITY_OUTCOMES = ["success", "failed", "unknown"] as const;
const ACTIVITY_ORIGINS = ["demo_fixture", "provider_observed"] as const;

interface StructuredApiDetail {
  code?: unknown;
  message?: unknown;
  message_safe?: unknown;
  retryable?: unknown;
  active_sync_public_id?: unknown;
  current_metadata_version?: unknown;
}

export class WalletCaseApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;
  readonly retryAfterMs: number | null;
  readonly activeSyncPublicId: string | null;
  readonly currentMetadataVersion: number | null;

  constructor({
    message,
    status,
    code = null,
    retryable = false,
    retryAfterMs = null,
    activeSyncPublicId = null,
    currentMetadataVersion = null,
  }: {
    message: string;
    status: number;
    code?: string | null;
    retryable?: boolean;
    retryAfterMs?: number | null;
    activeSyncPublicId?: string | null;
    currentMetadataVersion?: number | null;
  }) {
    super(message);
    this.name = "WalletCaseApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.retryAfterMs = retryAfterMs;
    this.activeSyncPublicId = activeSyncPublicId;
    this.currentMetadataVersion = currentMetadataVersion;
  }
}

export async function createWalletCase(
  request: WalletCaseCreateRequest,
  signal?: AbortSignal,
): Promise<WalletCaseUpsertResponse> {
  const response = await fetch(`${API_BASE}/api/v1/cases`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
    signal,
  });
  if (!response.ok) {
    throw await walletCaseResponseError(response, "Wallet Case creation failed");
  }
  return parseWalletCaseUpsertResponse(await response.json());
}

export interface WalletCaseListRequest {
  limit?: number;
  state?: WalletCaseCatalogState;
  query?: string | null;
  network?: WalletCaseNetwork | null;
  dataEnvironment?: WalletCaseDataEnvironment | null;
  cursor?: string | null;
  signal?: AbortSignal;
}

export async function listWalletCases({
  limit = 20,
  state = "active",
  query = null,
  network = null,
  dataEnvironment = null,
  cursor = null,
  signal,
}: WalletCaseListRequest = {}): Promise<WalletCaseListResponse> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 50) {
    throw new Error("Wallet Case list limit must be from 1 through 50");
  }
  if (state !== "active" && state !== "archived") {
    throw new Error("Wallet Case list lifecycle state is invalid");
  }
  if (query !== null && typeof query !== "string") {
    throw new Error("Wallet Case list query must contain 1 through 120 characters");
  }
  const canonicalQuery = query?.trim() || null;
  if (query !== null && (canonicalQuery === null || canonicalQuery.length > 120)) {
    throw new Error("Wallet Case list query must contain 1 through 120 characters");
  }
  if (network !== null && network !== "ton-mainnet" && network !== "ton-testnet") {
    throw new Error("Wallet Case list network is invalid");
  }
  if (dataEnvironment !== null && dataEnvironment !== "demo" && dataEnvironment !== "live") {
    throw new Error("Wallet Case list data environment is invalid");
  }
  const params = new URLSearchParams({ limit: String(limit), state });
  if (canonicalQuery !== null) params.set("q", canonicalQuery);
  if (network !== null) params.set("network", network);
  if (dataEnvironment !== null) params.set("data_environment", dataEnvironment);
  if (cursor !== null) {
    if (!cursor || cursor.length > 1_024 || cursor.trim() !== cursor) {
      throw new Error("Wallet Case list cursor is invalid");
    }
    params.set("cursor", cursor);
  }
  const response = await fetch(`${API_BASE}/api/v1/cases?${params}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw await walletCaseResponseError(response, "Wallet Case list failed");
  }
  const catalog = parseWalletCaseListResponse(await response.json());
  if (catalog.limit !== limit) {
    throw new Error("Wallet Case list response does not match the requested limit");
  }
  if (catalog.state !== state) {
    throw new Error("Wallet Case list response does not match the requested lifecycle state");
  }
  if (
    catalog.query !== canonicalQuery ||
    catalog.network !== network ||
    catalog.data_environment !== dataEnvironment
  ) {
    throw new Error("Wallet Case list response does not match the requested filters");
  }
  return catalog;
}

export async function archiveWalletCase(
  caseId: string,
  signal?: AbortSignal,
): Promise<WalletCase> {
  return transitionWalletCaseLifecycle(caseId, "archive", signal);
}

export async function restoreWalletCase(
  caseId: string,
  signal?: AbortSignal,
): Promise<WalletCase> {
  return transitionWalletCaseLifecycle(caseId, "restore", signal);
}

async function transitionWalletCaseLifecycle(
  caseId: string,
  action: "archive" | "restore",
  signal?: AbortSignal,
): Promise<WalletCase> {
  assertPublicId(caseId, "Wallet Case id");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/${action}`,
    { method: "POST", cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      `Wallet Case ${action === "archive" ? "archival" : "restoration"} failed`,
    );
  }
  const walletCase = parseWalletCase(await response.json());
  if (
    walletCase.public_id !== caseId ||
    (action === "archive") !== (walletCase.archived_at !== null)
  ) {
    throw new Error("Wallet Case lifecycle response does not match the request");
  }
  return walletCase;
}

export async function getWalletCase(
  caseId: string,
  signal?: AbortSignal,
): Promise<WalletCase> {
  assertPublicId(caseId, "Wallet Case id");
  const response = await fetch(`${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw await walletCaseResponseError(response, "Wallet Case read failed");
  }
  const walletCase = parseWalletCase(await response.json());
  if (walletCase.public_id !== caseId) {
    throw new Error("Wallet Case response does not match the requested case id");
  }
  return walletCase;
}

export async function updateWalletCaseMetadata(
  current: WalletCase,
  request: WalletCaseMetadataUpdateRequest,
  signal?: AbortSignal,
): Promise<WalletCase> {
  assertPublicId(current.public_id, "Wallet Case id");
  if (
    !Number.isSafeInteger(request.expected_metadata_version) ||
    request.expected_metadata_version < 1 ||
    request.expected_metadata_version !== current.metadata_version
  ) {
    throw new Error("Wallet Case metadata version is invalid");
  }
  if (!("label" in request) && !("note" in request)) {
    throw new Error("Wallet Case metadata update is empty");
  }
  if (
    request.label !== undefined && request.label !== null &&
    (typeof request.label !== "string" || request.label.length > 120)
  ) {
    throw new Error("Wallet Case label is invalid");
  }
  if (
    request.note !== undefined && request.note !== null &&
    (typeof request.note !== "string" || request.note.length > 4_000)
  ) {
    throw new Error("Wallet Case note is invalid");
  }
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(current.public_id)}`,
    {
      method: "PATCH",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal,
    },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(response, "Wallet Case metadata update failed");
  }
  const updated = parseWalletCase(await response.json());
  const immutableKeys = [
    "public_id",
    "network",
    "data_environment",
    "canonical_wallet_key",
    "identity_version",
    "display_address",
    "created_at",
  ] as const;
  if (
    immutableKeys.some((key) => updated[key] !== current[key]) ||
    updated.metadata_version !== current.metadata_version + 1 ||
    ("label" in request && updated.label !== request.label) ||
    ("note" in request && updated.note !== request.note)
  ) {
    throw new Error("Wallet Case metadata response does not match the request");
  }
  return updated;
}

export async function deleteWalletCase(
  caseId: string,
  signal?: AbortSignal,
): Promise<WalletCaseDeletionResponse> {
  assertPublicId(caseId, "Wallet Case id");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}`,
    { method: "DELETE", cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(response, "Wallet Case deletion failed");
  }
  const receipt = parseWalletCaseDeletionResponse(await response.json());
  if (receipt.case_public_id !== caseId) {
    throw new Error("Wallet Case deletion response does not match the request");
  }
  return receipt;
}

export async function getWalletCaseActivity(
  caseId: string,
  query: WalletCaseActivityQuery,
  signal?: AbortSignal,
): Promise<WalletCaseActivityResponse> {
  assertPublicId(caseId, "Wallet Case id");
  if (query.snapshot !== null) assertPublicId(query.snapshot, "Wallet Case snapshot id");
  if (!Number.isInteger(query.limit) || query.limit < 1 || query.limit > 100) {
    throw new Error("Wallet Case Activity limit must be between 1 and 100");
  }
  if (query.cursor !== null && query.cursor !== undefined && (!query.cursor || query.cursor.length > 1024)) {
    throw new Error("Wallet Case Activity cursor is invalid");
  }
  if (query.cursor && query.snapshot === null) {
    throw new Error("Wallet Case Activity pagination requires a pinned snapshot");
  }
  assertActivityChoices(query.kinds, ACTIVITY_KINDS, "kind");
  assertActivityChoices(query.directions, ACTIVITY_DIRECTIONS, "direction");
  assertActivityChoices(query.outcomes, ACTIVITY_OUTCOMES, "outcome");
  assertActivityChoices(query.data_origins, ACTIVITY_ORIGINS, "data origin");
  if (query.sort !== "newest" && query.sort !== "oldest") throw new Error("Wallet Case Activity sort is invalid");
  if ((query.from_at === null) !== (query.to_at === null)) {
    throw new Error("Wallet Case Activity period must include both bounds");
  }
  if (query.from_at !== null && query.to_at !== null) {
    const fromInstant = parseRfc3339Instant(query.from_at, { requireUtc: true, maximumFractionDigits: 6 });
    const toInstant = parseRfc3339Instant(query.to_at, { requireUtc: true, maximumFractionDigits: 6 });
    if (
      fromInstant === null || toInstant === null || fromInstant >= toInstant
    ) throw new Error("Wallet Case Activity period is invalid");
  }
  if (query.asset_id !== null && !isWalletCaseAssetPublicId(query.asset_id)) {
    throw new Error("Wallet Case Activity asset id is invalid");
  }
  if (query.protocol_id !== null && !(CASE_ACTIVITY_PROTOCOL_IDS as readonly string[]).includes(query.protocol_id)) {
    throw new Error("Wallet Case Activity protocol id is not recognized");
  }
  if (query.counterparty !== null && !isCanonicalRawTonAddress(query.counterparty)) {
    throw new Error("Wallet Case Activity counterparty is not canonical");
  }
  const requestQuery: WalletCaseActivityQuery = {
    ...query,
    ...canonicalizeCaseActivityFilters(query),
  };
  const params = new URLSearchParams();
  if (requestQuery.snapshot) params.set("snapshot", requestQuery.snapshot);
  params.set("limit", String(requestQuery.limit));
  if (requestQuery.cursor) params.set("cursor", requestQuery.cursor);
  requestQuery.kinds.forEach((value) => params.append("kind", value));
  requestQuery.directions.forEach((value) => params.append("direction", value));
  requestQuery.outcomes.forEach((value) => params.append("outcome", value));
  if (requestQuery.from_at) params.set("from_at", requestQuery.from_at);
  if (requestQuery.to_at) params.set("to_at", requestQuery.to_at);
  if (requestQuery.asset_id) params.set("asset_id", requestQuery.asset_id);
  if (requestQuery.protocol_id) params.set("protocol_id", requestQuery.protocol_id);
  if (requestQuery.counterparty) params.set("counterparty", requestQuery.counterparty);
  requestQuery.data_origins.forEach((value) => params.append("data_origin", value));
  params.set("sort", requestQuery.sort);
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/activity?${params}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) throw await walletCaseResponseError(response, "Wallet Case Activity read failed");
  const result = parseWalletCaseActivityResponse(await response.json());
  if (result.case_public_id !== caseId) {
    throw new Error("Wallet Case Activity response does not match the requested case id");
  }
  if (requestQuery.snapshot !== null && result.snapshot?.public_id !== requestQuery.snapshot) {
    throw new Error("Wallet Case Activity response does not match the requested snapshot id");
  }
  const expectedFilters = {
    kinds: requestQuery.kinds,
    directions: requestQuery.directions,
    outcomes: requestQuery.outcomes,
    from_at: requestQuery.from_at,
    to_at: requestQuery.to_at,
    asset_id: requestQuery.asset_id,
    protocol_id: requestQuery.protocol_id,
    counterparty: requestQuery.counterparty,
    data_origins: requestQuery.data_origins,
    sort: requestQuery.sort,
  };
  if (!activityFiltersMatch(result.filters, expectedFilters)) {
    throw new Error("Wallet Case Activity response filters do not match the request");
  }
  return result;
}

function assertActivityChoices<T extends string>(
  values: T[],
  allowed: readonly T[],
  label: string,
): void {
  if (
    values.length > allowed.length || new Set(values).size !== values.length ||
    values.some((value) => !allowed.includes(value))
  ) throw new Error(`Wallet Case Activity ${label} filters are invalid`);
}

function activityFiltersMatch(
  actual: WalletCaseActivityResponse["filters"],
  expected: WalletCaseActivityResponse["filters"],
): boolean {
  const sameInstant = (left: string | null, right: string | null) =>
    left === right || (
      left !== null && right !== null &&
      activityInstantNanoseconds(left) === activityInstantNanoseconds(right)
    );
  return (
    JSON.stringify(actual.kinds) === JSON.stringify(expected.kinds) &&
    JSON.stringify(actual.directions) === JSON.stringify(expected.directions) &&
    JSON.stringify(actual.outcomes) === JSON.stringify(expected.outcomes) &&
    sameInstant(actual.from_at, expected.from_at) && sameInstant(actual.to_at, expected.to_at) &&
    actual.asset_id === expected.asset_id && actual.protocol_id === expected.protocol_id &&
    actual.counterparty === expected.counterparty &&
    JSON.stringify(actual.data_origins) === JSON.stringify(expected.data_origins) &&
    actual.sort === expected.sort
  );
}

function activityInstantNanoseconds(value: string): bigint {
  const parsed = parseRfc3339Instant(value, { requireUtc: true, maximumFractionDigits: 6 });
  if (parsed === null) throw new Error("Wallet Case Activity timestamp is invalid");
  return parsed;
}

export async function getWalletCaseActivityDetail(
  caseId: string,
  snapshotId: string,
  activityId: string,
  signal?: AbortSignal,
): Promise<WalletCaseActivityDetailResponse> {
  assertPublicId(caseId, "Wallet Case id");
  assertPublicId(snapshotId, "Wallet Case snapshot id");
  if (!isWalletCaseActivityPublicId(activityId)) throw new Error("Wallet Case Activity id is invalid");
  const params = new URLSearchParams({ snapshot: snapshotId });
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/activity/${encodeURIComponent(activityId)}?${params}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) throw await walletCaseResponseError(response, "Wallet Case Activity detail failed");
  const result = parseWalletCaseActivityDetailResponse(await response.json());
  if (
    result.case_public_id !== caseId ||
    result.snapshot_public_id !== snapshotId ||
    result.item.public_id !== activityId
  ) {
    throw new Error("Wallet Case Activity detail does not match the requested resource");
  }
  return result;
}

export async function createWalletCaseSync(
  caseId: string,
  request: WalletCaseSyncRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<WalletCaseSync> {
  assertPublicId(caseId, "Wallet Case id");
  assertPublicId(idempotencyKey, "Wallet Case sync idempotency key");
  assertWalletCaseSyncRequest(request);
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/syncs`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify(request),
      signal,
    },
  );
  if (response.status !== 202) {
    throw await walletCaseResponseError(response, "Wallet Case sync failed");
  }
  const sync = bindSyncToRequest(await response.json(), caseId);
  assertSyncMatchesRequest(sync, request);
  return sync;
}

export async function getWalletCaseSync(
  caseId: string,
  syncId: string,
  signal?: AbortSignal,
): Promise<WalletCaseSync> {
  assertPublicId(caseId, "Wallet Case id");
  assertPublicId(syncId, "Wallet Case sync id");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/syncs/${encodeURIComponent(syncId)}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(response, "Wallet Case sync read failed");
  }
  const sync = bindSyncToRequest(await response.json(), caseId);
  if (sync.public_id !== syncId) {
    throw new Error("Wallet Case sync response does not match the requested sync id");
  }
  return sync;
}

export async function getWalletCaseSyncManifest(
  caseId: string,
  syncId: string,
  signal?: AbortSignal,
): Promise<WalletCaseSyncManifestResponse> {
  assertPublicId(caseId, "Wallet Case id");
  assertPublicId(syncId, "Wallet Case sync id");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/syncs/${encodeURIComponent(syncId)}/manifest`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case acquisition manifest read failed",
    );
  }
  const manifest = parseWalletCaseSyncManifestResponse(await response.json());
  if (
    manifest.document.case_public_id !== caseId ||
    manifest.document.sync_public_id !== syncId
  ) {
    throw new Error("Wallet Case acquisition manifest does not match the requested sync");
  }
  return manifest;
}

export async function getWalletCaseStreamCheckpoints(
  caseId: string,
  signal?: AbortSignal,
): Promise<WalletCaseStreamCheckpointCatalogResponse> {
  assertPublicId(caseId, "Wallet Case id");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/stream-checkpoints`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case stream checkpoint read failed",
    );
  }
  const catalog = parseWalletCaseStreamCheckpointCatalog(await response.json());
  if (catalog.case_public_id !== caseId) {
    throw new Error("Wallet Case stream checkpoint catalog does not match the request");
  }
  return catalog;
}

export async function getWalletCaseStreamCheckpoint(
  caseId: string,
  checkpointId: string,
  signal?: AbortSignal,
): Promise<WalletCaseStreamCheckpointDetailResponse> {
  assertPublicId(caseId, "Wallet Case id");
  assertCheckpointId(checkpointId);
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/stream-checkpoints/${encodeURIComponent(checkpointId)}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case stream checkpoint detail read failed",
    );
  }
  const detail = parseWalletCaseStreamCheckpointDetail(await response.json());
  if (
    detail.document.case_public_id !== caseId ||
    detail.checkpoint.public_id !== checkpointId
  ) {
    throw new Error("Wallet Case stream checkpoint detail does not match the request");
  }
  return detail;
}

export async function getWalletCaseStreamCheckpointChain(
  caseId: string,
  checkpointId: string,
  signal?: AbortSignal,
): Promise<WalletCaseStreamCheckpointChainResponse> {
  assertPublicId(caseId, "Wallet Case id");
  assertCheckpointId(checkpointId);
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/stream-checkpoints/${encodeURIComponent(checkpointId)}/chain`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case checkpoint chain read failed",
    );
  }
  const chain = parseWalletCaseStreamCheckpointChain(await response.json());
  if (
    chain.document.case_public_id !== caseId ||
    chain.document.tip_checkpoint_public_id !== checkpointId
  ) {
    throw new Error("Wallet Case checkpoint chain does not match the request");
  }
  return chain;
}

export async function getWalletCaseCheckpointContinuationPlan(
  caseId: string,
  signal?: AbortSignal,
): Promise<WalletCaseCheckpointContinuationPlanResponse> {
  assertPublicId(caseId, "Wallet Case id");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/stream-checkpoints/continuation-plan`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case checkpoint continuation plan read failed",
    );
  }
  const plan = parseWalletCaseCheckpointContinuationPlan(await response.json());
  if (plan.document.case_public_id !== caseId) {
    throw new Error("Wallet Case checkpoint continuation plan does not match the request");
  }
  return plan;
}

export async function getWalletCaseCheckpointContinuationReceipt(
  caseId: string,
  syncId: string,
  signal?: AbortSignal,
): Promise<WalletCaseCheckpointContinuationReceiptResponse> {
  assertPublicId(caseId, "Wallet Case id");
  assertPublicId(syncId, "Wallet Case sync id");
  const response = await fetch(
    (
      `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/syncs/` +
      `${encodeURIComponent(syncId)}/continuation-receipt`
    ),
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case continuation receipt read failed",
    );
  }
  const receipt = parseWalletCaseCheckpointContinuationReceipt(
    await response.json(),
  );
  if (
    receipt.document.case_public_id !== caseId ||
    receipt.document.sync_public_id !== syncId ||
    receipt.receipt.sync_public_id !== syncId
  ) {
    throw new Error("Wallet Case continuation receipt does not match the request");
  }
  return receipt;
}

export async function getWalletCaseStreamCheckpointHistory({
  caseId,
  limit = 20,
  cursor,
  signal,
}: {
  caseId: string;
  limit?: number;
  cursor?: string;
  signal?: AbortSignal;
}): Promise<WalletCaseStreamCheckpointHistoryResponse> {
  assertPublicId(caseId, "Wallet Case id");
  if (!Number.isInteger(limit) || limit < 1 || limit > 50) {
    throw new Error("Wallet Case checkpoint history limit must be from 1 through 50");
  }
  if (cursor !== undefined && (!cursor || cursor.length > 1024)) {
    throw new Error("Wallet Case checkpoint history cursor is invalid");
  }
  const query = new URLSearchParams({ limit: String(limit) });
  if (cursor !== undefined) query.set("cursor", cursor);
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/stream-checkpoints/history?${query}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case checkpoint history read failed",
    );
  }
  const history = parseWalletCaseStreamCheckpointHistory(await response.json());
  if (
    history.case_public_id !== caseId ||
    history.page.limit !== limit
  ) {
    throw new Error("Wallet Case checkpoint history does not match the request");
  }
  return history;
}

export async function resumeWalletCaseStreamCheckpoint(
  caseId: string,
  checkpointId: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<WalletCaseSync> {
  assertPublicId(caseId, "Wallet Case id");
  assertCheckpointId(checkpointId);
  assertPublicId(idempotencyKey, "Wallet Case sync idempotency key");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/stream-checkpoints/${encodeURIComponent(checkpointId)}/resume`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Idempotency-Key": idempotencyKey },
      signal,
    },
  );
  if (response.status !== 202) {
    throw await walletCaseResponseError(response, "Wallet Case checkpoint resume failed");
  }
  const sync = bindSyncToRequest(await response.json(), caseId);
  if (
    sync.requested_scope.mode !== "resume" ||
    sync.requested_scope.source_checkpoint_public_id !== checkpointId ||
    sync.requested_scope.base_snapshot_public_id === null
  ) {
    throw new Error("Wallet Case checkpoint resume response does not match the request");
  }
  return sync;
}

export async function resumeWalletCaseContinuationPlan(
  caseId: string,
  continuationPlanId: string,
  checkpointId: string,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<WalletCaseSync> {
  assertPublicId(caseId, "Wallet Case id");
  assertContinuationPlanId(continuationPlanId);
  assertCheckpointId(checkpointId);
  assertPublicId(idempotencyKey, "Wallet Case sync idempotency key");
  const response = await fetch(
    (
      `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}` +
      "/stream-checkpoints/continuation-plan/" +
      `${encodeURIComponent(continuationPlanId)}/` +
      `${encodeURIComponent(checkpointId)}/resume`
    ),
    {
      method: "POST",
      cache: "no-store",
      headers: { "Idempotency-Key": idempotencyKey },
      signal,
    },
  );
  if (response.status !== 202) {
    throw await walletCaseResponseError(
      response,
      "Wallet Case continuation plan resume failed",
    );
  }
  const sync = bindSyncToRequest(await response.json(), caseId);
  if (
    sync.requested_scope.mode !== "resume" ||
    sync.requested_scope.continuation_plan_public_id !== continuationPlanId ||
    sync.requested_scope.source_checkpoint_public_id !== checkpointId ||
    sync.requested_scope.base_snapshot_public_id === null
  ) {
    throw new Error("Wallet Case continuation plan resume response does not match the request");
  }
  return sync;
}

export async function cancelWalletCaseSync(
  caseId: string,
  syncId: string,
  signal?: AbortSignal,
): Promise<WalletCaseSync> {
  assertPublicId(caseId, "Wallet Case id");
  assertPublicId(syncId, "Wallet Case sync id");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/syncs/${encodeURIComponent(syncId)}/cancel`,
    { method: "POST", cache: "no-store", signal },
  );
  if (response.status !== 200 && response.status !== 202) {
    throw await walletCaseResponseError(response, "Wallet Case sync cancellation failed");
  }
  const sync = bindSyncToRequest(await response.json(), caseId);
  if (sync.public_id !== syncId) {
    throw new Error("Wallet Case sync response does not match the cancelled sync id");
  }
  return sync;
}

function bindSyncToRequest(value: unknown, caseId: string): WalletCaseSync {
  const sync = parseWalletCaseSync(value);
  if (sync.case_public_id !== caseId) {
    throw new Error("Wallet Case sync response does not match the requested case id");
  }
  return sync;
}

function assertWalletCaseSyncRequest(request: WalletCaseSyncRequest): void {
  const allowedSurfaces = new Set([
    "transfers",
    "transactions",
    "swaps",
    "balances",
    "jettons",
  ]);
  if (
    (request.mode !== "bounded" && request.mode !== "incremental") ||
    request.surfaces.length === 0 ||
    new Set(request.surfaces).size !== request.surfaces.length ||
    request.surfaces.some((surface) => !allowedSurfaces.has(surface))
  ) {
    throw new Error("Wallet Case sync request is invalid");
  }
  if (request.mode === "incremental") {
    if (
      request.time_window !== "24h" ||
      request.custom_start !== undefined ||
      request.custom_end !== undefined
    ) {
      throw new Error("Incremental Wallet Case refresh cannot define time bounds");
    }
    return;
  }
  if (request.time_window === "custom") {
    const start = parseRfc3339Instant(request.custom_start);
    const end = parseRfc3339Instant(request.custom_end);
    if (start === null || end === null || start >= end) {
      throw new Error("Custom Wallet Case sync bounds are invalid");
    }
  } else if (request.custom_start !== undefined || request.custom_end !== undefined) {
    throw new Error("Wallet Case sync bounds require a custom window");
  }
}

function assertSyncMatchesRequest(
  sync: WalletCaseSync,
  request: WalletCaseSyncRequest,
): void {
  if (
    sync.requested_scope.mode !== request.mode ||
    JSON.stringify(sync.requested_scope.surfaces) !== JSON.stringify(request.surfaces)
  ) {
    throw new Error("Wallet Case sync response does not match the requested scope");
  }
  if (request.mode === "incremental") {
    if (
      sync.requested_scope.time_window !== "custom" ||
      sync.requested_scope.base_snapshot_public_id === null
    ) {
      throw new Error("Wallet Case incremental response is missing its base snapshot");
    }
    return;
  }
  if (sync.requested_scope.time_window !== request.time_window) {
    throw new Error("Wallet Case sync response does not match the requested window");
  }
  if (request.time_window === "custom") {
    const requestedStart = parseRfc3339Instant(request.custom_start);
    const requestedEnd = parseRfc3339Instant(request.custom_end);
    if (
      requestedStart !== parseRfc3339Instant(sync.requested_scope.start_at) ||
      requestedEnd !== parseRfc3339Instant(sync.requested_scope.end_at)
    ) {
      throw new Error("Wallet Case sync response does not match the requested bounds");
    }
  }
}

function assertPublicId(value: string, label: string): void {
  if (!UUID_V4.test(value)) throw new Error(`${label} must be a canonical UUIDv4`);
}

function assertCheckpointId(value: string): void {
  if (!CHECKPOINT_ID.test(value)) {
    throw new Error("Wallet Case stream checkpoint id is invalid");
  }
}

function assertContinuationPlanId(value: string): void {
  if (!CONTINUATION_PLAN_ID.test(value)) {
    throw new Error("Wallet Case continuation plan id is invalid");
  }
}

async function walletCaseResponseError(
  response: Response,
  fallback: string,
): Promise<WalletCaseApiError> {
  let message = `${fallback} (${response.status})`;
  let code: string | null = null;
  let retryable = response.status === 429 || response.status >= 500;
  let activeSyncPublicId: string | null = null;
  let currentMetadataVersion: number | null = null;

  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail) {
      message = detail;
    } else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const structured = detail as StructuredApiDetail;
      const safeMessage = typeof structured.message_safe === "string"
        ? structured.message_safe
        : structured.message;
      if (typeof safeMessage === "string" && safeMessage) message = safeMessage;
      if (typeof structured.code === "string" && structured.code) code = structured.code;
      if (typeof structured.retryable === "boolean") retryable = structured.retryable;
      if (
        typeof structured.active_sync_public_id === "string" &&
        UUID_V4.test(structured.active_sync_public_id)
      ) {
        activeSyncPublicId = structured.active_sync_public_id;
      }
      if (
        Number.isSafeInteger(structured.current_metadata_version) &&
        (structured.current_metadata_version as number) > 0
      ) {
        currentMetadataVersion = structured.current_metadata_version as number;
      }
    } else if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (typeof first?.msg === "string" && first.msg) message = first.msg;
    }
  } catch {
    // Keep the bounded fallback for non-JSON failures.
  }

  return new WalletCaseApiError({
    message,
    status: response.status,
    code,
    retryable,
    retryAfterMs: retryAfterMilliseconds(response.headers.get("Retry-After")),
    activeSyncPublicId,
    currentMetadataVersion,
  });
}

function retryAfterMilliseconds(value: string | null): number | null {
  if (!value) return null;
  if (/^[0-9]+$/.test(value)) return Number(value) * 1000;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, timestamp - Date.now());
}
