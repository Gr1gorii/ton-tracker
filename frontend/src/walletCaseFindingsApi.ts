import { API_BASE } from "./apiBase";
import { isWalletCaseSnapshotPublicId } from "./walletCaseActivity";
import {
  parseWalletCaseFindingsResponse,
  type WalletCaseFindingsResponse,
} from "./walletCaseFindings";

export class WalletCaseFindingsApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;

  constructor(message: string, status: number, code: string | null, retryable: boolean) {
    super(message);
    this.name = "WalletCaseFindingsApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

export async function getWalletCaseFindings(
  caseId: string,
  snapshotId: string | null,
  signal?: AbortSignal,
): Promise<WalletCaseFindingsResponse> {
  assertUuid(caseId, "Wallet Case ID");
  if (snapshotId !== null) assertUuid(snapshotId, "Findings snapshot ID");
  const base = `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/findings`;
  const url = snapshotId === null
    ? base
    : `${base}?snapshot=${encodeURIComponent(snapshotId)}`;
  const response = await fetch(url, { cache: "no-store", signal });
  if (!response.ok) throw await findingsResponseError(response);
  const parsed = parseWalletCaseFindingsResponse(await response.json());
  if (
    parsed.case_public_id !== caseId
    || (snapshotId !== null && parsed.snapshot_public_id !== snapshotId)
  ) {
    throw new Error("Wallet Case Findings response does not match the requested scope");
  }
  return parsed;
}

function assertUuid(value: string, label: string): void {
  if (!isWalletCaseSnapshotPublicId(value)) throw new Error(`${label} must be a canonical UUIDv4`);
}

async function findingsResponseError(response: Response): Promise<WalletCaseFindingsApiError> {
  let message = `Wallet Case Findings is unavailable (${response.status})`;
  let code: string | null = null;
  let retryable = response.status === 429 || response.status >= 500;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail.trim()) message = detail;
    if (detail && typeof detail === "object") {
      if (typeof detail.message_safe === "string" && detail.message_safe.trim()) message = detail.message_safe;
      if (typeof detail.code === "string" && /^[a-z][a-z0-9_]{0,63}$/.test(detail.code)) code = detail.code;
      if (typeof detail.retryable === "boolean") retryable = detail.retryable;
    }
  } catch {
    // The status-based safe fallback deliberately ignores malformed bodies.
  }
  return new WalletCaseFindingsApiError(message, response.status, code, retryable);
}
