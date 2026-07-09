import type {
  AnalysisResult,
  AnalyzeRequest,
  BitqueryAnalysisResponse,
  BitqueryPreviewResponse,
  BitqueryTokenTradesRequest,
  ImportedTradesAnalysisResponse,
  HistoricalPricesPreviewResponse,
  ImportPreviewRequest,
  ImportPreviewResponse,
  ProvidersStatus,
  StonfiPoolsPreviewResponse,
  TonapiAccountJettonsPreviewResponse,
  TonapiWalletIntelligencePreviewResponse,
  WalletClusterCompareResponse,
  WalletIngestionPreviewResponse,
  WalletIngestionRequest,
  WalletIngestionRunResponse,
  WalletRunPnlPreviewResponse,
  WalletRunSignalsResponse,
} from "./types";

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

export async function getProvidersStatus(): Promise<ProvidersStatus> {
  const res = await fetch(`${API_BASE}/api/providers/status`);
  if (!res.ok) {
    throw new Error(`Provider status request failed (${res.status})`);
  }
  return (await res.json()) as ProvidersStatus;
}

export async function previewImportedTrades(
  req: ImportPreviewRequest,
): Promise<ImportPreviewResponse> {
  const res = await fetch(`${API_BASE}/api/import/trades/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    let detail = `Import preview request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail) && body.detail.length > 0) {
        const first = body.detail[0];
        if (typeof first?.msg === "string") detail = first.msg;
      }
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new Error(detail);
  }

  return (await res.json()) as ImportPreviewResponse;
}

export async function analyzeImportedTrades(
  req: ImportPreviewRequest,
): Promise<ImportedTradesAnalysisResponse> {
  const res = await fetch(`${API_BASE}/api/import/trades/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    let detail = `Import analysis request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body && typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body?.detail) && body.detail.length > 0) {
        const first = body.detail[0];
        if (typeof first?.msg === "string") detail = first.msg;
      }
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new Error(detail);
  }

  return (await res.json()) as ImportedTradesAnalysisResponse;
}

export async function previewBitqueryTokenTrades(
  req: BitqueryTokenTradesRequest,
): Promise<BitqueryPreviewResponse> {
  const res = await fetch(`${API_BASE}/api/bitquery/token-trades/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Bitquery preview request failed"));
  }

  return (await res.json()) as BitqueryPreviewResponse;
}

export async function analyzeBitqueryTokenTrades(
  req: BitqueryTokenTradesRequest,
): Promise<BitqueryAnalysisResponse> {
  const res = await fetch(`${API_BASE}/api/bitquery/token-trades/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Bitquery analysis request failed"));
  }

  return (await res.json()) as BitqueryAnalysisResponse;
}

export async function previewStonfiPools(
  limit: number,
): Promise<StonfiPoolsPreviewResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE}/api/stonfi/pools/preview?${params}`);

  if (!res.ok) {
    throw new Error(await responseError(res, "STON.fi pools preview failed"));
  }

  return (await res.json()) as StonfiPoolsPreviewResponse;
}

export async function previewTonapiAccountJettons(
  accountAddress: string,
  limit: number,
): Promise<TonapiAccountJettonsPreviewResponse> {
  const params = new URLSearchParams({
    account_address: accountAddress,
    limit: String(limit),
  });
  const res = await fetch(
    `${API_BASE}/api/tonapi/account-jettons/preview?${params}`,
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "TonAPI account jettons preview failed"),
    );
  }

  return (await res.json()) as TonapiAccountJettonsPreviewResponse;
}

export async function previewTonapiWalletIntelligence(
  accountAddress: string,
  limit: number,
): Promise<TonapiWalletIntelligencePreviewResponse> {
  const params = new URLSearchParams({
    account_address: accountAddress,
    limit: String(limit),
  });
  const res = await fetch(
    `${API_BASE}/api/tonapi/wallet-intelligence/preview?${params}`,
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "TonAPI wallet intelligence preview failed"),
    );
  }

  return (await res.json()) as TonapiWalletIntelligencePreviewResponse;
}

export async function previewWalletIngestion(
  req: WalletIngestionRequest,
): Promise<WalletIngestionPreviewResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest/preview`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet ingestion preview failed"));
  }

  return (await res.json()) as WalletIngestionPreviewResponse;
}

