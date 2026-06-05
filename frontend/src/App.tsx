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
import ImportPreviewPanel from "./components/ImportPreviewPanel";
import BitqueryTokenTradesPanel from "./components/BitqueryTokenTradesPanel";
import StonfiPoolsPreviewPanel from "./components/StonfiPoolsPreviewPanel";
import TonapiAccountJettonsPreviewPanel from "./components/TonapiAccountJettonsPreviewPanel";
import TonapiWalletIntelligencePreviewPanel from "./components/TonapiWalletIntelligencePreviewPanel";

const SAMPLE_URL =
  "https://www.geckoterminal.com/ton/pools/EQCp_C-wPq2Z-mock-pool";

const navItems = [
  "Dashboard",
  "Providers",
  "Pools",
  "Wallets",
  "Intelligence",
  "Reports",
  "Watchlist",
];

type WorkspaceView = "wallet" | "jettons" | "pools";

export default function App() {
  const [poolUrl, setPoolUrl] = useState(SAMPLE_URL);
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("24h");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

  const [workspaceAccount, setWorkspaceAccount] = useState("");
  const [workspaceLimit, setWorkspaceLimit] = useState("10");
  const [workspaceView, setWorkspaceView] = useState<WorkspaceView>("wallet");
  const [workspaceHint, setWorkspaceHint] = useState<string | null>(null);

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
        providerSnapshot.bitquery,
        providerSnapshot.ton_provider,
      ].filter((item) => item?.available).length
    : 0;
  const providerTotal = providerSnapshot ? 5 : 0;
  const dataBadge =
    dataMode === "mock"
      ? { label: "DATA MODE mock", className: "badge badge-mock" }
      : dataMode === "real"
        ? { label: "DATA MODE real", className: "badge badge-real" }
        : { label: "DATA MODE unknown", className: "badge badge-group" };
  const sourceLabel = dataMode === "real" ? "live/preview" : "mock/offline";
  const bannerText =
    dataMode === "mock"
      ? "v0.2.1 - mock mode is active. No real on-chain wallet data is used."
      : dataMode === "real"
        ? "v0.2.1 - pool/token data may be real through GeckoTerminal, but wallets, balances, PnL and clusters are still mock."
        : "v0.2.1 - pool/token data may be real in real mode, but wallet buyers, balances, PnL and clusters remain mock.";

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

  function handleWorkspacePreview() {
    const targetId =
      workspaceView === "wallet"
        ? "wallet-intelligence-preview"
        : workspaceView === "jettons"
          ? "account-jettons-preview"
          : "stonfi-pools-preview";
    const target =
      workspaceView === "wallet"
        ? "TonAPI Wallet Intelligence Preview"
        : workspaceView === "jettons"
          ? "TonAPI Account Jettons Preview"
          : "STON.fi Pools Preview";
    document.getElementById(targetId)?.scrollIntoView({
      behavior: "smooth",
      block: "start",
    });
    setWorkspaceHint(
      `${target} selected. Run the provider request from that module's own action button.`,
    );
  }

  function clearWorkspaceControl() {
    setWorkspaceAccount("");
    setWorkspaceLimit("10");
    setWorkspaceView("wallet");
    setWorkspaceHint(null);
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
              className={item === "Dashboard" ? "nav-item nav-active" : "nav-item"}
              key={item}
              type="button"
            >
              <span className="nav-icon">{item.slice(0, 1)}</span>
              {item}
            </button>
          ))}
        </nav>

        <div className="sidebar-status">
          <span>Data mode</span>
          <strong>{dataMode}</strong>
          <small>Real data labels enabled</small>
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
            <span className="badge badge-provider">
              providers {availableProviders}/{providerTotal || "-"}
            </span>
            <span className="badge badge-provider">ENV mainnet</span>
            <span className="badge badge-real">SOURCE {sourceLabel}</span>
          </div>
        </header>

        <main className="workspace-grid">
          <div className="workspace-main">
            <WorkspaceControl
              account={workspaceAccount}
              limit={workspaceLimit}
              view={workspaceView}
              hint={workspaceHint}
              onAccountChange={(value) => {
                setWorkspaceAccount(value);
                setWorkspaceHint(null);
              }}
              onLimitChange={(value) => {
                setWorkspaceLimit(value);
                setWorkspaceHint(null);
              }}
              onViewChange={(value) => {
                setWorkspaceView(value);
                setWorkspaceHint(null);
              }}
              onPreview={handleWorkspacePreview}
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
              id="wallet-intelligence-preview"
              eyebrow="Wallet Intelligence"
              title="TonAPI Wallet Intelligence Preview"
              description="Lightweight intelligence based on TonAPI account jetton data."
            >
              <TonapiWalletIntelligencePreviewPanel />
            </DashboardSection>

            <div className="workspace-preview-grid">
              <DashboardSection
                id="account-jettons-preview"
                eyebrow="Wallet Jettons"
                title="TonAPI Account Jettons Preview"
                description="Provider preview rows from TonAPI account jetton data."
              >
                <TonapiAccountJettonsPreviewPanel />
              </DashboardSection>

              <DashboardSection
                id="stonfi-pools-preview"
                eyebrow="DEX Pools"
                title="STON.fi Pools Preview"
                description="STON.fi data covers STON.fi DEX pools only, not all TON DeFi."
              >
                <StonfiPoolsPreviewPanel />
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
                      onClick={handleAnalyze}
                      disabled={loading}
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
                  <div className="state-box error-box dashboard-state">
                    <strong>Request failed.</strong> {error}
                    <div className="muted small">
                      Is the backend running at <code>{API_BASE}</code>? Start it
                      with <code>uvicorn main:app --reload</code>.
                    </div>
                  </div>
                )}

                {loading && (
                  <div className="state-box loading-box dashboard-state">
                    <span className="spinner" /> Crunching mock wallet data...
                  </div>
                )}

                {!loading && !result && !error && (
                  <div className="state-box empty-box dashboard-state">
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
              id="experimental-tools"
              eyebrow="Provider-limited / Experimental tools"
              title="Provider-limited / Experimental tools"
              description="Bitquery TON coverage and manual/import workflows remain explicitly scoped and experimental."
            >
              <BitqueryTokenTradesPanel />
              <ImportPreviewPanel />
            </DashboardSection>
          </div>

          <EvidenceColumn dataMode={dataMode} bannerText={bannerText} />
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
  onAccountChange,
  onLimitChange,
  onViewChange,
  onPreview,
  onClear,
}: {
  account: string;
  limit: string;
  view: WorkspaceView;
  hint: string | null;
  onAccountChange: (value: string) => void;
  onLimitChange: (value: string) => void;
  onViewChange: (value: WorkspaceView) => void;
  onPreview: () => void;
  onClear: () => void;
}) {
  return (
    <section className="workspace-control">
      <div className="workspace-control-head">
        <div>
          <span className="section-eyebrow">Workspace quick jump</span>
          <h2>Orient provider preview modules</h2>
        </div>
        <span className="badge badge-provider">does not fetch data</span>
      </div>

      <div className="workspace-control-grid">
        <div className="field">
          <label className="field-label" htmlFor="workspace-account">
            Draft account address
          </label>
          <input
            id="workspace-account"
            className="text-input"
            type="text"
            value={account}
            placeholder="Paste TON wallet address"
            onChange={(event) => onAccountChange(event.target.value)}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="workspace-limit">
            Draft limit
          </label>
          <input
            id="workspace-limit"
            className="text-input"
            type="number"
            min={1}
            max={100}
            value={limit}
            onChange={(event) => onLimitChange(event.target.value)}
          />
          <span className="field-sublabel">1-100</span>
        </div>

        <div className="field workspace-view-field">
          <span className="field-label">View</span>
          <div className="workspace-segmented">
            <button
              className={
                view === "wallet"
                  ? "workspace-segment workspace-segment-active"
                  : "workspace-segment"
              }
              type="button"
              onClick={() => onViewChange("wallet")}
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
            >
              STON.fi pools
            </button>
          </div>
        </div>

        <div className="workspace-actions">
          <button className="btn btn-primary" type="button" onClick={onPreview}>
            Go to selected module
          </button>
          <button className="btn btn-ghost" type="button" onClick={onClear}>
            Clear
          </button>
        </div>
      </div>

      <div className="workspace-control-note">
        Quick jump only. Provider-specific panels below run the existing API
        calls and keep their own inputs.
        {hint && <span>{hint}</span>}
      </div>
    </section>
  );
}

