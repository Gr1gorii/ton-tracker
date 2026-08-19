import { API_BASE } from "./apiBase";
import { isWalletCaseSnapshotPublicId } from "./walletCaseActivity";
import {
  parseWalletCaseReportResponse,
  type WalletCaseReportResponse,
} from "./walletCaseReport";

export class WalletCaseReportApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly retryable: boolean;

  constructor(message: string, status: number, code: string | null, retryable: boolean) {
    super(message);
    this.name = "WalletCaseReportApiError";
    this.status = status;
    this.code = code;
    this.retryable = retryable;
  }
}

export async function getWalletCaseReport(
  caseId: string,
  snapshotId: string | null,
  signal?: AbortSignal,
): Promise<WalletCaseReportResponse> {
  assertUuid(caseId, "Wallet Case ID");
  if (snapshotId !== null) assertUuid(snapshotId, "Report snapshot ID");
  const response = await fetch(walletCaseReportUrl(caseId, snapshotId), { cache: "no-store", signal });
  if (!response.ok) throw await reportResponseError(response);
  const parsed = parseWalletCaseReportResponse(await response.json());
  if (parsed.case_public_id !== caseId || (snapshotId !== null && parsed.snapshot_public_id !== snapshotId)) {
    throw new Error("Wallet Case report response does not match the requested scope");
  }
  return parsed;
}

export function walletCaseReportExportUrl(caseId: string, snapshotId: string): string {
  assertUuid(caseId, "Wallet Case ID");
  assertUuid(snapshotId, "Report snapshot ID");
  return `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/report/export.json?snapshot=${encodeURIComponent(snapshotId)}`;
}

function walletCaseReportUrl(caseId: string, snapshotId: string | null): string {
  const base = `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/report`;
  return snapshotId === null ? base : `${base}?snapshot=${encodeURIComponent(snapshotId)}`;
}

function assertUuid(value: string, label: string): void {
  if (!isWalletCaseSnapshotPublicId(value)) throw new Error(`${label} must be a canonical UUIDv4`);
}

async function reportResponseError(response: Response): Promise<WalletCaseReportApiError> {
  let message = `Wallet Case report is unavailable (${response.status})`;
  let code: string | null = null;
  let retryable = response.status === 429 || response.status >= 500;
  try {
    const body = await response.json();
    const detail = body?.detail;
    if (typeof detail === "string" && detail.trim()) message = detail;
    if (detail && typeof detail === "object" && !Array.isArray(detail)) {
      if (typeof detail.message_safe === "string" && detail.message_safe.trim()) message = detail.message_safe;
      if (typeof detail.code === "string" && detail.code.trim()) code = detail.code;
      if (typeof detail.retryable === "boolean") retryable = detail.retryable;
    }
  } catch {
    // Keep a bounded local message when an intermediary returns a non-JSON body.
  }
  return new WalletCaseReportApiError(message, response.status, code, retryable);
}