export async function runWalletIngestion(
  req: WalletIngestionRequest,
): Promise<WalletIngestionRunResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet ingestion run failed"));
  }

  return (await res.json()) as WalletIngestionRunResponse;
}

export async function getWalletIngestionRun(
  runId: number,
): Promise<WalletIngestionRunResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest/${runId}`);

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet ingestion read failed"));
  }

  return (await res.json()) as WalletIngestionRunResponse;
}

export async function getWalletRunSignals(
  runId: number,
): Promise<WalletRunSignalsResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest/${runId}/signals`);

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet signals read failed"));
  }

  return (await res.json()) as WalletRunSignalsResponse;
}

export async function previewHistoricalPrices(
  token: string,
  start: string,
  end: string,
): Promise<HistoricalPricesPreviewResponse> {
  const params = new URLSearchParams({ token, start, end });
  const res = await fetch(
    `${API_BASE}/api/prices/historical/preview?${params.toString()}`,
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Historical prices preview failed"),
    );
  }

  return (await res.json()) as HistoricalPricesPreviewResponse;
}

export async function getWalletRunPnlPreview(
  runId: number,
  includeHistorical = false,
  includeUnrealized = false,
): Promise<WalletRunPnlPreviewResponse> {
  const params = new URLSearchParams();
  if (includeHistorical) params.set("include_historical", "true");
  if (includeUnrealized) params.set("include_unrealized", "true");
  const query = params.toString();
  const suffix = query ? `?${query}` : "";
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/pnl-preview${suffix}`,
  );

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet PnL preview read failed"));
  }

  return (await res.json()) as WalletRunPnlPreviewResponse;
}

export function walletRunPnlPreviewExportUrl(
  runId: number,
  includeHistorical = false,
): string {
  const suffix = includeHistorical ? "?include_historical=true" : "";
  return `${API_BASE}/api/wallets/ingest/${runId}/pnl-preview/export.json${suffix}`;
}

export function walletRunPnlPreviewCsvExportUrl(
  runId: number,
  includeHistorical = false,
): string {
  const suffix = includeHistorical ? "?include_historical=true" : "";
  return `${API_BASE}/api/wallets/ingest/${runId}/pnl-preview/export.csv${suffix}`;
}

export function walletRunSignalsExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/signals/export.json`;
}

export function walletRunSignalsCsvExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/signals/export.csv`;
}

export function walletRunExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/export.json`;
}

export function walletRunExportCsvUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/export.csv`;
}

export function walletClusterCompareExportUrl(runIds: number[]): string {
  const params = runIds.map((id) => `run_ids=${id}`).join("&");
  return `${API_BASE}/api/wallets/cluster/compare/export.json?${params}`;
}

export function walletClusterCompareCsvExportUrl(runIds: number[]): string {
  const params = runIds.map((id) => `run_ids=${id}`).join("&");
  return `${API_BASE}/api/wallets/cluster/compare/export.csv?${params}`;
}

export async function compareWalletRuns(
  runIds: number[],
): Promise<WalletClusterCompareResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/cluster/compare`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: runIds }),
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet cluster compare failed"));
  }

  return (await res.json()) as WalletClusterCompareResponse;
}

async function responseError(res: Response, fallback: string): Promise<string> {
  let detail = `${fallback} (${res.status})`;
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body?.detail) && body.detail.length > 0) {
      const first = body.detail[0];
      if (typeof first?.msg === "string") detail = first.msg;
    }
  } catch {
    // non-JSON error body; keep the generic message
  }
  return detail;
}

export async function checkHealth(): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/health`);
    return res.ok;
  } catch {
    return false;
  }
}
