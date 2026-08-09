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
  WalletHistoryReadinessRequest,
  WalletHistoryReadinessResponse,
  WalletIngestionPreviewResponse,
  WalletIngestionRequest,
  WalletIngestionRunResponse,
  WalletJettonContractVerificationCatalogResponse,
  WalletJettonContractVerificationResponse,
  WalletJettonPayloadObservationsResponse,
  WalletNativeActivityPnlReadinessResponse,
  WalletMultiAssetPnlReadinessResponse,
  WalletRunPnlPreviewResponse,
  WalletRunSignalsResponse,
  WalletTransactionInclusionCatalogResponse,
  WalletOwnershipChallengeResponse,
  WalletOwnershipProofRequest,
  WalletOwnershipProofResponse,
} from "./types";
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

// API base URL. Override with VITE_API_BASE at build/dev time.
export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  (import.meta.env.DEV ? "http://localhost:8000" : "");

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

export async function getProvidersStatus(signal?: AbortSignal): Promise<ProvidersStatus> {
  const res = await fetch(`${API_BASE}/api/providers/status`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    throw new Error(`Provider status request failed (${res.status})`);
  }
  return (await res.json()) as ProvidersStatus;
}

export async function createWalletCase(
  req: WalletCaseCreateRequest,
  signal?: AbortSignal,
): Promise<WalletCaseUpsertResponse> {
  const res = await fetch(`${API_BASE}/api/v1/cases`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });
  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet Case creation failed"));
  }
  return parseWalletCaseUpsertResponse(await res.json());
}

export async function listWalletCases(
  limit = 20,
  signal?: AbortSignal,
): Promise<WalletCaseListResponse> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE}/api/v1/cases?${params}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet Case list failed"));
  }
  return parseWalletCaseListResponse(await res.json());
}

export async function getWalletCase(
  caseId: string,
  signal?: AbortSignal,
): Promise<WalletCase> {
  const res = await fetch(`${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}`, {
    cache: "no-store",
    signal,
  });
  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet Case read failed"));
  }
  const walletCase = parseWalletCase(await res.json());
  if (walletCase.public_id !== caseId) {
    throw new Error("Wallet Case response does not match the requested case id");
  }
  return walletCase;
}

export async function createWalletCaseSync(
  caseId: string,
  req: WalletCaseSyncRequest,
  signal?: AbortSignal,
): Promise<WalletCaseSync> {
  const res = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/syncs`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
      signal,
    },
  );
  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet Case sync failed"));
  }
  return parseWalletCaseSync(await res.json());
}

export async function getWalletCaseSync(
  caseId: string,
  syncId: string,
  signal?: AbortSignal,
): Promise<WalletCaseSync> {
  const res = await fetch(
    `${API_BASE}/api/v1/cases/${encodeURIComponent(caseId)}/syncs/${encodeURIComponent(syncId)}`,
    { cache: "no-store", signal },
  );
  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet Case sync read failed"));
  }
  const sync = parseWalletCaseSync(await res.json());
  if (sync.public_id !== syncId) {
    throw new Error("Wallet Case sync response does not match the requested sync id");
  }
  return sync;
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
  signal?: AbortSignal,
): Promise<WalletIngestionPreviewResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest/preview`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet ingestion preview failed"));
  }

  return (await res.json()) as WalletIngestionPreviewResponse;
}

export async function runWalletIngestion(
  req: WalletIngestionRequest,
  signal?: AbortSignal,
): Promise<WalletIngestionRunResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet ingestion run failed"));
  }

  return (await res.json()) as WalletIngestionRunResponse;
}

export async function getWalletIngestionRun(
  runId: number,
  signal?: AbortSignal,
): Promise<WalletIngestionRunResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest/${runId}`, {
    cache: "no-store",
    signal,
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet ingestion read failed"));
  }

  return (await res.json()) as WalletIngestionRunResponse;
}

export async function getWalletIngestionRunCatalog(
  limit: number,
  signal?: AbortSignal,
): Promise<unknown> {
  const params = new URLSearchParams({ limit: String(limit) });
  const res = await fetch(`${API_BASE}/api/wallets/ingest?${params}`, {
    cache: "no-store",
    signal,
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet run catalog read failed"));
  }

  return await res.json();
}

export async function getWalletTransactionTraceEvidence(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence`,
    {
      cache: "no-store",
      signal,
    },
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Transaction trace evidence preview failed"),
    );
  }

  return await res.json();
}

