import { useEffect, useState, type ReactNode } from "react";
import { analyze, API_BASE, getProvidersStatus } from "./api";
import type { AnalysisResult, ProvidersStatus, TimeWindow } from "./types";
import PoolUrlInput from "./components/PoolUrlInput";
import TimeWindowPicker from "./components/TimeWindowPicker";
import ProviderStatus from "./components/ProviderStatus";
import TokenOverview from "./components/TokenOverview";
import BuyersTable from "./components/BuyersTable";
import WalletGroups from "./components/WalletGroups";
import CommonHoldings from "./components/CommonHoldings";
import InterestingWallets from "./components/InterestingWallets";
import ExportButtons from "./components/ExportButtons";
import HistoricalPricesPreviewPanel from "./components/HistoricalPricesPreviewPanel";
import ImportPreviewPanel from "./components/ImportPreviewPanel";
import BitqueryTokenTradesPanel from "./components/BitqueryTokenTradesPanel";
import StonfiPoolsPreviewPanel from "./components/StonfiPoolsPreviewPanel";
import TonapiAccountJettonsPreviewPanel from "./components/TonapiAccountJettonsPreviewPanel";
import TonapiWalletIntelligencePreviewPanel from "./components/TonapiWalletIntelligencePreviewPanel";
import WalletIngestionWorkspace from "./components/WalletIngestionWorkspace";
import type { ProviderPreviewRunUpdate } from "./components/providerPreviewUtils";

const SAMPLE_URL =
  "https://www.geckoterminal.com/ton/pools/EQCp_C-wPq2Z-mock-pool";
const RELEASE_LABEL = "v0.22.1 MIGRATION FOUNDATION";

const navItems = [
  "DASHBOARD",
  "PROVIDERS",
  "WALLETS",
  "JETTONS",
  "STON.fi",
  "REPORTS",
  "SETTINGS",
];

type WorkspaceView = "ingestion" | "wallet" | "jettons" | "pools";
type WorkspaceRunStatus =
  | "idle"
  | "queued"
  | "running"
  | "success"
  | "error"
  | "stale";

interface WorkspaceRunState {
  target: WorkspaceView;
  status: WorkspaceRunStatus;
  message: string;
  accountLabel: string;
  limitLabel: string;
  updatedAt: string;
}

const workspaceTargets: Record<
  WorkspaceView,
  {
    label: string;
    targetId: string;
    requiresAccount: boolean;
  }
> = {
  ingestion: {
    label: "Wallet Activity Ingestion Workspace",
    targetId: "wallet-ingestion-workspace",
    requiresAccount: true,
  },
  wallet: {
    label: "TonAPI Wallet Intelligence Preview",
    targetId: "wallet-intelligence-preview",
    requiresAccount: true,
  },
  jettons: {
    label: "TonAPI Account Jettons Preview",
    targetId: "account-jettons-preview",
    requiresAccount: true,
  },
  pools: {
    label: "STON.fi Pools Preview",
    targetId: "stonfi-pools-preview",
    requiresAccount: false,
  },
};

function clampWorkspaceLimit(value: string): number | null {
  if (!value.trim()) return 10;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.min(100, Math.max(1, Math.trunc(parsed)));
}

