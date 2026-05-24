import { useEffect, useState } from "react";
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
    <div className="app">
      <header className="app-header">
        <div className="brand">
          <span className="brand-mark">◈</span>
          <div>
            <h1>TON Wallet Intelligence</h1>
            <span className="brand-sub">Dashboard · v0.2.1</span>
          </div>
        </div>
        <span className={dataBadge.className}>{dataBadge.label}</span>
      </header>

      <div className="banner">
        {bannerText} Wallet clustering is <strong>probabilistic</strong> and is
        not proof of common ownership.
      </div>

      <ProviderStatus
        providers={result?.providers ?? providers}
        dataQuality={result?.data_quality ?? null}
        error={providersError}
      />

      <div className="controls-card">
        <PoolUrlInput value={poolUrl} onChange={setPoolUrl} disabled={loading} />
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

      <ImportPreviewPanel />

      {error && (
        <div className="state-box error-box">
          <strong>Request failed.</strong> {error}
          <div className="muted small">
            Is the backend running at <code>{API_BASE}</code>? Start it with{" "}
            <code>uvicorn main:app --reload</code>.
          </div>
        </div>
      )}

      {loading && (
        <div className="state-box loading-box">
          <span className="spinner" /> Crunching mock wallet data…
        </div>
      )}

      {!loading && !result && !error && (
        <div className="state-box empty-box">
          Enter a TON pool URL and pick a time window, then press{" "}
          <strong>Analyze</strong> to generate a mock intelligence report.
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
          <footer className="app-footer muted small">{result.disclaimer}</footer>
        </main>
      )}
    </div>
  );
}

function TokenStatsDivider() {
  return <div className="divider" />;
}
