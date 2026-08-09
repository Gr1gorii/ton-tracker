import { API_BASE } from "./apiBase";
import {
  parseWalletCase,
  parseWalletCaseListResponse,
  parseWalletCaseSync,
  parseWalletCaseUpsertResponse,
  type WalletCase,
  type WalletCaseCreateRequest,
  type WalletCaseListResponse,
  type WalletCaseSync,
  type WalletCaseSyncRequest,
  type WalletCaseUpsertResponse,
} from "./walletCase";

const UUID_V4 =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

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