function EvidenceColumn({
  dataMode,
  bannerText,
}: {
  dataMode: string;
  bannerText: string;
}) {
  return (
    <aside className="evidence-column">
      <section className="evidence-card">
        <div className="evidence-card-head">
          <h2>Evidence & limitations</h2>
          <span className="badge badge-provider">visible scope</span>
        </div>
        <EvidenceItem
          tone="warning"
          title="Based only on account jetton data"
          text="Uses jetton wallet states for this account."
        />
        <EvidenceItem
          tone="warning"
          title="Not full wallet intelligence"
          text="Does not include full wallet activities or behavior."
        />
        <EvidenceItem
          tone="warning"
          title="No transaction history, PnL, or swaps"
          text="No transfers, swaps, or PnL calculations."
        />
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
          <h2>Data Quality</h2>
          <span className="badge badge-provider">{dataMode}</span>
        </div>
        <QualityRow label="Completeness" value="Medium" tone="warning" />
        <QualityRow label="Freshness" value="High" tone="success" />
        <QualityRow label="Reliability" value="Medium" tone="warning" />
        <div className="quality-note">
          <span>Notes</span>
          <p>Based on available provider data. {bannerText}</p>
        </div>
      </section>
    </aside>
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
      <span className="evidence-icon">!</span>
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
  return (
    <section
      className={
        className ? `dashboard-section ${className}` : "dashboard-section"
      }
      id={id}
    >
      <div className="dashboard-section-head">
        <div>
          <span className="section-eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        <p>{description}</p>
      </div>
      <div className="dashboard-section-body">{children}</div>
    </section>
  );
}
