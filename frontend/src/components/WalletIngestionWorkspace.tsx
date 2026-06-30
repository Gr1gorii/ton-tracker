import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  compareWalletRuns,
  getWalletIngestionRun,
  previewWalletIngestion,
  runWalletIngestion,
  walletClusterCompareCsvExportUrl,
  walletClusterCompareExportUrl,
  walletRunExportCsvUrl,
  walletRunExportUrl,
} from "../api";
import type {
  TimeWindow,
  WalletActivityProviderEvidence,
  WalletActivitySummary,
  WalletBalanceSnapshotRecord,
  WalletClusterCompareResponse,
  WalletIngestionPreviewResponse,
  WalletIngestionRequest,
  WalletIngestionRunResponse,
  WalletIngestionSurface,
  WalletIngestionWarningRecord,
  WalletSourceStatus,
  WalletSwapRecord,
  WalletTransactionRecord,
  WalletTransferRecord,
} from "../types";
import PreviewFreshnessStrip from "./PreviewFreshnessStrip";
import PreviewReadinessStrip, {
  type PreviewReadinessTone,
} from "./PreviewReadinessStrip";
import {
  type ProviderPreviewRunUpdate,
  displayPreviewValue,
  formatPreviewRequestedAt,
  previewAccountLabel,
} from "./providerPreviewUtils";

const SURFACE_OPTIONS: Array<{
  value: WalletIngestionSurface;
  label: string;
  description: string;
}> = [
  {
    value: "transfers",
    label: "Transfers",
    description: "Incoming/outgoing TON and jetton movements",
  },
  {
    value: "transactions",
    label: "Transactions",
    description: "Ordered account transaction rows",
  },
  {
    value: "swaps",
    label: "DEX swaps",
    description: "Mock-normalized swap-side activity",
  },
  {
    value: "balances",
    label: "TON balance",
    description: "Native TON balance snapshot",
  },
  {
    value: "jettons",
    label: "Jettons",
    description: "Jetton balance snapshots",
  },
];

const DEFAULT_SURFACES = SURFACE_OPTIONS.map((item) => item.value);

const CAN_SHOW = [
  "Coverage preview",
  "Persisted mock run",
  "Transfers",
  "Transactions",
  "Swaps",
  "Balances",
  "Provider evidence",
  "Wallet-pair similarity (probabilistic, not proof)",
];

const CANNOT_SHOW = [
  "Real provider fetch",
  "Real wallet PnL",
  "Ownership proof",
];

interface RequestSnapshot {
  walletAddress: string;
  timeWindow: TimeWindow;
  customStart: string;
  customEnd: string;
  surfaces: WalletIngestionSurface[];
  requestedAt: string;
  signature: string;
}

interface WalletIngestionWorkspaceProps {
  accountAddress: string;
  runRequestId: number;
  onAccountAddressChange: (value: string) => void;
  onPreviewRunStateChange?: (update: ProviderPreviewRunUpdate) => void;
}

function surfaceLabel(surface: WalletIngestionSurface): string {
  return SURFACE_OPTIONS.find((item) => item.value === surface)?.label ?? surface;
}

function formatSurfaces(surfaces: WalletIngestionSurface[]): string {
  if (surfaces.length === 0) return "None";
  if (surfaces.length === SURFACE_OPTIONS.length) return "All surfaces";
  return surfaces.map(surfaceLabel).join(", ");
}

function sourceClass(status: WalletSourceStatus | string): string {
  if (status === "live") return "source-badge source-real";
  if (status === "mock") return "source-badge source-mock";
  return "source-badge source-unknown";
}

function dateLabel(value: string | null | undefined): string {
  if (!value) return "-";
  return value.replace("T", " ").replace("Z", " UTC");
}

