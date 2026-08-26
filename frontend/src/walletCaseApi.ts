import { API_BASE } from "./apiBase";
import {
  parseWalletCase,
  parseWalletCaseDeletionResponse,
  parseWalletCaseListResponse,
  parseWalletCaseSync,
  parseWalletCaseUpsertResponse,
  type WalletCase,
  type WalletCaseCreateRequest,
  type WalletCaseDeletionResponse,
  type WalletCaseListResponse,
  type WalletCaseSync,
  type WalletCaseSyncRequest,
  type WalletCaseUpsertResponse,
} from "./walletCase";
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
}

export class WalletCaseApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;
  readonly retryAfterMs: number | null;
  readonly activeSyncPublicId: string | null;

  constructor({
    message,
    status,
    code = null,
    retryable = false,
    retryAfterMs = null,
    activeSyncPublicId = null,
  }: {
    message: string;
    status: number;
    code?: string | null;
    retryable?: boolean;
    retryAfterMs?: number | null;
    activeSyncPublicId?: string | null;
  }) {
    super(message);
    this.name = "WalletCaseApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.retryAfterMs = retryAfterMs;
    this.activeSyncPublicId = activeSyncPublicId;
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

export async function listWalletCases(
  limit = 20,
  signal?: AbortSignal,
): Promise<WalletCaseListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  const response = await fetch(`${API_BASE}/api/v1/cases?${params}`, {
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    throw await walletCaseResponseError(response, "Wallet Case list failed");
  }
  return parseWalletCaseListResponse(await response.json());
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
  return bindSyncToRequest(await response.json(), caseId);
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

function assertPublicId(value: string, label: string): void {
  if (!UUID_V4.test(value)) throw new Error(`${label} must be a canonical UUIDv4`);
}

async function walletCaseResponseError(
  response: Response,
  fallback: string,
): Promise<WalletCaseApiError> {
  let message = `${fallback} (${response.status})`;
  let code: string | null = null;
  let retryable = response.status === 429 || response.status >= 500;
  let activeSyncPublicId: string | null = null;

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
  });
}

function retryAfterMilliseconds(value: string | null): number | null {
  if (!value) return null;
  if (/^[0-9]+$/.test(value)) return Number(value) * 1000;
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return null;
  return Math.max(0, timestamp - Date.now());
}
