import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  compareWalletRuns,
  getWalletIngestionRun,
  getWalletRunPnlPreview,
  getWalletRunSignals,
  previewWalletIngestion,
  runWalletIngestion,
  walletClusterCompareCsvExportUrl,
  walletClusterCompareExportUrl,
  walletRunExportCsvUrl,
  walletRunExportUrl,
  walletRunPnlPreviewCsvExportUrl,
  walletRunPnlPreviewExportUrl,
  walletRunSignalsCsvExportUrl,
  walletRunSignalsExportUrl,
} from "../api";
import type {
  TimeWindow,
  WalletActivityAcquisitionStreamEvidence,
  WalletActivityProviderEvidence,
  WalletActivitySummary,
  WalletBalanceSnapshotRecord,
  WalletClusterCompareResponse,
  WalletEvidenceSignalRecord,
  WalletIdentityRecord,
  WalletIngestionPreviewResponse,
  WalletIngestionRequest,
  WalletIngestionRunResponse,
  WalletIngestionSurface,
  WalletIngestionWarningRecord,
  WalletRunPnlPreviewResponse,
  WalletRunSignalsResponse,
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
    description: "Normalized swap-side activity",
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
  "Persisted source-labeled run",
  "Transfers",
  "Transactions",
  "Network-scoped transaction identity",
  "Transaction acquisition bounds and page evidence",
  "Swaps",
  "Balances",
  "Provider evidence",
  "Evidence signals and run-scoped PnL",
  "Wallet-pair similarity (probabilistic, not proof)",
];

