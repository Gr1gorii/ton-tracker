import { API_BASE } from "./apiBase";
import {
  parseWalletCaseEvidenceCatalog,
  parseWalletCaseEvidenceVerification,
  type WalletCaseEvidenceCatalog,
  type WalletCaseEvidenceVerification,
  type WalletCaseEvidenceVerificationRequest,
} from "./walletCaseEvidence";
import {
  isWalletCaseActivityPublicId,
  isWalletCaseSnapshotPublicId,
} from "./walletCaseActivity";

interface StructuredErrorDetail {
  code?: unknown;
  message_safe?: unknown;
  retryable?: unknown;
  active_verification_public_id?: unknown;
}

export class WalletCaseEvidenceApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;
  readonly retryAfterMs: number | null;
  readonly activeVerificationPublicId: string | null;

  constructor({
    message,
    status,
    code,
    retryable,
    retryAfterMs,
    activeVerificationPublicId = null,
  }: {
    message: string;
    status: number;
    code: string | null;
    retryable: boolean;
    retryAfterMs: number | null;
    activeVerificationPublicId?: string | null;
  }) {
    super(message);
    this.name = "WalletCaseEvidenceApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
    this.retryAfterMs = retryAfterMs;
    this.activeVerificationPublicId = activeVerificationPublicId;
  }
}

export async function getWalletCaseEvidence(
  caseId: string,
  snapshotId: string | null,
  signal?: AbortSignal,
): Promise<WalletCaseEvidenceCatalog> {
  assertUuid(caseId, "Wallet Case ID");
  if (snapshotId !== null) assertUuid(snapshotId, "Evidence snapshot ID");
  const params = new URLSearchParams();
  if (snapshotId !== null) params.set("snapshot", snapshotId);
  const suffix = params.size ? `?${params}` : "";
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/evidence${suffix}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) throw await evidenceResponseError(response, "Wallet Case Evidence is unavailable");
  const catalog = parseWalletCaseEvidenceCatalog(await response.json());
  if (catalog.case_public_id !== caseId) throw new Error("Evidence response does not match the requested Wallet Case");
  if (snapshotId !== null && catalog.snapshot?.public_id !== snapshotId) {
    throw new Error("Evidence response does not match the requested snapshot");
  }
  return catalog;
}

export async function createWalletCaseEvidenceVerification(
  caseId: string,
  request: WalletCaseEvidenceVerificationRequest,
  idempotencyKey: string,
  signal?: AbortSignal,
): Promise<WalletCaseEvidenceVerification> {
  assertUuid(caseId, "Wallet Case ID");
  assertRequest(request);
  assertUuid(idempotencyKey, "Evidence idempotency key");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/evidence/verifications`,
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
  if (response.status !== 202) throw await evidenceResponseError(response, "Evidence verification could not start");
  return bindVerification(await response.json(), caseId, request.snapshot_public_id, request.activity_public_id);
}

export async function getWalletCaseEvidenceVerification(
  caseId: string,
  verificationId: string,
  signal?: AbortSignal,
): Promise<WalletCaseEvidenceVerification> {
  assertUuid(caseId, "Wallet Case ID");
  assertUuid(verificationId, "Evidence verification ID");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/evidence/verifications/${encodeURIComponent(verificationId)}`,
    { cache: "no-store", signal },
  );
  if (!response.ok) throw await evidenceResponseError(response, "Evidence verification is unavailable");
  const verification = parseWalletCaseEvidenceVerification(await response.json());
  if (verification.case_public_id !== caseId || verification.public_id !== verificationId) {
    throw new Error("Evidence verification response does not match the requested resource");
  }
  return verification;
}

export async function cancelWalletCaseEvidenceVerification(
  caseId: string,
  verificationId: string,
  signal?: AbortSignal,
): Promise<WalletCaseEvidenceVerification> {
  assertUuid(caseId, "Wallet Case ID");
  assertUuid(verificationId, "Evidence verification ID");
  const response = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/evidence/verifications/${encodeURIComponent(verificationId)}/cancel`,
    { method: "POST", cache: "no-store", signal },
  );
  if (response.status !== 200 && response.status !== 202) {
    throw await evidenceResponseError(response, "Evidence verification cancellation failed");
  }
  const verification = parseWalletCaseEvidenceVerification(await response.json());
  if (verification.case_public_id !== caseId || verification.public_id !== verificationId) {
    throw new Error("Cancelled Evidence verification does not match the requested resource");
  }
  return verification;
}

function bindVerification(
  value: unknown,
  caseId: string,
  snapshotId: string,
  activityId: string,
): WalletCaseEvidenceVerification {
  const verification = parseWalletCaseEvidenceVerification(value);
  if (
    verification.case_public_id !== caseId ||
    verification.snapshot_public_id !== snapshotId ||
    verification.activity_public_id !== activityId
  ) throw new Error("Evidence verification response does not match the requested scope");
  return verification;
}

function assertRequest(request: WalletCaseEvidenceVerificationRequest): void {
  assertUuid(request.snapshot_public_id, "Evidence snapshot ID");
  if (!isWalletCaseActivityPublicId(request.activity_public_id)) throw new Error("Evidence Activity ID is invalid");
  if (request.policy !== "transaction_inclusion_v1") throw new Error("Evidence verification policy is invalid");
}

function assertUuid(value: string, label: string): void {
  if (!isWalletCaseSnapshotPublicId(value)) throw new Error(`${label} must be a canonical UUIDv4`);
}

async function evidenceResponseError(response: Response, fallback: string): Promise<WalletCaseEvidenceApiError> {
  let message = `${fallback} (${response.status})`;
  let code: string | null = null;
  let retryable = response.status === 429 || response.status >= 500;
  let activeVerificationPublicId: string | null = null;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail.trim()) {
      message = detail;
    } else if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      const structured = detail as StructuredErrorDetail;
      if (typeof structured.message_safe === "string" && structured.message_safe.trim()) message = structured.message_safe;
      if (typeof structured.code === "string" && structured.code.trim()) code = structured.code;
      if (typeof structured.retryable === "boolean") retryable = structured.retryable;
      if (
        structured.active_verification_public_id !== undefined &&
        typeof structured.active_verification_public_id === "string" &&
        isWalletCaseSnapshotPublicId(structured.active_verification_public_id)
      ) activeVerificationPublicId = structured.active_verification_public_id;
    } else if (Array.isArray(detail) && typeof detail[0]?.msg === "string") {
      message = detail[0].msg;
    }
  } catch {
    // Retain the bounded fallback when an intermediary does not return JSON.
  }
  return new WalletCaseEvidenceApiError({
    message,
    status: response.status,
    code,
    retryable,
    retryAfterMs: retryAfterMilliseconds(response.headers.get("Retry-After")),
    activeVerificationPublicId,
  });
}

function retryAfterMilliseconds(value: string | null): number | null {
  if (!value) return null;
  if (/^[0-9]+$/.test(value)) return Number(value) * 1_000;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed - Date.now()) : null;
}