function formatRunTime(date: Date): string {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function App() {
  const [poolUrl, setPoolUrl] = useState(SAMPLE_URL);
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("24h");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  const [workspaceAccount, setWorkspaceAccount] = useState("");
  const [workspaceLimit, setWorkspaceLimit] = useState("10");
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("ingestion");
  const [workspaceHint, setWorkspaceHint] = useState<string | null>(null);
  const [workspaceRunRequest, setWorkspaceRunRequest] = useState({
    target: "ingestion" as WorkspaceView,
    id: 0,
  });
  const [workspaceRunState, setWorkspaceRunState] =
    useState<WorkspaceRunState | null>(null);

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<AnalysisResult | null>(null);

  const [providers, setProviders] = useState<ProvidersStatus | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);

  // Load provider/data-mode status once on mount.
  useEffect(() => {
    getProvidersStatus()
      .then(setProviders)
      .catch((e) =>
        setProvidersError(e instanceof Error ? e.message : "Unknown error"),
      );
  }, []);

  const dataMode = result?.data_quality.mode ?? providers?.data_mode ?? "unknown";
  const providerSnapshot = result?.providers ?? providers;
  const availableProviders = providerSnapshot
    ? [
        providerSnapshot.geckoterminal,
        providerSnapshot.stonfi,
        providerSnapshot.tonapi,
        providerSnapshot.wallet_activity,
        providerSnapshot.bitquery,
        providerSnapshot.ton_provider,
      ].filter((item) => item?.available).length
    : 0;
  const providerTotal = providerSnapshot
    ? [
        providerSnapshot.geckoterminal,
        providerSnapshot.stonfi,
        providerSnapshot.tonapi,
        providerSnapshot.wallet_activity,
        providerSnapshot.bitquery,
        providerSnapshot.ton_provider,
      ].filter(Boolean).length
    : 0;
  const providerBadge = providerSnapshot
    ? {
        label: `PROVIDERS ${availableProviders}/${providerTotal}`,
        className: "badge badge-provider",
      }
    : providersError
      ? { label: "PROVIDERS ERROR", className: "badge badge-warning" }
      : { label: "PROVIDERS LOADING", className: "badge badge-provider" };
  const dataBadge =
    dataMode === "mock"
      ? { label: "DATA MODE MOCK", className: "badge badge-mock" }
      : dataMode === "real"
        ? { label: "DATA MODE REAL", className: "badge badge-real" }
        : { label: "DATA MODE UNKNOWN", className: "badge badge-provider" };
  const sourceLabel =
    dataMode === "real"
      ? "LIVE/PREVIEW"
      : dataMode === "mock"
        ? "MOCK/OFFLINE"
        : "STATUS UNKNOWN";
  const sourceBadgeClass =
    dataMode === "real"
      ? "badge badge-real"
      : dataMode === "mock"
        ? "badge badge-mock"
        : "badge badge-warning";
  const bannerText =
    dataMode === "mock"
      ? "Mock mode is active. No real on-chain wallet data is used."
      : dataMode === "real"
        ? "Provider previews may use real sources, while legacy wallet buyers, PnL and clusters remain mock-aware."
        : "Provider status is unavailable. Preview scopes remain visible; legacy wallet buyers, PnL and clusters remain mock-aware.";

  async function handleAnalyze() {
    if (!poolUrl.trim()) {
      setError("Please enter a pool URL.");
      return;
    }
    if (timeWindow === "custom") {
      if (!customStart || !customEnd) {
        setError("Please choose both a start and end date for a custom window.");
        return;
      }
      if (new Date(customStart) >= new Date(customEnd)) {
        setError("Custom range end must be after the start.");
        return;
      }
    }

    setLoading(true);
    setError(null);
    try {
      const data = await analyze({
        pool_url: poolUrl.trim(),
        time_window: timeWindow,
        custom_start:
          timeWindow === "custom"
            ? new Date(customStart).toISOString()
            : undefined,
        custom_end:
          timeWindow === "custom"
            ? new Date(customEnd).toISOString()
            : undefined,
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }

  function markWorkspaceInputsChanged(nextAccount: string, nextLimit: string) {
    const target = workspaceTargets[workspaceView];

    setWorkspaceHint(null);
    setWorkspaceRunState((current) =>
      current
        ? {
            ...current,
            status: "stale",
            message:
              "Shared inputs changed. Run the selected preview again for current scoped data.",
            accountLabel: target.requiresAccount
              ? nextAccount.trim() || "Required for TonAPI"
              : "Not used",
            limitLabel: nextLimit.trim() || "10",
            updatedAt: formatRunTime(new Date()),
          }
        : current,
    );
  }

  function handleWorkspaceAccountChange(value: string) {
    setWorkspaceAccount(value);
    markWorkspaceInputsChanged(value, workspaceLimit);
  }

  function handleWorkspaceLimitChange(value: string) {
    setWorkspaceLimit(value);
    markWorkspaceInputsChanged(workspaceAccount, value);
  }

  function handleWorkspaceViewChange(value: WorkspaceView) {
    setWorkspaceView(value);
    setWorkspaceHint(null);
  }

  function handleWorkspacePreview() {
    const target = workspaceTargets[workspaceView];
    document.getElementById(target.targetId)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    setWorkspaceHint(
      `${target.label} selected. Shared inputs are already synced; run one scoped request from the workspace or provider panel.`,
    );
  }

  function handleWorkspaceRunPreview() {
    const target = workspaceTargets[workspaceView];
    const cleanedAccount = workspaceAccount.trim();
    const safeLimit = clampWorkspaceLimit(workspaceLimit);
    const now = formatRunTime(new Date());

    if (target.requiresAccount && !cleanedAccount) {
      const message = `${target.label} requires a TON account address.`;
      setWorkspaceHint(message);
      setWorkspaceRunState({
        target: workspaceView,
        status: "error",
        message,
        accountLabel: "Required",
        limitLabel: workspaceLimit.trim() || "10",
        updatedAt: now,
      });
      return;
    }

    if (safeLimit === null) {
      const message = "Shared limit must be a number from 1 to 100.";
      setWorkspaceHint(message);
      setWorkspaceRunState({
        target: workspaceView,
        status: "error",
        message,
        accountLabel: target.requiresAccount ? cleanedAccount || "Required" : "Not used",
        limitLabel: "Invalid",
        updatedAt: now,
      });
      return;
    }

    const nextLimit = String(safeLimit);
    setWorkspaceAccount(cleanedAccount);
    setWorkspaceLimit(nextLimit);
    setWorkspaceRunState({
      target: workspaceView,
      status: "queued",
      message: `${target.label} queued from shared workspace inputs. This runs one scoped request only.`,
      accountLabel: target.requiresAccount ? cleanedAccount : "Not used",
      limitLabel: nextLimit,
      updatedAt: now,
    });
    setWorkspaceHint(
      `${target.label} is running from shared workspace inputs. Real wallet analytics remain separate.`,
    );
    document.getElementById(target.targetId)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    setWorkspaceRunRequest((current) => ({
      target: workspaceView,
      id: current.id + 1,
    }));
  }

  function handlePreviewRunStateChange(
    targetView: WorkspaceView,
    update: ProviderPreviewRunUpdate,
  ) {
    const target = workspaceTargets[targetView];
    const accountLabel =
      update.accountAddress ??
      (target.requiresAccount ? workspaceAccount.trim() || "-" : "Not used");
    const limitLabel = update.limit ?? (workspaceLimit.trim() || "10");

    setWorkspaceRunState({
      target: targetView,
      status: update.status,
      message: update.message,
      accountLabel,
      limitLabel,
      updatedAt: formatRunTime(new Date()),
    });
    setWorkspaceHint(update.message);
  }

  function clearWorkspaceControl() {
    setWorkspaceAccount("");
    setWorkspaceLimit("10");
    setWorkspaceView("ingestion");
    setWorkspaceHint(null);
    setWorkspaceRunState(null);
  }

  return (
    <div className="evidence-shell">
      <aside className="workspace-sidebar">
        <div className="sidebar-brand">
          <span className="sidebar-logo">T</span>
          <div>
            <strong>TON Tracker</strong>
            <span>TON intelligence workspace</span>
          </div>
        </div>

        <nav className="sidebar-nav" aria-label="Workspace navigation">
          {navItems.map((item) => (
            <button
              className={item === "DASHBOARD" ? "nav-item nav-active" : "nav-item"}
              key={item}
              type="button"
              aria-current={item === "DASHBOARD" ? "page" : undefined}
              aria-label={`${item} workspace section`}
            >
              <span className="nav-prefix">&gt;</span>
              {item}
            </button>
          ))}
        </nav>

        <div className="sidebar-status">
          <span>Data mode</span>
          <strong>{dataMode}</strong>
          <small>Provider scope visible</small>
        </div>
      </aside>

      <div className="workspace-frame">
        <header className="workspace-header">
          <div>
            <h1>TON Tracker</h1>
            <p>Data-honest intelligence for TON wallets and tokens</p>
          </div>
          <div className="header-badges">
            <span className={dataBadge.className}>{dataBadge.label}</span>
            <span className={providerBadge.className}>
              {providerBadge.label}
            </span>
            <span className="badge badge-real">RELEASE {RELEASE_LABEL}</span>
            <span className="badge badge-provider">
              ENV {dataMode === "real" ? "PROVIDER MODE" : "LOCAL MOCK"}
            </span>
            <span className={sourceBadgeClass}>SOURCE {sourceLabel}</span>
          </div>
        </header>

        <main className="workspace-grid">
          <div className="workspace-main">
            <WorkspaceControl
              account={workspaceAccount}
              limit={workspaceLimit}
              view={workspaceView}
              hint={workspaceHint}
              runState={workspaceRunState}
              onAccountChange={handleWorkspaceAccountChange}
              onLimitChange={handleWorkspaceLimitChange}
              onViewChange={handleWorkspaceViewChange}
              onPreview={handleWorkspacePreview}
              onRunPreview={handleWorkspaceRunPreview}
              onClear={clearWorkspaceControl}
            />

            <DashboardSection
              id="provider-status"
              eyebrow="Provider Health"
              title="Provider Status"
              description="Configured provider readiness and limitations are shown before any preview output."
            >
              <ProviderStatus
                providers={providerSnapshot}
                dataQuality={result?.data_quality ?? null}
                error={providersError}
              />
            </DashboardSection>

            <DashboardSection
              id="wallet-ingestion-workspace"
              eyebrow="Wallet Activity"
              title="Wallet Activity Ingestion Workspace"
              description="Preview coverage, persist mock-normalized activity, and inspect source-aware rows before analytics wiring."
            >
              <WalletIngestionWorkspace
                accountAddress={workspaceAccount}
                runRequestId={
                  workspaceRunRequest.target === "ingestion"
                    ? workspaceRunRequest.id
                    : 0
                }
                onAccountAddressChange={(value) => {
                  handleWorkspaceAccountChange(value);
                }}
                onPreviewRunStateChange={(update) => {
                  handlePreviewRunStateChange("ingestion", update);
                }}
              />
            </DashboardSection>

            <DashboardSection
              id="wallet-intelligence-preview"
              eyebrow="Wallet Intelligence"
              title="TonAPI Wallet Intelligence Preview"
              description="Lightweight intelligence based on TonAPI account jetton data."
            >
              <TonapiWalletIntelligencePreviewPanel
                accountAddress={workspaceAccount}
                limit={workspaceLimit}
                runRequestId={
                  workspaceRunRequest.target === "wallet"
                    ? workspaceRunRequest.id
                    : 0
                }
                onAccountAddressChange={(value) => {
                  handleWorkspaceAccountChange(value);
                }}
                onLimitChange={(value) => {
                  handleWorkspaceLimitChange(value);
                }}
                onPreviewRunStateChange={(update) => {
                  handlePreviewRunStateChange("wallet", update);
                }}
              />
            </DashboardSection>

            <div className="workspace-preview-grid">
              <DashboardSection
                id="account-jettons-preview"
                eyebrow="Wallet Jettons"
                title="TonAPI Account Jettons Preview"
                description="Provider preview rows from TonAPI account jetton data."
              >
                <TonapiAccountJettonsPreviewPanel
                  accountAddress={workspaceAccount}
                  limit={workspaceLimit}
                  runRequestId={
                    workspaceRunRequest.target === "jettons"
                      ? workspaceRunRequest.id
                      : 0
                  }
                  onAccountAddressChange={(value) => {
                    handleWorkspaceAccountChange(value);
                  }}
                  onLimitChange={(value) => {
                    handleWorkspaceLimitChange(value);
                  }}
                  onPreviewRunStateChange={(update) => {
                    handlePreviewRunStateChange("jettons", update);
                  }}
                />
              </DashboardSection>

              <DashboardSection
                id="stonfi-pools-preview"
                eyebrow="DEX Pools"
                title="STON.fi Pools Preview"
                description="STON.fi data covers STON.fi DEX pools only, not all TON DeFi."
              >
                <StonfiPoolsPreviewPanel
                  limit={workspaceLimit}
                  runRequestId={
                    workspaceRunRequest.target === "pools"
                      ? workspaceRunRequest.id
                      : 0
                  }
                  onLimitChange={(value) => {
                    handleWorkspaceLimitChange(value);
                  }}
                  onPreviewRunStateChange={(update) => {
                    handlePreviewRunStateChange("pools", update);
                  }}
                />
              </DashboardSection>
            </div>

            <DashboardSection
              className="dashboard-section-secondary"
              id="legacy-dashboard-report"
              eyebrow="Legacy / mock-aware analysis"
              title="Legacy Token and Wallet Clustering Report"
              description="Legacy report workspace remains mock-aware and separate from provider previews."
            >
              <div className="dashboard-workbench">
                <div className="dashboard-workbench-head">
                  <div>
                    <span className="section-eyebrow">
                      Legacy / mock-aware analysis
                    </span>
                    <h3>Token and wallet clustering report</h3>
                  </div>
                  <span className="badge badge-provider">mock-aware</span>
                </div>

                <div className="controls-card">
                  <PoolUrlInput
                    value={poolUrl}
                    onChange={setPoolUrl}
                    disabled={loading}
                  />
                  <TimeWindowPicker
                    value={timeWindow}
                    onChange={setTimeWindow}
                    customStart={customStart}
                    customEnd={customEnd}
                    onCustomStartChange={setCustomStart}
                    onCustomEndChange={setCustomEnd}
                    disabled={loading}
                  />
                  <div className="controls-actions">
                    <button
                      className="btn btn-primary"
                      type="button"
                      onClick={handleAnalyze}
                      disabled={loading}
                      aria-busy={loading}
                      aria-label="Run mock-aware token and wallet analysis"
                    >
                      {loading ? "Analyzing..." : "Analyze"}
                    </button>
                    {result && (
                      <ExportButtons
                        poolUrl={result.pool_url}
                        timeWindow={result.time_window}
                      />
                    )}
                  </div>
                </div>

                {error && (
                  <div
                    className="state-box error-box dashboard-state"
                    role="alert"
                  >
                    <strong>Request failed.</strong> {error}
                    <div className="muted small">
                      Is the backend running at <code>{API_BASE}</code>? Start it
                      with <code>uvicorn main:app --reload</code>.
                    </div>
                  </div>
                )}

                {loading && (
                  <div
                    className="state-box loading-box dashboard-state"
                    role="status"
                    aria-live="polite"
                  >
                    <span className="spinner" aria-hidden="true" /> Crunching
                    mock wallet data...
                  </div>
                )}

                {!loading && !result && !error && (
                  <div
                    className="state-box empty-box dashboard-state"
                    role="note"
                  >
                    Enter a TON pool URL and pick a time window, then press{" "}
                    <strong>Analyze</strong> to generate a mock-aware
                    intelligence report.
                  </div>
                )}

                {!loading && result && (
                  <main className="results">
                    <TokenOverview result={result} />
                    <TokenStatsDivider />
                    <BuyersTable wallets={result.wallets} />
                    <WalletGroups groups={result.groups} />
                    <div className="two-col">
                      <CommonHoldings holdings={result.common_holdings} />
                      <InterestingWallets wallets={result.interesting_wallets} />
                    </div>
                    <footer className="app-footer muted small">
                      {result.disclaimer}
                    </footer>
                  </main>
                )}
              </div>
            </DashboardSection>

            <DashboardSection
              id="historical-prices"
              eyebrow="Standalone price inspection"
              title="Historical prices"
              description="Inspect provider-reported historical rate points without mutating a run. PnL requests the same source only when historical enrichment is explicitly enabled."
            >
              <HistoricalPricesPreviewPanel />
            </DashboardSection>

            <DashboardSection
              id="experimental-tools"
              eyebrow="Provider-limited / Experimental tools"
              title="Provider-limited / Experimental tools"
              description="Bitquery TON coverage and manual/import workflows remain explicitly scoped and experimental."
            >
              <BitqueryTokenTradesPanel />
              <ImportPreviewPanel />
            </DashboardSection>
          </div>

          <EvidenceColumn
            dataMode={dataMode}
            bannerText={bannerText}
            providerAvailable={availableProviders}
            providerTotal={providerTotal}
          />
        </main>
      </div>
    </div>
  );
}

function WorkspaceControl({
  account,
  limit,
  view,
  hint,
  runState,
  onAccountChange,
  onLimitChange,
  onViewChange,
  onPreview,
  onRunPreview,
  onClear,
}: {
  account: string;
  limit: string;
  view: WorkspaceView;
  hint: string | null;
  runState: WorkspaceRunState | null;
  onAccountChange: (value: string) => void;
  onLimitChange: (value: string) => void;
  onViewChange: (value: WorkspaceView) => void;
  onPreview: () => void;
  onRunPreview: () => void;
  onClear: () => void;
}) {
  const target = workspaceTargets[view];
  const titleId = "workspace-control-title";
  const noteId = "workspace-control-note";
  const statusLabel = runState?.status ?? "idle";
  const statusMessage =
    runState?.message ??
    "Ready to run one selected provider preview from shared workspace inputs.";
  const accountLabel = target.requiresAccount
    ? account.trim() || "Required"
    : "Not used by STON.fi";
  const limitLabel = limit.trim() || "10";
  const selectedInputScope =
    view === "ingestion"
      ? "Address + surfaces in module"
      : target.requiresAccount
        ? "Address + limit required"
        : "Limit only; account ignored";
  const isRunBusy = statusLabel === "queued" || statusLabel === "running";

  return (
    <section
      className="workspace-control"
      aria-labelledby={titleId}
      aria-describedby={noteId}
      aria-busy={isRunBusy}
    >
      <div className="workspace-control-head">
        <div>
          <span className="section-eyebrow">Shared workspace control</span>
          <h2 id={titleId}>Provider preview command center</h2>
        </div>
        <span className="badge badge-provider">scoped previews only</span>
      </div>

      <div className="workspace-control-grid">
        <div className="field">
          <label className="field-label" htmlFor="workspace-account">
            Shared account address
          </label>
          <input
            id="workspace-account"
            className="text-input"
            type="text"
            value={account}
            placeholder="Paste TON wallet address for preview"
            onChange={(event) => onAccountChange(event.target.value)}
            aria-describedby="workspace-account-help"
          />
          <span className="field-sublabel" id="workspace-account-help">
            Used by TonAPI previews
          </span>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="workspace-limit">
            Shared limit
          </label>
          <input
            id="workspace-limit"
            className="text-input"
            type="number"
            min={1}
            max={100}
            value={limit}
            onChange={(event) => onLimitChange(event.target.value)}
            aria-describedby="workspace-limit-help"
          />
          <span className="field-sublabel" id="workspace-limit-help">
            1-100 rows
          </span>
        </div>

        <div className="field workspace-view-field">
          <span className="field-label" id="workspace-view-label">
            View
          </span>
          <div
            className="workspace-segmented"
            role="group"
            aria-labelledby="workspace-view-label"
          >
            <button
              className={
                view === "ingestion"
                  ? "workspace-segment workspace-segment-active"
                  : "workspace-segment"
              }
              type="button"
              onClick={() => onViewChange("ingestion")}
              aria-pressed={view === "ingestion"}
            >
              Wallet ingestion
            </button>
            <button
              className={
                view === "wallet"
                  ? "workspace-segment workspace-segment-active"
                  : "workspace-segment"
              }
              type="button"
              onClick={() => onViewChange("wallet")}
              aria-pressed={view === "wallet"}
            >
              Wallet intelligence
            </button>
            <button
              className={
                view === "jettons"
                  ? "workspace-segment workspace-segment-active"
                  : "workspace-segment"
              }
              type="button"
              onClick={() => onViewChange("jettons")}
              aria-pressed={view === "jettons"}
            >
              Account jettons
            </button>
            <button
              className={
                view === "pools"
                  ? "workspace-segment workspace-segment-active"
                  : "workspace-segment"
              }
              type="button"
              onClick={() => onViewChange("pools")}
              aria-pressed={view === "pools"}
            >
              STON.fi pools
            </button>
          </div>
        </div>

        <div className="workspace-actions">
          <button
            className="btn btn-primary"
            type="button"
            onClick={onRunPreview}
            disabled={isRunBusy}
            aria-busy={isRunBusy}
            aria-label={`Run ${target.label} from shared workspace inputs`}
          >
            {isRunBusy ? "Running selected preview" : "Run selected preview"}
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={onPreview}
            aria-label={`Open ${target.label} panel`}
          >
            Open selected preview
          </button>
          <button
            className="btn btn-ghost"
            type="button"
            onClick={onClear}
            aria-label="Clear shared workspace inputs"
          >
            Clear
          </button>
        </div>
      </div>

      <div
        className={`workspace-orchestration workspace-orchestration-${statusLabel}`}
        role="status"
        aria-live="polite"
        aria-label={`Workspace run status: ${statusLabel}. ${statusMessage}`}
      >
        <div className="workspace-orchestration-item">
          <span>Selected module</span>
          <strong>{target.label}</strong>
        </div>
        <div className="workspace-orchestration-item">
          <span>Account</span>
          <strong>{runState?.accountLabel ?? accountLabel}</strong>
        </div>
        <div className="workspace-orchestration-item">
          <span>Limit</span>
          <strong>{runState?.limitLabel ?? limitLabel}</strong>
        </div>
        <div className="workspace-orchestration-status">
          <span className="workspace-status-dot" aria-hidden="true" />
          <strong>{statusLabel.toUpperCase()}</strong>
          {runState?.updatedAt && <span>{runState.updatedAt}</span>}
        </div>
        <p>{statusMessage}</p>
      </div>

      <div className="workspace-scope-strip" aria-label="Shared workspace scope">
        <div className="workspace-scope-item">
          <span>Selected input scope</span>
          <strong>{selectedInputScope}</strong>
        </div>
        <div className="workspace-scope-item">
          <span>Result contract</span>
          <strong>
            {view === "ingestion"
              ? "Mock ingestion, not analytics"
              : "Provider preview, not full analysis"}
          </strong>
        </div>
        <div className="workspace-scope-item">
          <span>Evidence state</span>
          <strong>Unavailable data remains visible</strong>
        </div>
      </div>

      <div className="workspace-control-note" id={noteId}>
        One shared input layer. Wallet ingestion uses address plus selected
        surfaces; TonAPI uses address plus limit; STON.fi uses limit only. Every
        run stays scoped and source-labeled.
        {hint && <span>{hint}</span>}
      </div>
    </section>
  );
}

function EvidenceColumn({
  dataMode,
  bannerText,
  providerAvailable,
  providerTotal,
}: {
  dataMode: string;
  bannerText: string;
  providerAvailable: number;
  providerTotal: number;
}) {
  const providerScopeText =
    providerTotal > 0
      ? `${providerAvailable}/${providerTotal} providers reported; missing coverage remains visible.`
      : "Provider status loads from the backend; unavailable sources remain explicit.";

  return (
    <aside className="evidence-column">
      <section className="evidence-card release-readiness-card">
        <div className="evidence-card-head">
          <h2>Release readiness</h2>
          <span className="badge badge-real">{RELEASE_LABEL}</span>
        </div>
        <div className="release-readiness-summary">
          <span className="release-readiness-led" aria-hidden="true" />
          <div>
            <strong>Versioned database migrations</strong>
            <p>
              Backend schema evolution now has a checked-in migration path.
              This infrastructure release does not add canonical identity,
              broader history, cost basis, or new PnL behavior.
            </p>
          </div>
        </div>
        <div className="release-readiness-list">
          <ReleaseReadinessItem
            tone="ready"
            label="TonAPI live guard"
            text="DATA_MODE=real, WALLET_ACTIVITY_PROVIDER=tonapi, and WALLET_ACTIVITY_LIVE_ENABLED=true enable live native TON balance, account jetton balance, account transaction-history, TON/jetton transfer, and DEX swap coverage only."
          />
          <ReleaseReadinessItem
            tone="ready"
            label="Browser QA"
            text="Desktop and mobile signoff still checks release labels, overflow, provider status, and console health."
          />
          <ReleaseReadinessItem
            tone="ready"
            label="Workspace routing"
            text="Shared account, limit, selected module, and run status are visible before preview output."
          />
          <ReleaseReadinessItem
            tone="ready"
            label="Provider scope"
            text={providerScopeText}
          />
          <ReleaseReadinessItem
            tone="scoped"
            label="Legacy analytics"
            text="Legacy buyers and the top-level report remain separate from ingestion runs; run-scoped PnL, exports, probabilistic cluster comparison, and evidence signals operate on stored runs."
          />
          <ReleaseReadinessItem
            tone="scoped"
            label="Data contract"
            text="Ownership proof remains unavailable; cluster comparison stays probabilistic; unlocked Real PnL covers in-window realized swaps only, while spot-based unrealized valuation remains separate and informational."
          />
          <ReleaseReadinessItem
            tone="scoped"
            label="History readiness"
            text="Explicit stored-run sets can be inspected against a target run. Results stay diagnostic: is_cost_basis and eligible_for_cost_basis remain false and no readiness output enters PnL."
          />
          <ReleaseReadinessItem
            tone="ready"
            label="Schema migrations"
            text="Versioned revisions make database upgrades explicit and testable; application API and analytics contracts are unchanged in this release."
          />
          <ReleaseReadinessItem
            tone="ready"
            label="Historical prices"
            text="Provider-reported rate points power the optional USD valuation and in-window cost basis of the PnL preview; provider failures stay visible with no hidden fallback."
          />
          <ReleaseReadinessItem
            tone="ready"
            label="PnL preview"
            text="Stored runs expose after-fee flows, optional in-window realized PnL, and a separate spot-based unrealized snapshot; Real PnL unlocks per run only when all five evidence requirements are met."
          />
          <ReleaseReadinessItem
            tone="ready"
            label="Evidence signals"
            text="Stored runs expose rule-based signals with confidence levels and explicit insufficient-evidence records — heuristic observations, not a risk score."
          />
          <ReleaseReadinessItem
            tone="scoped"
            label="Version contract"
            text={`Backend VERSION remains the API-version field; ${RELEASE_LABEL} is a product release label.`}
          />
        </div>
      </section>

      <section className="evidence-card">
        <div className="evidence-card-head">
          <h2>Evidence & limitations</h2>
          <span className="badge badge-provider">VISIBLE SCOPE</span>
        </div>
        <div className="evidence-group-label">Current workspace scope</div>
        <EvidenceItem
          tone="warning"
          title="Each result stays source-scoped"
          text="Wallet ingestion uses stored activity rows; TonAPI preview cards remain jetton-only; STON.fi remains pool-only."
        />
        <EvidenceItem
          tone="info"
          title="Can show stored-run intelligence"
          text="Activity rows, evidence signals, run-scoped PnL, probabilistic cluster comparison, provider previews, and explicit limitations."
        />
        <EvidenceItem
          tone="info"
          title="Workspace inputs are shared"
          text="TonAPI panels use address and limit; STON.fi uses limit only."
        />
        <div className="evidence-group-label">Cannot show yet</div>
        <EvidenceItem
          tone="warning"
          title="No canonical full-history cost basis"
          text="History readiness exposes overlap and coverage blockers only. It does not merge runs, prove complete history, or supply acquisition cost basis."
        />
        <EvidenceItem
          tone="warning"
          title="No ownership or intent proof"
          text="Signals and cluster similarity are probabilistic evidence, never identity, intent, or ownership facts."
        />
        <EvidenceItem
          tone="warning"
          title="No hidden fallback data"
          text="Unavailable provider data remains explicit instead of being inferred."
        />
        <div className="evidence-group-label">Provider limitations</div>
        <EvidenceItem
          tone="info"
          title="Public mode may be rate limited"
          text="High-load periods may affect response times."
        />
        <EvidenceItem
          tone="warning"
          title="STON.fi DEX pools only"
          text="STON.fi data covers STON.fi DEX pools only, not all TON DeFi."
        />
        <EvidenceItem
          tone="danger"
          title="Bitquery TON coverage unavailable"
          text="Current Bitquery schema does not expose TON."
        />
      </section>

      <section className="evidence-card data-quality-card">
        <div className="evidence-card-head">
          <h2>Data confidence</h2>
          <span className="badge badge-provider">{dataMode.toUpperCase()}</span>
        </div>
        <QualityRow label="Completeness" value="Scoped" tone="warning" />
        <QualityRow label="Freshness" value="Run-scoped" tone="success" />
        <QualityRow label="Reliability" value="Provider-limited" tone="warning" />
        <div className="quality-note">
          <span>Notes</span>
          <p>Based on available provider data. {bannerText}</p>
        </div>
      </section>
    </aside>
  );
}

function ReleaseReadinessItem({
  tone,
  label,
  text,
}: {
  tone: "ready" | "scoped";
  label: string;
  text: string;
}) {
  return (
    <div className={`release-readiness-item release-readiness-${tone}`}>
      <span>{tone === "ready" ? "READY" : "SCOPED"}</span>
      <div>
        <strong>{label}</strong>
        <p>{text}</p>
      </div>
    </div>
  );
}

function EvidenceItem({
  tone,
  title,
  text,
}: {
  tone: "warning" | "info" | "danger";
  title: string;
  text: string;
}) {
  return (
    <div className={`evidence-item evidence-${tone}`}>
      <span className="evidence-icon" aria-hidden="true">
        !
      </span>
      <div>
        <strong>{title}</strong>
        <p>{text}</p>
      </div>
    </div>
  );
}

function QualityRow({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "success" | "warning";
}) {
  return (
    <div className="quality-row">
      <span>{label}</span>
      <strong className={`quality-${tone}`}>{value}</strong>
    </div>
  );
}

function TokenStatsDivider() {
  return <div className="divider" />;
}

function DashboardSection({
  id,
  className,
  eyebrow,
  title,
  description,
  children,
}: {
  id?: string;
  className?: string;
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  const titleId = id ? `${id}-title` : undefined;
  const descriptionId = id ? `${id}-description` : undefined;

  return (
    <section
      className={
        className ? `dashboard-section ${className}` : "dashboard-section"
      }
      id={id}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
    >
      <div className="dashboard-section-head">
        <div>
          <span className="section-eyebrow">{eyebrow}</span>
          <h2 id={titleId}>{title}</h2>
        </div>
        <p id={descriptionId}>{description}</p>
      </div>
      <div className="dashboard-section-body">{children}</div>
    </section>
  );
}
