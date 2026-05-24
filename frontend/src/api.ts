import type { AnalysisResult, AnalyzeRequest } from "./types";

// API base URL. Override with VITE_API_BASE at build/dev time.
export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "http://localhost:8000";

export async function analyze(
  req: AnalyzeRequest,
): Promise<AnalysisResult> {
  const res = await fetch(`${API_BASE}/api/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new Error(detail);
  }

  return (await res.json()) as AnalysisResult;
}

// Build a download URL for the export placeholders.
export function exportUrl(
  format: "csv" | "json",
  poolUrl: string,
  timeWindow: string,
): string {
  const params = new URLSearchParams({
    pool_url: poolUrl,
    time_window: timeWindow,
  });
  return `${API_BASE}/api/export/${format}?${params.toString()}`;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    return res.ok;
  } catch {
    return false;
  }
}
