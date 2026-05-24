import { useState } from "react";
import { analyze, API_BASE } from "./api";
import type { AnalysisResult, TimeWindow } from "./types";
import PoolUrlInput from "./components/PoolUrlInput";
import TimeWindowPicker from "./components/TimeWindowPicker";
import TokenOverview from "./components/TokenOverview";
import BuyersTable from "./components/BuyersTable";
import WalletGroups from "./components/WalletGroups";
import CommonHoldings from "./components/CommonHoldings";
import InterestingWallets from "./components/InterestingWallets";
import ExportButtons from "./components/ExportButtons";

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
            <span className="brand-sub">Dashboard · v0.1</span>
          </div>
        </div>
        <span className="badge badge-mock">MOCK DATA</span>
      </header>

      <div className="banner">
        v0.1 prototype — analysis uses simulated mock data. Real APIs
        (GeckoTerminal / TonAPI / Toncenter) are not connected yet. Wallet
        clustering is <strong>probabilistic</strong> and is not proof of common
        ownership.
      </div>

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