export default function WalletIngestionWorkspace({
  accountAddress,
  runRequestId,
  onAccountAddressChange,
  onPreviewRunStateChange,
}: WalletIngestionWorkspaceProps) {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("24h");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [selectedSurfaces, setSelectedSurfaces] =
    useState<WalletIngestionSurface[]>(DEFAULT_SURFACES);
  const [loadingAction, setLoadingAction] = useState<
    "preview" | "run" | "read" | null
  >(null);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] =
    useState<WalletIngestionPreviewResponse | null>(null);
  const [runResult, setRunResult] = useState<WalletIngestionRunResponse | null>(
    null,
  );
  const [resultSnapshot, setResultSnapshot] = useState<RequestSnapshot | null>(
    null,
  );
  const activeRequestId = useRef(0);

  useEffect(() => {
    setRequestError(null);
  }, [accountAddress, timeWindow, customStart, customEnd, selectedSurfaces]);

  useEffect(() => {
    if (runRequestId <= 0) return;
    void handlePreview();
  }, [runRequestId]);

  const currentAccount = accountAddress.trim();
  const currentSignature = requestSignature(
    currentAccount,
    timeWindow,
    customStart,
    customEnd,
    selectedSurfaces,
  );
  const resultIsStale =
    resultSnapshot !== null && resultSnapshot.signature !== currentSignature;
  const busy = loadingAction !== null;
  const validationMessage = validateCurrentRequest(
    currentAccount,
    timeWindow,
    customStart,
    customEnd,
    selectedSurfaces,
  );
  const canSubmit = !busy && validationMessage === null;
  const visibleEvidence =
    runResult?.provider_evidence ?? previewResult?.provider_coverage ?? [];
  const visibleWarnings = runResult
    ? runResult.warnings.map((warning) => warning.message)
    : previewResult?.warnings ?? [];
  const readiness = buildReadiness({
    busy,
    loadingAction,
    requestError,
    validationMessage,
    previewResult,
    runResult,
    resultIsStale,
  });

  function makePayload(): { payload: WalletIngestionRequest } | { error: string } {
    const error = validateCurrentRequest(
      currentAccount,
      timeWindow,
      customStart,
      customEnd,
      selectedSurfaces,
    );
    if (error) return { error };

    const payload: WalletIngestionRequest = {
      wallet_address: currentAccount,
      time_window: timeWindow,
      surfaces: selectedSurfaces,
    };

    if (timeWindow === "custom") {
      payload.custom_start = new Date(customStart).toISOString();
      payload.custom_end = new Date(customEnd).toISOString();
    }

    return { payload };
  }

  function snapshotForPayload(payload: WalletIngestionRequest): RequestSnapshot {
    return {
      walletAddress: payload.wallet_address,
      timeWindow: payload.time_window,
      customStart: payload.custom_start ?? "",
      customEnd: payload.custom_end ?? "",
      surfaces: payload.surfaces,
      requestedAt: formatPreviewRequestedAt(new Date()),
      signature: requestSignature(
        payload.wallet_address,
        payload.time_window,
        payload.custom_start ?? "",
        payload.custom_end ?? "",
        payload.surfaces,
      ),
    };
  }

  function toggleSurface(surface: WalletIngestionSurface) {
    setSelectedSurfaces((current) => {
      if (!current.includes(surface)) return [...current, surface];
      if (current.length === 1) return current;
      return current.filter((item) => item !== surface);
    });
  }

  async function handlePreview() {
    setRequestError(null);
    const request = makePayload();
    if ("error" in request) {
      setRequestError(request.error);
      onPreviewRunStateChange?.({
        status: "error",
        message: request.error,
        accountAddress: currentAccount,
        limit: formatSurfaces(selectedSurfaces),
      });
      return;
    }

    const requestId = activeRequestId.current + 1;
    activeRequestId.current = requestId;
    setPreviewResult(null);
    setLoadingAction("preview");
    onAccountAddressChange(request.payload.wallet_address);
    onPreviewRunStateChange?.({
      status: "running",
      message: "Previewing mock-normalized wallet activity coverage.",
      accountAddress: request.payload.wallet_address,
      limit: formatSurfaces(request.payload.surfaces),
    });

    try {
      const data = await previewWalletIngestion(request.payload);
      if (activeRequestId.current !== requestId) return;
      setPreviewResult(data);
      setResultSnapshot(snapshotForPayload(request.payload));
      onPreviewRunStateChange?.({
        status: "success",
        message: `Coverage preview returned ${data.provider_coverage[0]?.normalized_count ?? 0} mock-normalized rows.`,
        accountAddress: request.payload.wallet_address,
        limit: formatSurfaces(request.payload.surfaces),
      });
    } catch (e) {
      if (activeRequestId.current !== requestId) return;
      const message =
        e instanceof Error ? e.message : "Unknown wallet ingestion preview error";
      setRequestError(message);
      onPreviewRunStateChange?.({
        status: "error",
        message,
        accountAddress: request.payload.wallet_address,
        limit: formatSurfaces(request.payload.surfaces),
      });
    } finally {
      if (activeRequestId.current === requestId) setLoadingAction(null);
    }
  }

  async function handleRun() {
    setRequestError(null);
    const request = makePayload();
    if ("error" in request) {
      setRequestError(request.error);
      return;
    }

    const requestId = activeRequestId.current + 1;
    activeRequestId.current = requestId;
    setLoadingAction("run");
    onAccountAddressChange(request.payload.wallet_address);
    onPreviewRunStateChange?.({
      status: "running",
      message: "Persisting wallet activity ingestion run.",
      accountAddress: request.payload.wallet_address,
      limit: formatSurfaces(request.payload.surfaces),
    });

    try {
      const data = await runWalletIngestion(request.payload);
      if (activeRequestId.current !== requestId) return;
      setRunResult(data);
      setResultSnapshot(snapshotForPayload(request.payload));
      onPreviewRunStateChange?.({
        status: "success",
        message: `${data.data_mode === "real" ? "Live" : "Mock"} ingestion run #${data.run_id ?? "-"} stored ${activityCount(data)} normalized rows.`,
        accountAddress: request.payload.wallet_address,
        limit: formatSurfaces(request.payload.surfaces),
      });
    } catch (e) {
      if (activeRequestId.current !== requestId) return;
      const message =
        e instanceof Error ? e.message : "Unknown wallet ingestion run error";
      setRequestError(message);
      onPreviewRunStateChange?.({
        status: "error",
        message,
        accountAddress: request.payload.wallet_address,
        limit: formatSurfaces(request.payload.surfaces),
      });
    } finally {
      if (activeRequestId.current === requestId) setLoadingAction(null);
    }
  }

  async function handleRefreshRun() {
    if (!runResult?.run_id) return;
    setRequestError(null);
    const requestId = activeRequestId.current + 1;
    activeRequestId.current = requestId;
    setLoadingAction("read");
    try {
      const data = await getWalletIngestionRun(runResult.run_id);
      if (activeRequestId.current !== requestId) return;
      setRunResult(data);
    } catch (e) {
      if (activeRequestId.current !== requestId) return;
      setRequestError(
        e instanceof Error ? e.message : "Unknown wallet ingestion read error",
      );
    } finally {
      if (activeRequestId.current === requestId) setLoadingAction(null);
    }
  }

  function clearPanel() {
    setTimeWindow("24h");
    setCustomStart("");
    setCustomEnd("");
    setSelectedSurfaces(DEFAULT_SURFACES);
    setRequestError(null);
    setPreviewResult(null);
    setRunResult(null);
    setResultSnapshot(null);
    setLoadingAction(null);
    onPreviewRunStateChange?.({
      status: "idle",
      message: "Wallet ingestion workspace cleared.",
      accountAddress: currentAccount,
      limit: "All surfaces",
    });
  }

  return (
    <section className="section wallet-ingestion-panel wallet-intelligence-console">
      <div className="wallet-intelligence-head">
        <div>
          <span className="section-eyebrow">
            {runResult?.data_mode === "real"
              ? "Guarded live ingestion"
              : "Mock-normalized ingestion"}
          </span>
          <h2>Wallet Activity Ingestion Workspace</h2>
          <p>
            Preview coverage, persist one wallet activity run, and inspect
            normalized, source-labeled rows.
          </p>
        </div>
        <div className="wallet-intelligence-badges">
          <span className="badge badge-provider">WORKSPACE</span>
          <span
            className={`badge ${runResult?.data_mode === "real" ? "badge-real" : "badge-mock"}`}
          >
            {runResult?.data_mode === "real" ? "LIVE SOURCE" : "MOCK SOURCE"}
          </span>
          {runResult && <span className="badge badge-real">RUN #{runResult.run_id}</span>}
        </div>
      </div>

      <div className="wallet-scope-board" aria-label="Wallet ingestion scope">
        <ScopeColumn title="Can show" tone="success" items={CAN_SHOW} />
        <ScopeColumn title="Not wired yet" tone="warning" items={CANNOT_SHOW} />
      </div>

      <div className="tonapi-wallet-note wallet-ingestion-note">
        <div>
          {runResult?.data_mode === "real"
            ? "This run used the guarded live TonAPI path. Rows are real on-chain account data, persisted and source-labeled; they do not feed PnL or clustering yet."
            : "The ingestion workspace uses deterministic fixtures from the backend. Rows are persisted and source-labeled, but they are not real on-chain wallet activity and do not feed PnL or clustering yet."}
        </div>
      </div>

      <PreviewReadinessStrip
        tone={readiness.tone}
        label={readiness.label}
        message={readiness.message}
        items={[
          {
            label: "Wallet",
            value: currentAccount || "Required",
          },
          {
            label: "Window",
            value: timeWindow,
          },
          {
            label: "Surfaces",
            value: formatSurfaces(selectedSurfaces),
          },
        ]}
      />

      <div className="wallet-ingestion-form wallet-query-card">
        <div className="field wallet-ingestion-address-field">
          <label className="field-label" htmlFor="wallet-ingestion-address">
            Wallet address
          </label>
          <input
            id="wallet-ingestion-address"
            className="text-input"
            type="text"
            value={accountAddress}
            disabled={busy}
            placeholder="EQ..."
            onChange={(event) => onAccountAddressChange(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="wallet-ingestion-window">
            Window
          </label>
          <select
            id="wallet-ingestion-window"
            className="text-input"
            value={timeWindow}
            disabled={busy}
            onChange={(event) => setTimeWindow(event.target.value as TimeWindow)}
          >
            <option value="24h">24h</option>
            <option value="3d">3d</option>
            <option value="7d">7d</option>
            <option value="custom">Custom</option>
          </select>
        </div>

        {timeWindow === "custom" && (
          <div className="wallet-ingestion-custom-window">
            <div className="field">
              <label className="field-label" htmlFor="wallet-ingestion-start">
                Start
              </label>
              <input
                id="wallet-ingestion-start"
                className="text-input"
                type="datetime-local"
                value={customStart}
                disabled={busy}
                onChange={(event) => setCustomStart(event.target.value)}
              />
            </div>
            <div className="field">
              <label className="field-label" htmlFor="wallet-ingestion-end">
                End
              </label>
              <input
                id="wallet-ingestion-end"
                className="text-input"
                type="datetime-local"
                value={customEnd}
                disabled={busy}
                onChange={(event) => setCustomEnd(event.target.value)}
              />
            </div>
          </div>
        )}

        <div className="wallet-ingestion-surfaces" aria-label="Requested surfaces">
          {SURFACE_OPTIONS.map((surface) => (
            <label
              className={
                selectedSurfaces.includes(surface.value)
                  ? "wallet-surface-toggle wallet-surface-toggle-active"
                  : "wallet-surface-toggle"
              }
              key={surface.value}
            >
              <input
                type="checkbox"
                checked={selectedSurfaces.includes(surface.value)}
                disabled={busy || selectedSurfaces.length === 1 && selectedSurfaces.includes(surface.value)}
                onChange={() => toggleSurface(surface.value)}
              />
              <span>{surface.label}</span>
              <small>{surface.description}</small>
            </label>
          ))}
        </div>

        <div className="wallet-ingestion-actions">
          <button
            className="btn btn-primary"
            type="button"
            onClick={handlePreview}
            disabled={!canSubmit}
          >
            {loadingAction === "preview" ? "Previewing coverage" : "Preview coverage"}
          </button>
          <button
            className="btn btn-primary"
            type="button"
            onClick={handleRun}
            disabled={!canSubmit}
          >
            {loadingAction === "run" ? "Running ingestion" : "Run ingestion"}
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={handleRefreshRun}
            disabled={busy || !runResult?.run_id}
          >
            {loadingAction === "read" ? "Refreshing run" : "Refresh run"}
          </button>
          {runResult?.run_id != null && (
            <a
              className="btn btn-ghost"
              href={walletRunExportUrl(runResult.run_id)}
              download
            >
              Export run (JSON)
            </a>
          )}
          {runResult?.run_id != null && (
            <a
              className="btn btn-ghost"
              href={walletRunExportCsvUrl(runResult.run_id)}
              download
            >
              Export run (CSV)
            </a>
          )}
          <button
            className="btn btn-ghost"
            type="button"
            onClick={clearPanel}
            disabled={busy}
          >
            Clear
          </button>
        </div>
      </div>

      {requestError && <WalletIngestionError message={requestError} />}
      {busy && <WalletIngestionLoading action={loadingAction} />}
      {!busy && !requestError && !previewResult && !runResult && (
        <WalletIngestionEmpty />
      )}

      {!busy && !requestError && (previewResult || runResult) && resultSnapshot && (
        <div className="wallet-ingestion-results">
          <div className="tonapi-wallet-result-head">
            {previewResult && <span className="badge badge-provider">COVERAGE</span>}
            {runResult && (
              <>
                <span className="badge badge-real">RUN #{runResult.run_id}</span>
                <span className="badge badge-provider">STATUS {runResult.status}</span>
              </>
            )}
            <span className="badge badge-mock">SOURCE MOCK</span>
            <span className="badge badge-provider">
              ROWS {runResult ? activityCount(runResult) : visibleEvidence[0]?.normalized_count ?? 0}
            </span>
          </div>

          <PreviewFreshnessStrip
            isStale={resultIsStale}
            requestedAt={resultSnapshot.requestedAt}
            message={
              resultIsStale
                ? "Displayed ingestion data belongs to the requested snapshot below. Preview or run again for current inputs."
                : "Displayed ingestion data matches the current wallet, window, and surfaces."
            }
            items={[
              {
                label: "Wallet",
                requestedValue: resultSnapshot.walletAddress,
                currentValue: previewAccountLabel(currentAccount),
              },
              {
                label: "Window",
                requestedValue: resultSnapshot.timeWindow,
                currentValue: timeWindow,
              },
              {
                label: "Surfaces",
                requestedValue: formatSurfaces(resultSnapshot.surfaces),
                currentValue: formatSurfaces(selectedSurfaces),
              },
            ]}
          />

          <div className="scope-strip">
            {runResult?.message ?? previewResult?.message}
          </div>

          <WalletIngestionMetrics result={runResult} preview={previewResult} />
          <ProviderEvidence evidence={visibleEvidence} />
          <WalletIngestionWarnings warnings={visibleWarnings} />

          {runResult?.activity_summary && (
            <ActivitySummaryCard summary={runResult.activity_summary} />
          )}
          {runResult && <WalletActivityTables result={runResult} />}
          {runResult?.run_id != null && (
            <WalletClusterCompareCard runId={runResult.run_id} />
          )}
        </div>
      )}
    </section>
  );
}

function requestSignature(
  walletAddress: string,
  timeWindow: TimeWindow,
  customStart: string,
  customEnd: string,
  surfaces: WalletIngestionSurface[],
): string {
  return JSON.stringify({
    walletAddress,
    timeWindow,
    customStart,
    customEnd,
    surfaces: [...surfaces].sort(),
  });
}

function validateCurrentRequest(
  walletAddress: string,
  timeWindow: TimeWindow,
  customStart: string,
  customEnd: string,
  surfaces: WalletIngestionSurface[],
): string | null {
  if (!walletAddress) return "Wallet address is required.";
  if (surfaces.length === 0) return "At least one activity surface is required.";
  if (timeWindow !== "custom") return null;
  if (!customStart || !customEnd) {
    return "Choose both custom start and custom end before running ingestion.";
  }
  const start = new Date(customStart);
  const end = new Date(customEnd);
  if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
    return "Custom window must use valid dates.";
  }
  if (start >= end) return "Custom range end must be after the start.";
  return null;
}

function buildReadiness({
  busy,
  loadingAction,
  requestError,
  validationMessage,
  previewResult,
  runResult,
  resultIsStale,
}: {
  busy: boolean;
  loadingAction: "preview" | "run" | "read" | null;
  requestError: string | null;
  validationMessage: string | null;
  previewResult: WalletIngestionPreviewResponse | null;
  runResult: WalletIngestionRunResponse | null;
  resultIsStale: boolean;
}): { tone: PreviewReadinessTone; label: string; message: string } {
  if (busy) {
    const label =
      loadingAction === "run"
        ? "RUNNING INGESTION"
        : loadingAction === "read"
          ? "READING RUN"
          : "PREVIEWING COVERAGE";
    return {
      tone: "running",
      label,
      message: "Wallet activity ingestion request is in progress.",
    };
  }
  if (requestError) {
    return { tone: "error", label: "REQUEST ERROR", message: requestError };
  }
  if (validationMessage) {
    return { tone: "warning", label: "INPUT REQUIRED", message: validationMessage };
  }
  if (resultIsStale) {
    return {
      tone: "stale",
      label: "RESULT STALE",
      message: "Current controls no longer match the displayed ingestion result.",
    };
  }
  if (runResult) {
    return {
      tone: "fresh",
      label: "RUN STORED",
      message: "Persisted mock-normalized wallet activity run matches current inputs.",
    };
  }
  if (previewResult) {
    return {
      tone: "fresh",
      label: "COVERAGE READY",
      message: "Coverage preview matches current inputs. You can persist a mock run.",
    };
  }
  return {
    tone: "ready",
    label: "READY",
    message: "Ready to preview or persist deterministic mock wallet activity.",
  };
}

function activityCount(result: WalletIngestionRunResponse): number {
  return (
    result.transfers.length +
    result.transactions.length +
    result.swaps.length +
    result.balances.length
  );
}

function ScopeColumn({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "success" | "warning";
  items: string[];
}) {
  return (
    <div className={`wallet-scope-column wallet-scope-${tone}`}>
      <span>{title}</span>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function WalletIngestionMetrics({
  result,
  preview,
}: {
  result: WalletIngestionRunResponse | null;
  preview: WalletIngestionPreviewResponse | null;
}) {
  const rows = result ? activityCount(result) : preview?.provider_coverage[0]?.normalized_count ?? 0;

  return (
    <div className="wallet-metric-grid wallet-ingestion-metric-grid">
      <WalletMetric label="Normalized rows" value={rows} />
      <WalletMetric label="Transfers" value={result?.transfers.length ?? "-"} />
      <WalletMetric label="Transactions" value={result?.transactions.length ?? "-"} />
      <WalletMetric label="Swaps" value={result?.swaps.length ?? "-"} />
      <WalletMetric label="Balances" value={result?.balances.length ?? "-"} />
      <WalletMetric
        label="Warnings"
        value={result?.warnings.length ?? preview?.warnings.length ?? 0}
        muted
      />
    </div>
  );
}

function WalletMetric({
  label,
  value,
  muted,
}: {
  label: string;
  value: string | number;
  muted?: boolean;
}) {
  return (
    <div className={muted ? "wallet-metric wallet-metric-muted" : "wallet-metric"}>
      <span>{label}</span>
      <strong>{displayPreviewValue(value)}</strong>
    </div>
  );
}

function ProviderEvidence({
  evidence,
}: {
  evidence: WalletActivityProviderEvidence[];
}) {
  if (evidence.length === 0) return null;

  return (
    <div className="wallet-evidence-grid">
      {evidence.map((item) => (
        <div className="wallet-evidence-card" key={item.provider}>
          <span>{item.provider}</span>
          <strong>
            {item.normalized_count}/{item.raw_count} rows
          </strong>
          <p>
            <span className={sourceClass(item.source_status)}>
              {item.source_status}
            </span>{" "}
            {item.freshness ? `Freshness ${dateLabel(item.freshness)}` : "No freshness timestamp"}
          </p>
        </div>
      ))}
    </div>
  );
}

function WalletIngestionWarnings({ warnings }: { warnings: string[] }) {
  if (warnings.length === 0) return null;

  return (
    <div className="tonapi-wallet-warning-list">
      {warnings.map((warning, index) => (
        <div className="import-analysis-note" key={`${warning}:${index}`}>
          {warning}
        </div>
      ))}
    </div>
  );
}

function ActivitySummaryCard({ summary }: { summary: WalletActivitySummary }) {
  return (
    <div
      className="intelligence-table-block"
      aria-label="Derived activity summary"
    >
      <div className="table-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Derived — not PnL</span>
          <h2>Activity summary</h2>
          <p>{summary.note}</p>
        </div>
        <div className="table-meta">
          <span className="badge badge-mock">NOT PnL</span>
        </div>
      </div>

      <div className="workspace-scope-strip" aria-label="Activity counts">
        <div className="workspace-scope-item">
          <span>Transfers</span>
          <strong>{summary.counts.transfers}</strong>
        </div>
        <div className="workspace-scope-item">
          <span>Transactions</span>
          <strong>{summary.counts.transactions}</strong>
        </div>
        <div className="workspace-scope-item">
          <span>Swaps</span>
          <strong>{summary.counts.swaps}</strong>
        </div>
        <div className="workspace-scope-item">
          <span>Balances</span>
          <strong>{summary.counts.balances}</strong>
        </div>
      </div>

      {summary.transfers_by_asset.length > 0 && (
        <table className="data-table intelligence-table wallet-ingestion-table">
          <thead>
            <tr>
              <th>Asset</th>
              <th>In</th>
              <th>Out</th>
              <th>Net (token qty)</th>
            </tr>
          </thead>
          <tbody>
            {summary.transfers_by_asset.map((row) => (
              <tr key={row.asset}>
                <td>{row.asset}</td>
                <td>{row.in_count}</td>
                <td>{row.out_count}</td>
                <td>{row.net_amount}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {summary.swaps_by_dex.length > 0 && (
        <p className="muted small">
          Swaps by DEX:{" "}
          {summary.swaps_by_dex
            .map((entry) => `${entry.dex} (${entry.count})`)
            .join(", ")}
        </p>
      )}

      {summary.swaps_by_token && summary.swaps_by_token.length > 0 && (
        <p className="muted small">
          Swap volume (token qty):{" "}
          {summary.swaps_by_token
            .map(
              (entry) =>
                `${entry.token} sent ${entry.sent_amount} / received ${entry.received_amount}`,
            )
            .join("; ")}
        </p>
      )}

      {summary.balances.portfolio?.total_balance_usd != null && (
        <p className="muted small">
          Portfolio (provider-priced): ${summary.balances.portfolio.total_balance_usd}{" "}
          ({summary.balances.portfolio.priced_assets} priced,{" "}
          {summary.balances.portfolio.unpriced_assets} unpriced). Provider prices
          may be stale; unpriced assets excluded.
        </p>
      )}
    </div>
  );
}

function pairScoreKey(a: number, b: number): string {
  return a < b ? `${a}-${b}` : `${b}-${a}`;
}

function WalletClusterCompareCard({ runId }: { runId: number }) {
  const [otherRunIds, setOtherRunIds] = useState("");
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [compareResult, setCompareResult] =
    useState<WalletClusterCompareResponse | null>(null);

  const handleCompare = async () => {
    const tokens = otherRunIds
      .split(/[\s,]+/)
      .map((token) => token.trim())
      .filter((token) => token !== "");
    const invalid = tokens.filter((token) => {
      const value = Number(token);
      return !Number.isInteger(value) || value <= 0;
    });
    if (invalid.length > 0) {
      setCompareError(`Not valid run ids: ${invalid.join(", ")}`);
      return;
    }
    // Combine with the current run, dedupe, drop a self-reference.
    const others = tokens.map((token) => Number(token));
    const runIds = Array.from(new Set([runId, ...others]));
    if (runIds.length < 2) {
      setCompareError("Enter at least one other run id to compare against.");
      return;
    }
    if (runIds.length > 25) {
      setCompareError("At most 25 runs can be compared at once.");
      return;
    }
    setComparing(true);
    setCompareError(null);
    try {
      const data = await compareWalletRuns(runIds);
      setCompareResult(data);
    } catch (err) {
      setCompareResult(null);
      setCompareError(err instanceof Error ? err.message : "Comparison failed.");
    } finally {
      setComparing(false);
    }
  };

  const scoreByPair = new Map<string, number>();
  if (compareResult) {
    for (const pair of compareResult.pairs) {
      scoreByPair.set(
        pairScoreKey(pair.wallet_a_run_id, pair.wallet_b_run_id),
        pair.score,
      );
    }
  }

  return (
    <div className="intelligence-table-block" aria-label="Wallet pair comparison">
      <div className="table-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Probabilistic signal — not proof</span>
          <h2>Compare with other runs</h2>
          <p>
            Behavioral similarity between this run (#{runId}) and up to 24 other
            stored wallet ingestion runs, derived only from on-chain swap and
            balance rows. Never proof of common ownership.
          </p>
        </div>
        <div className="table-meta">
          <span className="badge badge-mock">NOT OWNERSHIP PROOF</span>
        </div>
      </div>

      <div className="wallet-ingestion-form wallet-query-card">
        <div className="field">
          <label className="field-label" htmlFor="wallet-cluster-other-runs">
            Other run ids
          </label>
          <input
            id="wallet-cluster-other-runs"
            className="text-input"
            type="text"
            value={otherRunIds}
            disabled={comparing}
            placeholder="e.g. 12, 15, 20"
            onChange={(event) => setOtherRunIds(event.target.value)}
          />
        </div>
        <button
          className="btn btn-primary"
          type="button"
          onClick={handleCompare}
          disabled={comparing || otherRunIds.trim() === ""}
        >
          {comparing ? "Comparing" : "Compare"}
        </button>
      </div>

      {compareError && <WalletIngestionError message={compareError} />}

      {compareResult && (
        <>
          <div className="tonapi-wallet-result-head">
            <a
              className="btn btn-ghost"
              href={walletClusterCompareExportUrl(
                compareResult.wallets.map((wallet) => wallet.run_id),
              )}
              download
            >
              Export comparison (JSON)
            </a>
            <a
              className="btn btn-ghost"
              href={walletClusterCompareCsvExportUrl(
                compareResult.wallets.map((wallet) => wallet.run_id),
              )}
              download
            >
              Export comparison (CSV)
            </a>
          </div>
          <p className="muted small">{compareResult.note}</p>

          {compareResult.wallets.length > 2 && (
            <table className="data-table intelligence-table wallet-ingestion-table">
              <thead>
                <tr>
                  <th>Score matrix</th>
                  {compareResult.wallets.map((wallet) => (
                    <th key={`col-${wallet.run_id}`}>#{wallet.run_id}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {compareResult.wallets.map((rowWallet) => (
                  <tr key={`row-${rowWallet.run_id}`}>
                    <td>#{rowWallet.run_id}</td>
                    {compareResult.wallets.map((colWallet) => {
                      if (rowWallet.run_id === colWallet.run_id) {
                        return <td key={`cell-${rowWallet.run_id}-${colWallet.run_id}`}>—</td>;
                      }
                      const score = scoreByPair.get(
                        pairScoreKey(rowWallet.run_id, colWallet.run_id),
                      );
                      return (
                        <td key={`cell-${rowWallet.run_id}-${colWallet.run_id}`}>
                          {score != null ? score.toFixed(2) : "-"}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          <table className="data-table intelligence-table wallet-ingestion-table">
            <thead>
              <tr>
                <th>Wallet A</th>
                <th>Wallet B</th>
                <th>Score</th>
                <th>Band</th>
                <th>Shared tokens</th>
              </tr>
            </thead>
            <tbody>
              {compareResult.pairs.map((pair) => (
                <tr key={`${pair.wallet_a_run_id}-${pair.wallet_b_run_id}`}>
                  <td>
                    #{pair.wallet_a_run_id} {pair.wallet_a_address}
                  </td>
                  <td>
                    #{pair.wallet_b_run_id} {pair.wallet_b_address}
                  </td>
                  <td>{pair.score.toFixed(2)}</td>
                  <td>{pair.band}</td>
                  <td>{pair.shared_tokens.join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {compareResult.pairs.map((pair) => (
            <p
              className="muted small"
              key={`note-${pair.wallet_a_run_id}-${pair.wallet_b_run_id}`}
            >
              {pair.note}
            </p>
          ))}
          {compareResult.wallets.some((w) => w.warnings.length > 0) && (
            <p className="muted small">
              {compareResult.wallets
                .flatMap((w) => w.warnings.map((msg) => `#${w.run_id}: ${msg}`))
                .join(" ")}
            </p>
          )}
        </>
      )}
    </div>
  );
}

function WalletActivityTables({ result }: { result: WalletIngestionRunResponse }) {
  return (
    <div className="wallet-activity-table-stack">
      <TransfersTable transfers={result.transfers} />
      <TransactionsTable transactions={result.transactions} />
      <SwapsTable swaps={result.swaps} />
      <BalancesTable balances={result.balances} />
      <RunWarningsTable warnings={result.warnings} />
    </div>
  );
}

function TableBlock({
  title,
  description,
  count,
  children,
}: {
  title: string;
  description: string;
  count: number;
  children: ReactNode;
}) {
  return (
    <div className="intelligence-table-block">
      <div className="table-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Normalized activity</span>
          <h2>{title}</h2>
          <p>{description}</p>
        </div>
        <div className="table-meta">
          <span className="badge badge-provider">{count} rows</span>
        </div>
      </div>
      {children}
    </div>
  );
}

function EmptyTable({ message }: { message: string }) {
  return (
    <div className="state-box empty-box table-empty-state">
      <strong>No rows for this surface.</strong>
      <p>{message}</p>
    </div>
  );
}

function TransfersTable({ transfers }: { transfers: WalletTransferRecord[] }) {
  return (
    <TableBlock
      title="Transfers"
      description="Incoming and outgoing TON or jetton movements from the ingestion run."
      count={transfers.length}
    >
      {transfers.length === 0 ? (
        <EmptyTable message="Transfers were not requested or no mock rows were returned." />
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table wallet-ingestion-table">
            <thead>
              <tr>
                <th>Tx</th>
                <th>Time</th>
                <th>Direction</th>
                <th>Asset</th>
                <th className="num">Amount</th>
                <th>Counterparty</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {transfers.map((item, index) => (
                <tr key={`${item.tx_hash}:${index}`}>
                  <td className="mono">{displayPreviewValue(item.tx_hash)}</td>
                  <td>{dateLabel(item.timestamp)}</td>
                  <td>
                    <span className="source-badge source-unknown">
                      {item.direction}
                    </span>
                  </td>
                  <td>{item.asset}</td>
                  <td className="num">{displayPreviewValue(item.amount)}</td>
                  <td className="mono">{displayPreviewValue(item.counterparty)}</td>
                  <td>
                    <span className={sourceClass(item.source_status)}>
                      {item.source_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </TableBlock>
  );
}

function TransactionsTable({
  transactions,
}: {
  transactions: WalletTransactionRecord[];
}) {
  return (
    <TableBlock
      title="Transactions"
      description="Transaction rows preserve fees, status, provider, and source status."
      count={transactions.length}
    >
      {transactions.length === 0 ? (
        <EmptyTable message="Transactions were not requested or no mock rows were returned." />
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table wallet-ingestion-table">
            <thead>
              <tr>
                <th>Tx</th>
                <th>Time</th>
                <th className="num">Fee TON</th>
                <th>Status</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((item, index) => (
                <tr key={`${item.tx_hash}:${index}`}>
                  <td className="mono">{item.tx_hash}</td>
                  <td>{dateLabel(item.timestamp)}</td>
                  <td className="num">{displayPreviewValue(item.fee_ton)}</td>
                  <td>
                    <span className="source-badge source-real">
                      {item.success}
                    </span>
                  </td>
                  <td>
                    <span className={sourceClass(item.source_status)}>
                      {item.source_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </TableBlock>
  );
}

function SwapsTable({ swaps }: { swaps: WalletSwapRecord[] }) {
  return (
    <TableBlock
      title="DEX swaps"
      description="Swap rows are source-labeled and kept separate from legacy PnL."
      count={swaps.length}
    >
      {swaps.length === 0 ? (
        <EmptyTable message="Swaps were not requested or no mock rows were returned." />
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table wallet-ingestion-table">
            <thead>
              <tr>
                <th>Tx</th>
                <th>DEX</th>
                <th className="num">In</th>
                <th className="num">Out</th>
                <th className="num">USD</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {swaps.map((item, index) => (
                <tr key={`${item.tx_hash}:${index}`}>
                  <td className="mono">{displayPreviewValue(item.tx_hash)}</td>
                  <td>{displayPreviewValue(item.dex)}</td>
                  <td className="num">
                    {displayPreviewValue(item.amount_in)} {displayPreviewValue(item.token_in)}
                  </td>
                  <td className="num">
                    {displayPreviewValue(item.amount_out)} {displayPreviewValue(item.token_out)}
                  </td>
                  <td className="num">{displayPreviewValue(item.estimated_usd)}</td>
                  <td>
                    <span className={sourceClass(item.source_status)}>
                      {item.source_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </TableBlock>
  );
}

function BalancesTable({ balances }: { balances: WalletBalanceSnapshotRecord[] }) {
  return (
    <TableBlock
      title="Balances"
      description="Source-aware native TON or jetton balance snapshots returned by the selected ingestion adapter."
      count={balances.length}
    >
      {balances.length === 0 ? (
        <EmptyTable message="Balances and jettons were not requested or no mock rows were returned." />
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table wallet-ingestion-table">
            <thead>
              <tr>
                <th>Asset</th>
                <th className="num">Balance</th>
                <th className="num">USD</th>
                <th>Snapshot</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {balances.map((item, index) => (
                <tr key={`${item.asset}:${index}`}>
                  <td>{item.asset}</td>
                  <td className="num">{displayPreviewValue(item.balance)}</td>
                  <td className="num">{displayPreviewValue(item.balance_usd)}</td>
                  <td>{dateLabel(item.snapshot_at)}</td>
                  <td>
                    <span className={sourceClass(item.source_status)}>
                      {item.source_status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </TableBlock>
  );
}

function RunWarningsTable({
  warnings,
}: {
  warnings: WalletIngestionWarningRecord[];
}) {
  return (
    <TableBlock
      title="Run warnings"
      description="Data honesty messages stored with the ingestion run."
      count={warnings.length}
    >
      {warnings.length === 0 ? (
        <EmptyTable message="No ingestion warnings were stored for this run." />
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table wallet-ingestion-table">
            <thead>
              <tr>
                <th>Severity</th>
                <th>Provider</th>
                <th>Evidence</th>
                <th>Message</th>
              </tr>
            </thead>
            <tbody>
              {warnings.map((item, index) => (
                <tr key={`${item.evidence_key}:${index}`}>
                  <td>
                    <span className="source-badge source-mock">
                      {item.severity}
                    </span>
                  </td>
                  <td>{displayPreviewValue(item.provider)}</td>
                  <td className="mono">{displayPreviewValue(item.evidence_key)}</td>
                  <td>{item.message}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </TableBlock>
  );
}

function WalletIngestionEmpty() {
  return (
    <div className="state-box empty-box tonapi-wallet-state wallet-intelligence-state">
      <span className="state-kicker">NO_INGESTION_RESULT</span>
      <strong>Preview coverage or run ingestion.</strong>
      <p>
        The workspace will show provider evidence first, then persisted
        normalized activity tables after a run is stored.
      </p>
    </div>
  );
}

function WalletIngestionLoading({
  action,
}: {
  action: "preview" | "run" | "read" | null;
}) {
  const label =
    action === "run"
      ? "RUNNING_MOCK_INGESTION"
      : action === "read"
        ? "READING_STORED_RUN"
        : "PREVIEWING_COVERAGE";

  return (
    <div className="state-box loading-box tonapi-wallet-state wallet-intelligence-state">
      <span className="spinner" />
      <div>
        <span className="state-kicker">{label}</span>
        <strong>Wallet ingestion request in progress.</strong>
        <p>Results will keep source status and limitations visible.</p>
      </div>
    </div>
  );
}

function WalletIngestionError({ message }: { message: string }) {
  return (
    <div className="state-box error-box tonapi-wallet-state wallet-intelligence-state">
      <span className="state-kicker">WALLET_INGESTION_FAILED</span>
      <strong>Wallet ingestion request failed.</strong>
      <p>{message}</p>
    </div>
  );
}