export async function getPersistedWalletTransactionTraceEvidence(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<unknown | null> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence/persisted`,
    {
      cache: "no-store",
      signal,
    },
  );

  if (res.status === 404) {
    let detail = "Persisted transaction trace evidence read failed (404)";
    try {
      const body = await res.json();
      if (body?.detail === "Persisted trace evidence not found") return null;
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // A missing-resource response without the exact absence contract is an error.
    }
    throw new Error(detail);
  }
  if (!res.ok) {
    throw new Error(
      await responseError(res, "Persisted transaction trace evidence read failed"),
    );
  }

  return await res.json();
}

export async function persistWalletTransactionTraceEvidence(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence/persisted`,
    {
      method: "POST",
      cache: "no-store",
      signal,
    },
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Transaction trace evidence capture failed"),
    );
  }

  return await res.json();
}

export async function getWalletTransactionTraceBocVerification(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<unknown | null> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence/boc-verification`,
    { cache: "no-store", signal },
  );

  if (res.status === 404) {
    let detail = "Local transaction BOC verification read failed (404)";
    try {
      const body = await res.json();
      if (
        body?.detail === "Locally verified transaction BOC evidence not found"
      ) {
        return null;
      }
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Only the exact absence contract is converted to null.
    }
    throw new Error(detail);
  }
  if (!res.ok) {
    throw new Error(
      await responseError(res, "Local transaction BOC verification read failed"),
    );
  }
  return await res.json();
}

export async function verifyWalletTransactionTraceBocs(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<unknown> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence/boc-verification`,
    { method: "POST", cache: "no-store", signal },
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Local transaction BOC verification failed"),
    );
  }
  return await res.json();
}

export async function getWalletTransactionInclusionProofs(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<WalletTransactionInclusionCatalogResponse | null> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence/boc-verification/block-inclusion`,
    { cache: "no-store", signal },
  );

  if (res.status === 404) {
    let detail = "Transaction inclusion proof read failed (404)";
    try {
      const body = await res.json();
      if (body?.detail === "Transaction inclusion proofs not found") return null;
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      // Only the exact absence contract is converted to null.
    }
    throw new Error(detail);
  }
  if (!res.ok) {
    throw new Error(
      await responseError(res, "Transaction inclusion proof read failed"),
    );
  }
  return (await res.json()) as WalletTransactionInclusionCatalogResponse;
}

export async function proveWalletTransactionInclusion(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<WalletTransactionInclusionCatalogResponse> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence/boc-verification/block-inclusion`,
    { method: "POST", cache: "no-store", signal },
  );
  if (!res.ok) {
    throw new Error(
      await responseError(res, "Transaction inclusion proof failed"),
    );
  }
  return (await res.json()) as WalletTransactionInclusionCatalogResponse;
}

export async function getWalletTransactionJettonPayloadObservations(
  runId: number,
  transactionHash: string,
  signal?: AbortSignal,
): Promise<WalletJettonPayloadObservationsResponse> {
  const encodedHash = encodeURIComponent(transactionHash);
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/transactions/${encodedHash}/trace-evidence/boc-verification/jetton-payloads`,
    { cache: "no-store", signal },
  );
  if (!res.ok) {
    throw new Error(
      await responseError(res, "Jetton payload observation read failed"),
    );
  }
  return (await res.json()) as WalletJettonPayloadObservationsResponse;
}

export async function getWalletJettonContractVerifications(
  runId: number,
  signal?: AbortSignal,
): Promise<WalletJettonContractVerificationCatalogResponse> {
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/jetton-contract-verifications`,
    { cache: "no-store", signal },
  );
  if (!res.ok) {
    throw new Error(
      await responseError(res, "Jetton contract verification read failed"),
    );
  }
  return (await res.json()) as WalletJettonContractVerificationCatalogResponse;
}

export async function verifyWalletJettonContractRelationship(
  runId: number,
  jettonWalletAccountCanonical: string,
  jettonMasterAccountCanonical: string,
  signal?: AbortSignal,
): Promise<WalletJettonContractVerificationResponse> {
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/jetton-contract-verifications`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        jetton_wallet_account_canonical: jettonWalletAccountCanonical,
        jetton_master_account_canonical: jettonMasterAccountCanonical,
      }),
      signal,
    },
  );
  if (!res.ok) {
    throw new Error(
      await responseError(res, "Jetton contract proof verification failed"),
    );
  }
  return (await res.json()) as WalletJettonContractVerificationResponse;
}

export async function getWalletRunSignals(
  runId: number,
  signal?: AbortSignal,
): Promise<WalletRunSignalsResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ingest/${runId}/signals`, {
    cache: "no-store",
    signal,
  });

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

function walletPnlPreviewQuery(
  includeHistorical: boolean,
  includeUnrealized: boolean,
): string {
  const params = new URLSearchParams();
  if (includeHistorical) params.set("include_historical", "true");
  if (includeUnrealized) params.set("include_unrealized", "true");
  const query = params.toString();
  return query ? `?${query}` : "";
}