const CANNOT_SHOW = [
  "Full-history acquisition cost basis",
  "Canonical transfer, swap-action, asset, and counterparty identity",
  "Legacy buyers/report wiring",
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
  const visibleAcquisitionStreams = runResult
    ? runResult.acquisition_streams ?? []
    : previewResult?.acquisition_streams ?? [];
  const visibleIncompleteSurfaces = runResult
    ? runResult.incomplete_surfaces ?? []
    : previewResult?.incomplete_surfaces ?? [];
  const visibleRequestedSurfaces = runResult
    ? runResult.requested_surfaces
    : previewResult?.requested_surfaces ?? [];
  const visibleAcquisitionContractPresent = runResult
    ? Array.isArray(runResult.acquisition_streams) &&
      Array.isArray(runResult.incomplete_surfaces)
    : previewResult
      ? Array.isArray(previewResult.acquisition_streams) &&
        Array.isArray(previewResult.incomplete_surfaces)
      : false;
  const visibleWarnings = runResult
    ? runResult.warnings.map((warning) => warning.message)
    : previewResult?.warnings ?? [];
  const displayedDataMode =
    runResult?.data_mode ?? previewResultDataMode(previewResult);
  const displayedIsLive = displayedDataMode === "real";
  const readiness = buildReadiness({
    busy,
    loadingAction,
    requestError,
    validationMessage,
    previewResult,
    runResult,
    resultIsStale,
    displayedDataMode,
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
      message: "Previewing source-labeled wallet activity coverage.",
      accountAddress: request.payload.wallet_address,
      limit: formatSurfaces(request.payload.surfaces),
    });

    try {
      const data = await previewWalletIngestion(request.payload);
      if (activeRequestId.current !== requestId) return;
      setPreviewResult(data);
      setResultSnapshot(snapshotForPayload(request.payload));
      const previewMode = previewResultDataMode(data);
      onPreviewRunStateChange?.({
        status: "success",
        message: `Coverage preview returned ${data.provider_coverage[0]?.normalized_count ?? 0} ${previewMode === "real" ? "live" : "mock-normalized"} rows.`,
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
            {displayedIsLive
              ? "Guarded live ingestion"
              : displayedDataMode === "mock"
                ? "Mock-normalized ingestion"
                : "Source-labeled ingestion"}
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
            className={`badge ${displayedIsLive ? "badge-real" : displayedDataMode === "mock" ? "badge-mock" : "badge-provider"}`}
          >
            {displayedIsLive
              ? "LIVE SOURCE"
              : displayedDataMode === "mock"
                ? "MOCK SOURCE"
                : "SOURCE PENDING"}
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
          {runResult && displayedIsLive
            ? "This run used the guarded live TonAPI path. Rows are real on-chain account data, persisted and source-labeled. Stored activity feeds signals; swaps and balances feed cluster comparison; swaps and transaction evidence feed the PnL preview below."
            : runResult
              ? "This run used deterministic backend fixtures. Rows are persisted and source-labeled. Stored activity feeds signals; swaps and balances feed cluster comparison; swaps and transaction evidence feed the PnL preview below. These are not real on-chain rows."
              : previewResult && displayedIsLive
                ? "This coverage preview used the guarded live TonAPI path. Returned rows are real account-level provider evidence but are not persisted until you run ingestion."
                : previewResult
                  ? "This coverage preview used deterministic backend fixtures. Preview rows are not persisted and are not real on-chain data."
                  : "Preview coverage first to confirm whether the configured path is guarded live TonAPI or deterministic mock data. Every result stays source-labeled."}
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
            <span
              className={`badge ${displayedIsLive ? "badge-real" : "badge-mock"}`}
            >
              SOURCE {displayedIsLive ? "LIVE" : "MOCK"}
            </span>
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

          {runResult && <WalletIdentityEvidence result={runResult} />}

          <div className="scope-strip">
            {runResult?.message ?? previewResult?.message}
          </div>

          <WalletIngestionMetrics result={runResult} preview={previewResult} />
          <ProviderEvidence evidence={visibleEvidence} />
          <AcquisitionEvidenceCard
            streams={visibleAcquisitionStreams}
            incompleteSurfaces={visibleIncompleteSurfaces}
            requestedSurfaces={visibleRequestedSurfaces}
            contractPresent={visibleAcquisitionContractPresent}
          />
          <WalletIngestionWarnings warnings={visibleWarnings} />

          {runResult?.activity_summary && (
            <ActivitySummaryCard summary={runResult.activity_summary} />
          )}
          {runResult && <WalletActivityTables result={runResult} />}
          {runResult?.run_id != null && (
            <WalletEvidenceSignalsCard runId={runResult.run_id} />
          )}
          {runResult?.run_id != null && (
            <WalletPnlPreviewCard runId={runResult.run_id} />
          )}
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
  displayedDataMode,
}: {
  busy: boolean;
  loadingAction: "preview" | "run" | "read" | null;
  requestError: string | null;
  validationMessage: string | null;
  previewResult: WalletIngestionPreviewResponse | null;
  runResult: WalletIngestionRunResponse | null;
  resultIsStale: boolean;
  displayedDataMode: "mock" | "real" | null;
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
      message: `Persisted ${displayedDataMode === "real" ? "live" : "mock-normalized"} wallet activity run matches current inputs.`,
    };
  }
  if (previewResult) {
    return {
      tone: "fresh",
      label: "COVERAGE READY",
      message: `Coverage preview matches current inputs. You can persist a ${displayedDataMode === "real" ? "guarded live" : "mock-normalized"} run.`,
    };
  }
  return {
    tone: "ready",
    label: "READY",
    message: "Ready to preview or persist source-labeled wallet activity.",
  };
}

function previewResultDataMode(
  preview: WalletIngestionPreviewResponse | null,
): "mock" | "real" | null {
  if (!preview) return null;
  return preview.provider_coverage.some((item) => item.data_mode === "real")
    ? "real"
    : "mock";
}

function activityCount(result: WalletIngestionRunResponse): number {
  return (
    result.transfers.length +
    result.transactions.length +
    result.swaps.length +
    result.balances.length
  );
}

function WalletIdentityEvidence({
  result,
}: {
  result: WalletIngestionRunResponse;
}) {
  const identity: WalletIdentityRecord = result.wallet_identity ?? {
    status: "unavailable",
    version: "unavailable",
    network: "ton-unknown",
    submitted_format: "unrecognized",
    is_account_existence_proof: false,
    is_ownership_proof: false,
  };
  const canonical = identity.canonical_address ?? "Unavailable";
  const workchain =
    identity.workchain_id == null
      ? "Workchain unavailable"
      : `Workchain ${identity.workchain_id}`;
  const bounce =
    identity.bounceable == null
      ? "Bounce flag unavailable"
      : identity.bounceable
        ? "Bounceable input"
        : "Non-bounceable input";
  const scopeDetail =
    identity.status === "network_scoped" && identity.canonical_address
      ? `${workchain}. Network scope is part of the identity key.`
      : `${workchain}. No network-scoped identity key is available.`;

  return (
    <div className="wallet-evidence-grid" aria-label="Persisted wallet identity">
      <div className="wallet-evidence-card">
        <span>Canonical wallet</span>
        <strong>{canonical}</strong>
        <p>The submitted address remains stored separately for audit.</p>
      </div>
      <div className="wallet-evidence-card">
        <span>TON scope</span>
        <strong>{identity.network}</strong>
        <p>{scopeDetail}</p>
      </div>
      <div className="wallet-evidence-card">
        <span>Identity contract</span>
        <strong>
          {identity.status} · {identity.version}
        </strong>
        <p>
          {identity.submitted_format} · {bounce}. Syntax identity only; not
          account-existence or ownership proof.
        </p>
      </div>
    </div>
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

function acquisitionStateClass(state: string): string {
  const normalized = state.trim().toLowerCase();
  if (normalized === "complete" || normalized === "completed") {
    return "source-badge source-real";
  }
  if (
    normalized === "incomplete" ||
    normalized === "partial" ||
    normalized === "failed" ||
    normalized === "error" ||
    normalized === "capped" ||
    normalized === "preview_only" ||
    normalized === "legacy_unavailable"
  ) {
    return "source-badge source-mock";
  }
  return "source-badge source-unknown";
}

function acquisitionValue(value: string | null | undefined): string {
  return value && value.length > 0 ? value : "∅";
}

function acquisitionRange(
  minimum: string | null | undefined,
  maximum: string | null | undefined,
): string {
  return acquisitionValue(minimum) + " → " + acquisitionValue(maximum);
}

function AcquisitionTimestamp({
  value,
}: {
  value: string | null | undefined;
}) {
  if (!value) return <span>∅</span>;
  return <time dateTime={value}>{value}</time>;
}

function succeededPageCount(
  stream: WalletActivityAcquisitionStreamEvidence,
): number {
  if (
    typeof stream.pages_succeeded === "number" &&
    Number.isFinite(stream.pages_succeeded) &&
    stream.pages_succeeded >= 0
  ) {
    return stream.pages_succeeded;
  }
  const pages = Array.isArray(stream.pages) ? stream.pages : [];
  return pages.filter((page) => !page.error_code && !page.error_message).length;
}

function AcquisitionEvidenceCard({
  streams,
  incompleteSurfaces,
  requestedSurfaces,
  contractPresent,
}: {
  streams: WalletActivityAcquisitionStreamEvidence[];
  incompleteSurfaces: WalletIngestionSurface[];
  requestedSurfaces: WalletIngestionSurface[];
  contractPresent: boolean;
}) {
  const safeStreams = Array.isArray(streams) ? streams : [];
  const safeIncompleteSurfaces = Array.isArray(incompleteSurfaces)
    ? incompleteSurfaces
    : [];
  const safeRequestedSurfaces = Array.isArray(requestedSurfaces)
    ? requestedSurfaces
    : [];
  const everyStreamBounded =
    safeStreams.length > 0 &&
    safeStreams.every((stream) => stream.bounds_verified === true);
  const incompleteSummary = contractPresent
    ? "INCOMPLETE " + safeIncompleteSurfaces.length
    : "INCOMPLETE UNKNOWN";
  const surfaceStateHeading = !contractPresent
    ? "Incomplete-surface evidence unavailable"
    : safeIncompleteSurfaces.length > 0
      ? "Incomplete surfaces"
      : "No surface marked incomplete";

  return (
    <section
      className="intelligence-table-block acquisition-evidence-card"
      aria-label="Wallet activity acquisition evidence"
    >
      <div className="table-toolbar acquisition-evidence-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Acquisition contract</span>
          <h2>Stream and pagination evidence</h2>
          <p>
            Each stream is scoped only to its recorded cursor chain and exact
            half-open UTC interval. A complete account-events chain verifies
            provider page traversal only: its derived transfer and swap actions
            remain mutable display data, not PnL or acquisition cost basis.
          </p>
        </div>
        <div className="table-meta" aria-label="Acquisition evidence summary">
          <span className="badge badge-provider">
            STREAMS {safeStreams.length}
          </span>
          <span
            className={
              "badge " +
              (!contractPresent || safeIncompleteSurfaces.length > 0
                ? "badge-mock"
                : "badge-provider")
            }
          >
            {incompleteSummary}
          </span>
          <span
            className={
              "badge " + (everyStreamBounded ? "badge-real" : "badge-mock")
            }
          >
            {everyStreamBounded ? "BOUNDS VERIFIED" : "BOUNDS UNVERIFIED"}
          </span>
        </div>
      </div>

      <div
        className={
          "acquisition-surface-state" +
          (!contractPresent || safeIncompleteSurfaces.length > 0
            ? " acquisition-surface-state-warning"
            : "")
        }
        role="status"
      >
        <strong>{surfaceStateHeading}</strong>
        <div>
          {!contractPresent ? (
            <span className="muted small">
              Legacy response: treat every requested surface as unverified.
            </span>
          ) : safeIncompleteSurfaces.length > 0 ? (
            safeIncompleteSurfaces.map((surface) => (
              <span className="source-badge source-mock" key={surface}>
                {surfaceLabel(surface)}
              </span>
            ))
          ) : (
            <span className="muted small">
              This is not a claim that every requested surface is complete.
            </span>
          )}
        </div>
      </div>

      {safeStreams.length === 0 ? (
        <div className="acquisition-evidence-empty">
          <strong>No stream-level acquisition evidence returned</strong>
          <p>
            Treat pagination and requested bounds as unverified for{" "}
            {safeRequestedSurfaces.length > 0
              ? formatSurfaces(safeRequestedSurfaces)
              : "the requested surfaces"}
            . Legacy responses may not contain this contract.
          </p>
        </div>
      ) : (
        <div className="acquisition-stream-list">
          {safeStreams.map((stream) => (
            <AcquisitionStreamEvidence
              key={[
                stream.provider,
                stream.stream_key,
                acquisitionValue(stream.requested_start),
              ].join(":")}
              stream={stream}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function AcquisitionStreamEvidence({
  stream,
}: {
  stream: WalletActivityAcquisitionStreamEvidence;
}) {
  const pages = Array.isArray(stream.pages) ? stream.pages : [];
  const pagesSucceeded = succeededPageCount(stream);
  const queryFilters = JSON.stringify(stream.query_filters ?? {});

  return (
    <article className="acquisition-stream">
      <div className="acquisition-stream-head">
        <div>
          <span>{stream.provider}</span>
          <h3>{stream.stream_key}</h3>
          <p>
            {stream.contract_version} · {stream.scope_kind} · {stream.sort_order} ·
            page {stream.page_size}/{stream.page_cap}
          </p>
        </div>
        <span className={acquisitionStateClass(stream.completion_state)}>
          {stream.completion_state}
        </span>
      </div>

      {stream.scope_kind === "provider_display_events" && (
        <div className="acquisition-display-note" role="note">
          <strong>Provider display stream</strong>
          <span>
            Completion applies only to this TonAPI event page chain. Derived
            transfer and swap actions can change and remain incomplete,
            non-authoritative evidence.
          </span>
        </div>
      )}

      <div className="acquisition-stream-grid">
        <div className="acquisition-stream-bound">
          <span>UTC half-open bounds</span>
          <code>
            [<AcquisitionTimestamp value={stream.requested_start} />,{" "}
            <AcquisitionTimestamp value={stream.requested_end} />)
          </code>
        </div>
        <div>
          <span>Bounds contract</span>
          <strong>{stream.bounds_verified ? "Verified" : "Unverified"}</strong>
        </div>
        <div>
          <span>Pages succeeded / attempted</span>
          <strong>
            {pagesSucceeded} / {stream.page_count}
          </strong>
        </div>
        <div>
          <span>Normalized / raw / duplicates</span>
          <strong>
            {stream.normalized_count} / {stream.raw_count} /{" "}
            {stream.duplicate_count}
          </strong>
        </div>
        <div>
          <span>Termination reason</span>
          <strong>{acquisitionValue(stream.termination_reason)}</strong>
        </div>
        <div>
          <span>Cursor: first → terminal</span>
          <code>
            {acquisitionRange(stream.first_cursor, stream.terminal_cursor)}
          </code>
        </div>
      </div>

      {(stream.error_code || stream.error_message) && (
        <div className="acquisition-stream-error" role="alert">
          <strong>{acquisitionValue(stream.error_code)}</strong>
          <span>{acquisitionValue(stream.error_message)}</span>
        </div>
      )}

      <details className="acquisition-page-details">
        <summary>
          <span>Page evidence</span>
          <span>
            {pages.length} record{pages.length === 1 ? "" : "s"}
          </span>
        </summary>
        <div className="acquisition-stream-contract">
          <span>
            Filters <code>{queryFilters}</code>
          </span>
          <span>
            Stream UTC{" "}
            <AcquisitionTimestamp value={stream.started_at} />
            {" → "}
            <AcquisitionTimestamp value={stream.finished_at} />
          </span>
        </div>
        {pages.length === 0 ? (
          <p className="acquisition-page-empty">
            No page-level evidence records were returned.
          </p>
        ) : (
          <div className="table-wrap acquisition-page-table-wrap">
            <table
              className="data-table acquisition-page-table"
              aria-label={
                "Page-level acquisition evidence for " + stream.stream_key
              }
            >
              <thead>
                <tr>
                  <th>Page</th>
                  <th>Cursor</th>
                  <th>Rows</th>
                  <th>Logical time</th>
                  <th>Activity UTC</th>
                  <th>Fetch evidence</th>
                </tr>
              </thead>
              <tbody>
                {pages.map((page) => {
                  const pageFailed = Boolean(
                    page.error_code || page.error_message,
                  );
                  return (
                    <tr
                      key={[
                        page.page_index,
                        page.request_cursor ?? "root",
                      ].join(":")}
                    >
                      <td>
                        <strong>#{page.page_index}</strong>
                        <span
                          className={
                            pageFailed
                              ? "source-badge source-mock"
                              : "source-badge source-real"
                          }
                        >
                          {pageFailed ? "FAILED" : "SUCCEEDED"}
                        </span>
                        <small>
                          {page.attempt_count} attempt
                          {page.attempt_count === 1 ? "" : "s"} · limit{" "}
                          {page.requested_limit}
                        </small>
                      </td>
                      <td>
                        <code>
                          {acquisitionRange(
                            page.request_cursor,
                            page.response_cursor,
                          )}
                        </code>
                        <small>request → response</small>
                      </td>
                      <td>
                        <strong>
                          {page.normalized_count} / {page.raw_count}
                        </strong>
                        <small>normalized / raw</small>
                        <small>{page.duplicate_count} duplicates</small>
                      </td>
                      <td>
                        <code>
                          {acquisitionRange(
                            page.min_logical_time,
                            page.max_logical_time,
                          )}
                        </code>
                        <small>minimum → maximum</small>
                      </td>
                      <td>
                        <code>
                          {acquisitionRange(
                            page.min_timestamp,
                            page.max_timestamp,
                          )}
                        </code>
                        <small>minimum → maximum</small>
                      </td>
                      <td>
                        <AcquisitionTimestamp value={page.fetched_at} />
                        <small>
                          Digest{" "}
                          <code title={page.response_digest}>
                            {acquisitionValue(page.response_digest)}
                          </code>
                        </small>
                        {pageFailed && (
                          <small className="acquisition-page-error">
                            {acquisitionValue(page.error_code)} ·{" "}
                            {acquisitionValue(page.error_message)}
                          </small>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </article>
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

function confidenceBadgeClass(
  confidence: WalletEvidenceSignalRecord["confidence"] | "unavailable",
): string {
  switch (confidence) {
    case "high":
      return "badge-group";
    case "medium":
      return "badge-warning";
    default:
      return "badge-provider";
  }
}

function formatSignalEvidence(evidence: Record<string, unknown>): string {
  const entries = Object.entries(evidence);
  if (entries.length === 0) {
    return "-";
  }
  return entries
    .map(([key, value]) => {
      const rendered =
        typeof value === "object" && value !== null
          ? JSON.stringify(value)
          : String(value);
      return `${key}=${rendered}`;
    })
    .join(", ");
}

function WalletEvidenceSignalsCard({ runId }: { runId: number }) {
  const [loading, setLoading] = useState(true);
  const [signalsError, setSignalsError] = useState<string | null>(null);
  const [signalsResult, setSignalsResult] =
    useState<WalletRunSignalsResponse | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setSignalsError(null);
    setSignalsResult(null);
    getWalletRunSignals(runId)
      .then((data) => {
        if (!cancelled) {
          setSignalsResult(data);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setSignalsError(
            err instanceof Error ? err.message : "Wallet signals read failed.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  return (
    <div className="intelligence-table-block" aria-label="Wallet evidence signals">
      <div className="table-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Heuristic observations — not a verdict</span>
          <h2>Evidence signals</h2>
          <p>
            Rule-based observations derived only from the stored rows of run
            #{runId}. Each signal explains the evidence behind it; absence of a
            signal is not clearance.
          </p>
        </div>
        <div className="table-meta">
          <span className="badge badge-mock">NOT A RISK SCORE</span>
        </div>
      </div>

      {loading && <p className="muted small">Deriving evidence signals…</p>}
      {signalsError && <WalletIngestionError message={signalsError} />}

      {signalsResult && (
        <>
          <div className="tonapi-wallet-result-head">
            <a
              className="btn btn-ghost"
              href={walletRunSignalsExportUrl(runId)}
              download
            >
              Export signals (JSON)
            </a>
            <a
              className="btn btn-ghost"
              href={walletRunSignalsCsvExportUrl(runId)}
              download
            >
              Export signals (CSV)
            </a>
          </div>
          {signalsResult.signals.length > 0 ? (
            <table className="data-table intelligence-table wallet-ingestion-table">
              <thead>
                <tr>
                  <th>Signal</th>
                  <th>Confidence</th>
                  <th>Observation</th>
                  <th>Evidence</th>
                </tr>
              </thead>
              <tbody>
                {signalsResult.signals.map((signal) => (
                  <tr key={signal.code}>
                    <td>{signal.title}</td>
                    <td>
                      <span
                        className={`badge ${confidenceBadgeClass(signal.confidence)}`}
                      >
                        {signal.confidence.toUpperCase()}
                      </span>
                    </td>
                    <td>{signal.observation}</td>
                    <td>{formatSignalEvidence(signal.evidence)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted small">
              No evidence signals were derived from the stored rows of this run.
            </p>
          )}
          {signalsResult.signals.map((signal) => (
            <p className="muted small" key={`note-${signal.code}`}>
              {signal.note}
            </p>
          ))}
          {signalsResult.insufficient_evidence.length > 0 && (
            <p className="muted small">
              Insufficient evidence:{" "}
              {signalsResult.insufficient_evidence
                .map((item) => `${item.code} — ${item.reason}`)
                .join("; ")}
            </p>
          )}
          {signalsResult.evaluated.length > 0 && (
            <p className="muted small">
              Evaluated rules: {signalsResult.evaluated.join(", ")}
            </p>
          )}
          <p className="muted small">{signalsResult.note}</p>
        </>
      )}
    </div>
  );
}

const PNL_MODE_LABELS: Record<WalletRunPnlPreviewResponse["pnl_mode"], string> = {
  imported_pnl: "IMPORTED PNL",
  estimated_onchain_pnl: "ESTIMATED ON-CHAIN",
  real_pnl_locked: "REAL PNL LOCKED",
  insufficient_data: "INSUFFICIENT DATA",
  real_pnl: "REAL PNL (IN-WINDOW)",
};

function WalletPnlPreviewCard({ runId }: { runId: number }) {
  const [loading, setLoading] = useState(true);
  const [includeHistorical, setIncludeHistorical] = useState(false);
  const [includeUnrealized, setIncludeUnrealized] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [pnlResult, setPnlResult] =
    useState<WalletRunPnlPreviewResponse | null>(null);
  const [pnlResultScope, setPnlResultScope] = useState<{
    runId: number;
    includeHistorical: boolean;
    includeUnrealized: boolean;
  } | null>(null);
  const loadedPnlRunId = useRef(runId);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setPreviewError(null);
    if (loadedPnlRunId.current !== runId) {
      loadedPnlRunId.current = runId;
      setPnlResult(null);
      setPnlResultScope(null);
    }
    getWalletRunPnlPreview(runId, includeHistorical, includeUnrealized)
      .then((data) => {
        if (!cancelled) {
          setPnlResult(data);
          setPnlResultScope({
            runId,
            includeHistorical,
            includeUnrealized,
          });
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setPreviewError(
            err instanceof Error
              ? err.message
              : "Wallet PnL preview read failed.",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [runId, includeHistorical, includeUnrealized]);

  function toggleHistorical() {
    if (includeHistorical) {
      setIncludeHistorical(false);
      setIncludeUnrealized(false);
      return;
    }
    setIncludeHistorical(true);
  }

  function toggleUnrealized() {
    const nextValue = !includeUnrealized;
    setIncludeUnrealized(nextValue);
    if (nextValue) setIncludeHistorical(true);
  }

  const canRenderUnrealized =
    pnlResultScope?.runId === runId &&
    pnlResultScope.includeUnrealized;
  const displayedIncludeHistorical =
    pnlResultScope?.runId === runId && pnlResultScope.includeHistorical;
  const displayedIncludeUnrealized =
    pnlResultScope?.runId === runId && pnlResultScope.includeUnrealized;

  return (
    <div className="intelligence-table-block" aria-label="Wallet PnL preview">
      <div className="table-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">
            {pnlResult && !pnlResult.real_pnl_locked
              ? "In-window realized Real PnL — evidence-complete"
              : "Estimated preview — not Real PnL"}
          </span>
          <h2>PnL preview</h2>
          <p>
            TON-denominated realized swap flows estimated only from the stored
            swap rows of run #{runId}. Non-TON swap legs, transfers, and
            activity outside this run are excluded. Spot-based unrealized
            valuation is optional, informational, and kept separate from
            realized figures. Real PnL unlocks only when every evidence
            requirement below is available.
          </p>
        </div>
        <div className="table-meta">
          {pnlResult && !pnlResult.real_pnl_locked ? (
            <span className="badge badge-real">REAL PNL (IN-WINDOW)</span>
          ) : (
            <span className="badge badge-mock">REAL PNL LOCKED</span>
          )}
        </div>
      </div>

      {loading && (
        <p className="muted small">
          {pnlResult
            ? "Refreshing PnL preview; the last successful result remains visible."
            : "Deriving PnL preview…"}
        </p>
      )}
      {previewError && <WalletIngestionError message={previewError} />}
      {previewError && pnlResult && (
        <p className="muted small">
          Requested enrichment failed; showing the last successful preview.
        </p>
      )}

      {pnlResult && (
        <>
          <div className="tonapi-wallet-result-head">
            <span className="badge badge-provider">
              MODE {PNL_MODE_LABELS[pnlResult.pnl_mode]}
            </span>
            <span
              className={`badge ${confidenceBadgeClass(pnlResult.confidence)}`}
            >
              CONFIDENCE {pnlResult.confidence.toUpperCase()}
            </span>
            <a
              className="btn btn-ghost"
              href={walletRunPnlPreviewExportUrl(
                runId,
                displayedIncludeHistorical,
                displayedIncludeUnrealized,
              )}
              download
            >
              Export preview (JSON)
            </a>
            <a
              className="btn btn-ghost"
              href={walletRunPnlPreviewCsvExportUrl(
                runId,
                displayedIncludeHistorical,
                displayedIncludeUnrealized,
              )}
              download
            >
              Export preview (CSV)
            </a>
            <button
              className="btn btn-ghost"
              type="button"
              aria-pressed={includeHistorical}
              onClick={toggleHistorical}
              disabled={loading}
            >
              {includeHistorical
                ? "Hide USD valuation"
                : "Add USD valuation (historical)"}
            </button>
            <button
              className="btn btn-ghost"
              type="button"
              aria-pressed={includeUnrealized}
              onClick={toggleUnrealized}
              disabled={loading}
            >
              {includeUnrealized
                ? "Hide unrealized valuation"
                : "Add unrealized valuation (spot)"}
            </button>
          </div>
          {canRenderUnrealized && (
            <p className="muted small">
              JSON/CSV exports match the last successfully displayed historical
              and spot scope; unavailable holdings remain separate from the
              priced subtotal.
            </p>
          )}
          {(loading || previewError) && pnlResultScope?.runId === runId && (
            <p className="muted small">
              Export links keep the last successful result scope until the
              requested refresh succeeds.
            </p>
          )}

          {pnlResult.token_flows.length > 0 ? (
            <div className="table-wrap">
              <table className="data-table intelligence-table wallet-ingestion-table">
                <thead>
                  <tr>
                    <th>Token</th>
                    <th>Buys</th>
                    <th>Sells</th>
                    <th>TON spent</th>
                    <th>TON received</th>
                    <th>Net TON flow</th>
                    <th>Fees (TON)</th>
                    <th>Net after fees</th>
                  </tr>
                </thead>
                <tbody>
                  {pnlResult.token_flows.map((flow) => (
                    <tr key={flow.token}>
                      <td>{flow.token}</td>
                      <td>{flow.buy_swap_count}</td>
                      <td>{flow.sell_swap_count}</td>
                      <td>{flow.ton_spent}</td>
                      <td>{flow.ton_received}</td>
                      <td>{flow.net_ton_flow}</td>
                      <td>{flow.fee_ton}</td>
                      <td>{flow.net_ton_flow_after_fees}</td>
                    </tr>
                  ))}
                  <tr>
                    <td>Total</td>
                    <td colSpan={2} />
                    <td>{pnlResult.total_ton_spent}</td>
                    <td>{pnlResult.total_ton_received}</td>
                    <td>{pnlResult.net_ton_flow}</td>
                    <td>{pnlResult.total_fees_ton}</td>
                    <td>{pnlResult.net_ton_flow_after_fees}</td>
                  </tr>
                </tbody>
              </table>
            </div>
          ) : (
            <p className="muted small">
              No TON-denominated swap flows could be estimated from the stored
              rows of this run.
            </p>
          )}

          <p className="muted small">
            Swap rows used: {pnlResult.swaps_used}; excluded:{" "}
            {pnlResult.swaps_excluded}.
          </p>

          {pnlResult.usd_flows.length > 0 && (
            <>
              <div className="table-toolbar-main">
                <span className="section-eyebrow">
                  USD-valued swap legs — historical prices, not cost basis
                </span>
              </div>
              <div className="table-wrap">
                <table className="data-table intelligence-table wallet-ingestion-table">
                  <thead>
                    <tr>
                      <th>Token</th>
                      <th>Matched swaps</th>
                      <th>USD spent</th>
                      <th>USD received</th>
                      <th>Net USD flow</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pnlResult.usd_flows.map((flow) => (
                      <tr key={`usd-${flow.token}`}>
                        <td>{flow.token}</td>
                        <td>{flow.matched_swap_count}</td>
                        <td>{flow.usd_spent}</td>
                        <td>{flow.usd_received}</td>
                        <td>{flow.net_usd_flow}</td>
                      </tr>
                    ))}
                    <tr>
                      <td>Total</td>
                      <td />
                      <td>{pnlResult.total_usd_spent ?? "-"}</td>
                      <td>{pnlResult.total_usd_received ?? "-"}</td>
                      <td>{pnlResult.net_usd_flow ?? "-"}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </>
          )}
          {pnlResult.realized_pnl && pnlResult.realized_pnl.length > 0 && (
            <>
              <div className="table-toolbar-main">
                <span className="section-eyebrow">
                  Realized PnL — in-window cost basis (USD)
                </span>
              </div>
              <div className="table-wrap">
                <table className="data-table intelligence-table wallet-ingestion-table">
                  <thead>
                    <tr>
                      <th>Token</th>
                      <th>Status</th>
                      <th>Sells</th>
                      <th>Proceeds</th>
                      <th>Cost basis</th>
                      <th>Realized PnL</th>
                      <th>Remaining qty</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pnlResult.realized_pnl.map((record) => (
                      <tr key={`realized-${record.token}`}>
                        <td>{record.token}</td>
                        <td>
                          <span
                            className={`badge ${
                              record.status === "computed"
                                ? "badge-group"
                                : "badge-warning"
                            }`}
                          >
                            {record.status.toUpperCase()}
                          </span>
                        </td>
                        <td>{record.sell_leg_count}</td>
                        <td>{record.proceeds_usd ?? "-"}</td>
                        <td>{record.cost_basis_usd ?? "-"}</td>
                        <td>{record.realized_pnl_usd ?? "-"}</td>
                        <td>{record.remaining_qty ?? "-"}</td>
                      </tr>
                    ))}
                    {pnlResult.total_realized_pnl_usd != null && (
                      <tr>
                        <td>Total</td>
                        <td colSpan={4} />
                        <td>{pnlResult.total_realized_pnl_usd}</td>
                        <td />
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {pnlResult.realized_pnl
                .filter((record) => record.reason)
                .map((record) => (
                  <p
                    className="muted small"
                    key={`realized-reason-${record.token}`}
                  >
                    {record.token}: {record.reason}
                  </p>
                ))}
            </>
          )}
          {canRenderUnrealized && pnlResult.unrealized.length > 0 && (
            <>
              <div className="table-toolbar">
                <div className="table-toolbar-main">
                  <span className="section-eyebrow">
                    Unrealized PnL — spot valuation evidence (USD)
                  </span>
                  <p>
                    Remaining in-window holdings only. Row-level sources
                    distinguish deterministic mock pricing from real provider
                    pricing; these figures do not change realized PnL or its
                    evidence checklist.
                  </p>
                </div>
                <div className="table-meta">
                  <span className="badge badge-warning">
                    INFORMATIONAL ONLY
                  </span>
                </div>
              </div>
              <div className="table-wrap">
                <table className="data-table intelligence-table wallet-ingestion-table">
                  <thead>
                    <tr>
                      <th>Token</th>
                      <th>Status</th>
                      <th>Remaining qty</th>
                      <th>Remaining cost</th>
                      <th>Spot price</th>
                      <th>Spot source</th>
                      <th>Market value</th>
                      <th>Unrealized PnL</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pnlResult.unrealized.map((record) => (
                      <tr key={`unrealized-${record.token}`}>
                        <td>{record.token}</td>
                        <td>
                          <span
                            className={`badge ${
                              record.status === "computed"
                                ? "badge-group"
                                : "badge-warning"
                            }`}
                          >
                            {record.status.toUpperCase()}
                          </span>
                        </td>
                        <td title={record.remaining_qty ?? undefined}>
                          {formatPnlNumber(record.remaining_qty)}
                        </td>
                        <td title={record.remaining_cost_usd ?? undefined}>
                          {formatPnlUsd(record.remaining_cost_usd)}
                        </td>
                        <td title={record.spot_price_usd ?? undefined}>
                          {formatPnlUsd(record.spot_price_usd, 8)}
                        </td>
                        <td>{record.priced_by?.toUpperCase() ?? "-"}</td>
                        <td title={record.market_value_usd ?? undefined}>
                          {formatPnlUsd(record.market_value_usd)}
                        </td>
                        <td
                          className={pnlValueClass(record.unrealized_pnl_usd)}
                          title={record.unrealized_pnl_usd ?? undefined}
                        >
                          {formatPnlUsd(record.unrealized_pnl_usd)}
                        </td>
                      </tr>
                    ))}
                    {pnlResult.total_unrealized_pnl_usd != null && (
                      <tr>
                        <td>Priced subtotal</td>
                        <td colSpan={6} />
                        <td
                          className={pnlValueClass(
                            pnlResult.total_unrealized_pnl_usd,
                          )}
                          title={pnlResult.total_unrealized_pnl_usd}
                        >
                          {formatPnlUsd(pnlResult.total_unrealized_pnl_usd)}
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              {pnlResult.unrealized
                .filter((record) => record.reason)
                .map((record) => (
                  <p
                    className="muted small"
                    key={`unrealized-reason-${record.token}`}
                  >
                    {record.token}: {record.reason}
                  </p>
                ))}
              {pnlResult.unrealized_note && (
                <p className="muted small">{pnlResult.unrealized_note}</p>
              )}
              <p className="muted small">
                Spot coverage: {pnlResult.unrealized.filter(
                  (record) => record.status === "computed",
                ).length}
                /{pnlResult.unrealized.length} holding(s) priced. Unavailable
                holdings are excluded from the priced subtotal.
              </p>
            </>
          )}
          {canRenderUnrealized && pnlResult.unrealized.length === 0 && (
            <p className="muted small">
              No spot-valued positions were returned. This can mean there is
              no remaining in-window inventory or that prerequisite pricing
              or cost-basis evidence is unavailable; review the evidence
              requirements and warnings below.
            </p>
          )}
          {pnlResult.historical_pricing && (
            <p className="muted small">
              Historical pricing: source{" "}
              {pnlResult.historical_pricing.source_status.toUpperCase()};{" "}
              {pnlResult.historical_pricing.points_fetched} points;{" "}
              {pnlResult.historical_pricing.swaps_matched} matched /{" "}
              {pnlResult.historical_pricing.swaps_unmatched} unmatched swap
              leg(s); tolerance{" "}
              {pnlResult.historical_pricing.tolerance_seconds / 3600}h.{" "}
              {pnlResult.historical_pricing.note}
            </p>
          )}

          <div className="table-toolbar-main">
            <span className="section-eyebrow">Real PnL evidence requirements</span>
          </div>
          {pnlResult.requirements.map((requirement) => (
            <p className="muted small" key={requirement.code}>
              <span
                className={`badge ${
                  requirement.available ? "badge-group" : "badge-warning"
                }`}
              >
                {requirement.available ? "AVAILABLE" : "MISSING"}
              </span>{" "}
              {requirement.code}
              {requirement.reason ? ` — ${requirement.reason}` : ""}
            </p>
          ))}

          {pnlResult.warnings.map((warning) => (
            <p className="muted small" key={warning}>
              {warning}
            </p>
          ))}
          <p className="muted small">{pnlResult.note}</p>
        </>
      )}
    </div>
  );
}

function pnlValueClass(value: string | null | undefined): string {
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "pnl-zero";
  return parsed > 0 ? "pnl-pos" : "pnl-neg";
}

function formatPnlNumber(
  value: string | null | undefined,
  maximumFractionDigits = 6,
  minimumFractionDigits = 0,
): string {
  if (value == null) return "-";
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return value;
  return new Intl.NumberFormat("en-US", {
    minimumFractionDigits,
    maximumFractionDigits,
  }).format(parsed);
}

function formatPnlUsd(
  value: string | null | undefined,
  maximumFractionDigits = 2,
): string {
  if (value == null) return "-";
  return `$${formatPnlNumber(value, maximumFractionDigits, 2)}`;
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
      description="Live low-level rows can expose a network-scoped account + LT + hash identity. The tuple is useful for deduplication evidence but is not locally proof-verified."
      count={transactions.length}
    >
      {transactions.length === 0 ? (
        <EmptyTable message="Transactions were not requested or no rows were returned." />
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table wallet-ingestion-table">
            <thead>
              <tr>
                <th>Tx</th>
                <th>Identity</th>
                <th>Time</th>
                <th className="num">Fee TON</th>
                <th>Status</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {transactions.map((item, index) => {
                const identity = item.transaction_identity;
                const scoped =
                  identity?.status === "network_scoped" &&
                  identity.is_deduplication_identity;
                return (
                  <tr key={`${item.tx_hash}:${index}`}>
                    <td className="mono">{item.tx_hash}</td>
                    <td title={identity?.key ?? "No persisted transaction identity"}>
                      <span
                        className={`source-badge ${scoped ? "source-real" : "source-unknown"}`}
                      >
                        {scoped ? "SCOPED TX ID" : "ID UNAVAILABLE"}
                      </span>
                      <div className="muted small">
                        {identity?.network ?? "ton-unknown"} · proof not verified
                      </div>
                    </td>
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
                );
              })}
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
