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

export default function App() {
  const [poolUrl, setPoolUrl] = useState(SAMPLE_URL);
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("24h");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");

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
  const dataBadge =
    dataMode === "mock"
      ? { label: "MOCK DATA", className: "badge badge-mock" }
      : dataMode === "real"
        ? { label: "MIXED DATA", className: "badge badge-real" }
        : { label: "DATA MODE UNKNOWN", className: "badge badge-group" };
  const bannerText =
    dataMode === "mock"
      ? "v0.2.1 — mock mode is active. No real on-chain wallet data is used."
      : dataMode === "real"
        ? "v0.2.1 — pool/token data may be real through GeckoTerminal, but wallets, balances, PnL and clusters are still mock."
        : "v0.2.1 — pool/token data may be real in real mode, but wallet buyers, balances, PnL and clusters remain mock.";

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

  return (
    <div className="app dashboard-app">
      <header className="dashboard-hero">
        <div className="hero-copy">
          <span className="hero-eyebrow">TON intelligence console</span>
          <h1>TON Tracker</h1>
          <p className="hero-tagline">
            Data-honest intelligence for TON wallets and tokens
          </p>
          <p className="hero-text">
            Real provider previews, provider limitations, imported data, and
            mock dashboard analysis are separated so every result keeps its
            source and scope visible.
          </p>
        </div>
        <div className="hero-status-panel">
          <span className={dataBadge.className}>{dataBadge.label}</span>
          <div className="hero-status-copy">
            <span className="muted small">Current data mode</span>
            <strong>{dataMode}</strong>
          </div>
        </div>
      </header>

      <div className="dashboard-truth-grid">
        <div className="truth-card">
          <span className="truth-label">Provider previews</span>
          <strong>Real when configured</strong>
          <p>STON.fi and TonAPI previews stay scoped to their provider data.</p>
        </div>
        <div className="truth-card">
          <span className="truth-label">Dashboard analysis</span>
          <strong>Mixed or mock-limited</strong>
          <p>{bannerText}</p>
        </div>
        <div className="truth-card truth-card-warning">
          <span className="truth-label">Interpretation</span>
          <strong>No proof of ownership</strong>
          <p>
            Wallet clustering is probabilistic and is not proof of common
            ownership.
          </p>
        </div>
      </div>

      <DashboardSection
        eyebrow="Provider Health"
        title="Provider Health"
        description="Live readiness, mock mode, and provider scope are surfaced before any analysis tools."
      >
        <ProviderStatus
          providers={result?.providers ?? providers}
          dataQuality={result?.data_quality ?? null}
          error={providersError}
        />
      </DashboardSection>

      <DashboardSection
        eyebrow="Wallet Intelligence"
        title="Wallet Intelligence"
        description="Jetton-preview intelligence is separate from the legacy dashboard report and does not imply full wallet history."
      >
        <TonapiWalletIntelligencePreviewPanel />

        <div className="dashboard-workbench">
          <div className="dashboard-workbench-head">
            <div>
              <span className="section-eyebrow">Dashboard analysis</span>
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
                {loading ? "Analyzing…" : "Analyze"}
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
              <span className="spinner" /> Crunching mock wallet data…
            </div>
          )}

          {!loading && !result && !error && (
            <div className="state-box empty-box dashboard-state">
              Enter a TON pool URL and pick a time window, then press{" "}
              <strong>Analyze</strong> to generate a mock-aware intelligence
              report.
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
        eyebrow="Wallet Jettons"
        title="Wallet Jettons"
        description="TonAPI account jetton rows are shown as provider preview data, not full wallet inventory."
      >
        <TonapiAccountJettonsPreviewPanel />
      </DashboardSection>

      <DashboardSection
        eyebrow="DEX Pools"
        title="DEX Pools"
        description="STON.fi pool previews are limited to STON.fi DEX data and are not all TON DeFi."
      >
        <StonfiPoolsPreviewPanel />
      </DashboardSection>

      <DashboardSection
        eyebrow="Provider-limited / Experimental tools"
        title="Provider-limited / Experimental tools"
        description="Bitquery TON coverage and manual/import workflows remain explicitly scoped and experimental."
      >
        <BitqueryTokenTradesPanel />
        <ImportPreviewPanel />
      </DashboardSection>
    </div>
  );
}

function TokenStatsDivider() {
  return <div className="divider" />;
}

function DashboardSection({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
}) {
  return (
    <section className="dashboard-section">
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