export async function getWalletRunPnlPreview(
  runId: number,
  includeHistorical = false,
  includeUnrealized = false,
): Promise<WalletRunPnlPreviewResponse> {
  const suffix = walletPnlPreviewQuery(
    includeHistorical,
    includeUnrealized,
  );
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
  includeUnrealized = false,
): string {
  const suffix = walletPnlPreviewQuery(
    includeHistorical,
    includeUnrealized,
  );
  return `${API_BASE}/api/wallets/ingest/${runId}/pnl-preview/export.json${suffix}`;
}

export function walletRunPnlPreviewCsvExportUrl(
  runId: number,
  includeHistorical = false,
  includeUnrealized = false,
): string {
  const suffix = walletPnlPreviewQuery(
    includeHistorical,
    includeUnrealized,
  );
  return `${API_BASE}/api/wallets/ingest/${runId}/pnl-preview/export.csv${suffix}`;
}

export function walletRunSignalsExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/signals/export.json`;
}

export function walletRunSignalsCsvExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/signals/export.csv`;
}

export function walletRunExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/canonical-ledger/export.json`;
}

export function walletRunExportCsvUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/canonical-ledger/export.csv`;
}

export function walletCanonicalReportExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/canonical-report/export.json`;
}

export function walletCanonicalReportCsvExportUrl(runId: number): string {
  return `${API_BASE}/api/wallets/ingest/${runId}/canonical-report/export.csv`;
}

export async function getWalletCanonicalReportAvailability(
  runId: number,
): Promise<{ available: boolean; message: string }> {
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${runId}/canonical-report`,
    { cache: "no-store" },
  );

  if (res.ok) {
    return {
      available: true,
      message: "Canonical ledger and report are ready for export.",
    };
  }

  const detail = await responseError(
    res,
    `Canonical report readiness failed (${res.status})`,
  );
  if (res.status === 404) {
    return { available: false, message: detail };
  }
  throw new Error(detail);
}

export async function createWalletOwnershipChallenge(
  expectedWallet: string,
  signal?: AbortSignal,
): Promise<WalletOwnershipChallengeResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/ownership/challenges`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    cache: "no-store",
    body: JSON.stringify({ expected_wallet: expectedWallet }),
    signal,
  });

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Ownership challenge request failed"),
    );
  }

  return (await res.json()) as WalletOwnershipChallengeResponse;
}

export async function verifyWalletOwnershipChallenge(
  challengeId: string,
  proof: WalletOwnershipProofRequest,
  signal?: AbortSignal,
): Promise<WalletOwnershipProofResponse> {
  const res = await fetch(
    `${API_BASE}/api/wallets/ownership/challenges/${encodeURIComponent(challengeId)}/verify`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify(proof),
      signal,
    },
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Ownership verification failed"),
    );
  }

  return (await res.json()) as WalletOwnershipProofResponse;
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
  signal?: AbortSignal,
): Promise<WalletClusterCompareResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/cluster/compare`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ run_ids: runIds }),
    signal,
  });

  if (!res.ok) {
    throw new Error(await responseError(res, "Wallet cluster compare failed"));
  }

  return (await res.json()) as WalletClusterCompareResponse;
}

export async function inspectWalletHistoryReadiness(
  req: WalletHistoryReadinessRequest,
  signal?: AbortSignal,
): Promise<WalletHistoryReadinessResponse> {
  const res = await fetch(`${API_BASE}/api/wallets/history/readiness`, {
    method: "POST",
    cache: "no-store",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
    signal,
  });

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Wallet interval coverage inspection failed"),
    );
  }

  return (await res.json()) as WalletHistoryReadinessResponse;
}

export async function inspectWalletNativePnlReadiness(
  targetRunId: number,
  runIds: number[],
): Promise<WalletNativeActivityPnlReadinessResponse> {
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${targetRunId}/native-activity-pnl-readiness`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: runIds }),
    },
  );

  if (!res.ok) {
    throw new Error(
      await responseError(res, "Native activity PnL readiness failed"),
    );
  }
  return (await res.json()) as WalletNativeActivityPnlReadinessResponse;
}

export async function inspectWalletMultiAssetPnlReadiness(
  targetRunId: number,
  runIds: number[],
): Promise<WalletMultiAssetPnlReadinessResponse> {
  const res = await fetch(
    `${API_BASE}/api/wallets/ingest/${targetRunId}/multi-asset-pnl-readiness`,
    {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: runIds }),
    },
  );
  if (!res.ok) {
    throw new Error(await responseError(res, "Multi-asset PnL readiness failed"));
  }
  return (await res.json()) as WalletMultiAssetPnlReadinessResponse;
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
