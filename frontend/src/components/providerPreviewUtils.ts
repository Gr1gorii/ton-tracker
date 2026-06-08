export interface ProviderPreviewRunUpdate {
  status: "idle" | "running" | "success" | "error";
  message: string;
  accountAddress?: string;
  limit?: string;
}

export interface AccountPreviewRequestSnapshot {
  accountAddress: string;
  limit: string;
  requestedAt: string;
}

export interface LimitPreviewRequestSnapshot {
  limit: string;
  requestedAt: string;
}

export function displayPreviewValue(
  value: string | number | boolean | null | undefined,
): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

export function clampPreviewLimit(value: string): number | null {
  if (!value.trim()) return 10;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.min(100, Math.max(1, Math.trunc(parsed)));
}

export function previewLimitLabel(value: string): string {
  const safeLimit = clampPreviewLimit(value);
  if (safeLimit === null) return value.trim() || "Invalid";
  return String(safeLimit);
}

export function previewAccountLabel(value: string): string {
  return value.trim() || "-";
}

export function formatPreviewRequestedAt(date: Date): string {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}
