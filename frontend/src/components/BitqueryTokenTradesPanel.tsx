import { useState } from "react";
import {
  analyzeBitqueryTokenTrades,
  previewBitqueryTokenTrades,
} from "../api";
import type {
  BitqueryAnalysisResponse,
  BitqueryPreviewResponse,
  BitqueryTradePreview,
  BitqueryWalletAnalysis,
  ImportedWalletStatus,
} from "../types";

const SAMPLE_REQUEST = {
  tokenAddress: "EQsampleToken",
  start: "2026-05-24T00:00:00Z",
  end: "2026-05-25T00:00:00Z",
  previewLimit: "10",
};

const HONESTY_NOTE =
  "Bitquery analysis is based only on fetched DEX trades. It does not fetch wallet balances, current holdings, or full on-chain history.";

const PROVIDER_EMPTY_NOTE =
  "Provider did not return trade data. Check DATA_MODE and Bitquery API configuration.";

const STATUS_LABELS: Record<ImportedWalletStatus, string> = {
  holder: "holder",
  partial_seller: "partial seller",
  full_exit: "full exit",
  seller_only: "seller only",
  unknown: "unknown",
};

type ActiveAction = "preview" | "analysis" | null;

function displayValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function clampPreviewLimit(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 10;
  return Math.min(100, Math.max(1, Math.trunc(parsed)));
}

function tradeKey(trade: BitqueryTradePreview, index: number): string {
  return [trade.tx_hash, trade.wallet, trade.side, index].join(":");
}

function walletKey(wallet: BitqueryWalletAnalysis, index: number): string {
  return [
    wallet.wallet,
    wallet.buy_trades_count,
    wallet.sell_trades_count,
    index,
  ].join(":");
}

function pnlClass(value: string | null): string {
  if (value === null) return "pnl-zero";
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "pnl-zero";
  return parsed > 0 ? "pnl-pos" : "pnl-neg";
}

export default function BitqueryTokenTradesPanel() {
  const [tokenAddress, setTokenAddress] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [previewLimit, setPreviewLimit] = useState("10");
  const [activeAction, setActiveAction] = useState<ActiveAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] =
    useState<BitqueryPreviewResponse | null>(null);
  const [analysisResult, setAnalysisResult] =
    useState<BitqueryAnalysisResponse | null>(null);

  const loading = activeAction !== null;

  function clearResults() {
    setError(null);
    setPreviewResult(null);
    setAnalysisResult(null);
  }

  function handleTokenAddressChange(value: string) {
    setTokenAddress(value);
    clearResults();
  }

  function handleStartChange(value: string) {
    setStart(value);
    clearResults();
  }

  function handleEndChange(value: string) {
    setEnd(value);
    clearResults();
  }

  function handlePreviewLimitChange(value: string) {
    setPreviewLimit(value);
    clearResults();
  }

  function loadSampleRequest() {
    setTokenAddress(SAMPLE_REQUEST.tokenAddress);
    setStart(SAMPLE_REQUEST.start);
    setEnd(SAMPLE_REQUEST.end);
    setPreviewLimit(SAMPLE_REQUEST.previewLimit);
    clearResults();
  }

  function clearPanel() {
    setTokenAddress("");
    setStart("");
    setEnd("");
    setPreviewLimit("10");
    clearResults();
  }

  function requestPayload() {
    if (!tokenAddress.trim()) {
      setError("Token address is required.");
      return null;
    }
    if (!start.trim() || !end.trim()) {
      setError("Start and end datetime values are required.");
      return null;
    }
    return {
      token_address: tokenAddress.trim(),
      start: start.trim(),
      end: end.trim(),
      preview_limit: clampPreviewLimit(previewLimit),
    };
  }

  async function handlePreview() {
    setError(null);
    setPreviewResult(null);
    setAnalysisResult(null);
    const payload = requestPayload();
    if (!payload) return;

    setActiveAction("preview");
    try {
      const data = await previewBitqueryTokenTrades(payload);
      setPreviewResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown Bitquery preview error");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleAnalyze() {
    setError(null);
    setPreviewResult(null);
    setAnalysisResult(null);
    const payload = requestPayload();
    if (!payload) return;

    setActiveAction("analysis");
    try {
      const data = await analyzeBitqueryTokenTrades(payload);
      setAnalysisResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown Bitquery analysis error");
    } finally {
      setActiveAction(null);
    }
  }

  return (
    <section className="section bitquery-panel">
      <div className="section-head">
        <h2>Bitquery Token Trades</h2>
        {(previewResult || analysisResult) && (
          <div className="muted small">
            {analysisResult?.data_mode ?? previewResult?.data_mode} mode
          </div>
        )}
      </div>

      <div className="bitquery-note">{HONESTY_NOTE}</div>

      <div className="bitquery-form">
        <div className="field bitquery-token-field">
          <label className="field-label" htmlFor="bitquery-token-address">
            Token address
          </label>
          <input
            id="bitquery-token-address"
            className="text-input"
            type="text"
            value={tokenAddress}
            disabled={loading}
            placeholder="EQ..."
            onChange={(e) => handleTokenAddressChange(e.target.value)}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="bitquery-start">
            Start datetime
          </label>
          <input
            id="bitquery-start"
            className="text-input"
            type="text"
            value={start}
            disabled={loading}
            placeholder="2026-05-24T00:00:00Z"
            onChange={(e) => handleStartChange(e.target.value)}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="bitquery-end">
            End datetime
          </label>
          <input
            id="bitquery-end"
            className="text-input"
            type="text"
            value={end}
            disabled={loading}
            placeholder="2026-05-25T00:00:00Z"
            onChange={(e) => handleEndChange(e.target.value)}
          />
        </div>

        <div className="field bitquery-limit-field">
          <label className="field-label" htmlFor="bitquery-preview-limit">
            Preview limit
          </label>
          <input
            id="bitquery-preview-limit"
            className="text-input"
            type="number"
            min={1}
            max={100}
            value={previewLimit}
            disabled={loading}
            onChange={(e) => handlePreviewLimitChange(e.target.value)}
          />
        </div>

        <div className="bitquery-actions">
          <button
            type="button"
            className="btn btn-ghost"
            onClick={loadSampleRequest}
            disabled={loading}
          >
            Load sample request
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePreview}
            disabled={loading}
          >
            {activeAction === "preview"
              ? "Previewing..."
              : "Preview Bitquery trades"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={handleAnalyze}
            disabled={loading}
          >
            {activeAction === "analysis"
              ? "Analyzing..."
              : "Analyze Bitquery trades"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={clearPanel}
            disabled={loading}
          >
            Clear
          </button>
        </div>
      </div>

      {error && (
        <div className="state-box error-box bitquery-state">
          <strong>Bitquery request failed.</strong> {error}
        </div>
      )}

      {loading && (
        <div className="state-box loading-box bitquery-state">
          <span className="spinner" />
          {activeAction === "analysis"
            ? "Analyzing Bitquery trades..."
            : "Previewing Bitquery trades..."}
        </div>
      )}

      {!loading && !previewResult && !analysisResult && !error && (
        <div className="state-box empty-box bitquery-state">
          Enter a token address and time range to preview or analyze fetched DEX
          trades.
        </div>
      )}

      {!loading && previewResult && <PreviewResults result={previewResult} />}

      {!loading && analysisResult && (
        <AnalysisResults result={analysisResult} />
      )}
    </section>
  );
}

function ProviderMessages({
  warnings,
  error,
}: {
  warnings: string[];
  error: { code: string | null; message: string } | null;
}) {
  if (warnings.length === 0 && !error) return null;

  return (
    <div className="bitquery-provider-messages">
      {error && (
        <div className="state-box error-box bitquery-provider-error">
          <strong>{PROVIDER_EMPTY_NOTE}</strong>
          <div className="small">
            {displayValue(error.code)}: {error.message}
          </div>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="bitquery-warning-list">
          {warnings.map((warning, index) => (
            <div className="import-analysis-note" key={`${warning}:${index}`}>
              {warning}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PreviewResults({ result }: { result: BitqueryPreviewResponse }) {
  return (
    <div className="bitquery-results">
      <div className="bitquery-result-head">
        <span className="badge badge-group">success: {String(result.success)}</span>
        <span className="badge badge-real">{result.provider}</span>
        <span
          className={
            result.data_mode === "mock" ? "badge badge-mock" : "badge badge-real"
          }
        >
          {result.data_mode}
        </span>
      </div>

      <ProviderMessages warnings={result.warnings} error={result.error} />

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Total trades</div>
          <div className="stat-value">{result.summary.total_trades}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Preview count</div>
          <div className="stat-value">{result.summary.preview_count}</div>
        </div>
      </div>

      <TradesPreviewTable trades={result.trades_preview} />
    </div>
  );
}

function AnalysisResults({ result }: { result: BitqueryAnalysisResponse }) {
  return (
    <div className="bitquery-results">
      <div className="bitquery-result-head">
        <span className="badge badge-group">success: {String(result.success)}</span>
        <span className="badge badge-real">{result.provider}</span>
        <span
          className={
            result.data_mode === "mock" ? "badge badge-mock" : "badge badge-real"
          }
        >
          {result.data_mode}
        </span>
      </div>

      <div className="import-analysis-note">
        {result.analysis_note || HONESTY_NOTE}
      </div>

      <ProviderMessages warnings={result.warnings} error={result.error} />

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Total trades</div>
          <div className="stat-value">{result.summary.total_trades}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Wallets</div>
          <div className="stat-value">{result.summary.wallets_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Buy trades</div>
          <div className="stat-value">{result.summary.buy_trades_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Sell trades</div>
          <div className="stat-value">{result.summary.sell_trades_count}</div>
        </div>
      </div>

      <div className="section-head import-subhead">
        <h2>Bitquery wallet analysis</h2>
        <div className="muted small">
          {result.has_more_wallets
            ? `showing ${result.wallets.length} of ${result.summary.wallets_count}`
            : `${result.wallets.length} wallets`}
        </div>
      </div>

      <WalletAnalysisTable wallets={result.wallets} />
    </div>
  );
}

function TradesPreviewTable({ trades }: { trades: BitqueryTradePreview[] }) {
  return (
    <div>
      <div className="section-head import-subhead">
        <h2>Bitquery trades preview</h2>
        <div className="muted small">{trades.length} rows</div>
      </div>
      {trades.length === 0 ? (
        <div className="state-box empty-box bitquery-state">
          No Bitquery trades to preview.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>tx_hash</th>
                <th>block_time</th>
                <th>wallet</th>
                <th>side</th>
                <th className="num">token_amount</th>
                <th className="num">usd_amount</th>
                <th className="num">price_usd</th>
                <th>pool_address</th>
                <th>dex</th>
                <th>source</th>
              </tr>
            </thead>
            <tbody>
              {trades.map((trade, index) => (
                <tr key={tradeKey(trade, index)}>
                  <td className="mono" title={trade.tx_hash}>
                    {displayValue(trade.tx_hash)}
                  </td>
                  <td>{displayValue(trade.block_time)}</td>
                  <td className="mono" title={trade.wallet}>
                    {displayValue(trade.wallet)}
                  </td>
                  <td>
                    <span className={`badge status-${trade.side}`}>
                      {trade.side}
                    </span>
                  </td>
                  <td className="num">{displayValue(trade.token_amount)}</td>
                  <td className="num">{displayValue(trade.usd_amount)}</td>
                  <td className="num">{displayValue(trade.price_usd)}</td>
                  <td className="mono">{displayValue(trade.pool_address)}</td>
                  <td>{displayValue(trade.dex)}</td>
                  <td>{trade.source}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function WalletAnalysisTable({
  wallets,
}: {
  wallets: BitqueryWalletAnalysis[];
}) {
  return (
    <div>
      {wallets.length === 0 ? (
        <div className="state-box empty-box bitquery-state">
          No wallet analysis available from Bitquery trades.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Wallet</th>
                <th>Status</th>
                <th className="num">Buy trades</th>
                <th className="num">Sell trades</th>
                <th className="num">Bought qty</th>
                <th className="num">Bought USD</th>
                <th className="num">Sold qty</th>
                <th className="num">Sold USD</th>
                <th className="num">Net holding</th>
                <th className="num">Avg buy</th>
                <th className="num">Avg sell</th>
                <th className="num">Realized PnL</th>
                <th className="num">Realized %</th>
                <th>First trade</th>
                <th>Last trade</th>
              </tr>
            </thead>
            <tbody>
              {wallets.map((wallet, index) => (
                <tr key={walletKey(wallet, index)}>
                  <td className="mono" title={wallet.wallet}>
                    {wallet.wallet}
                  </td>
                  <td>
                    <span className={`badge status-${wallet.status}`}>
                      {STATUS_LABELS[wallet.status] ?? wallet.status}
                    </span>
                  </td>
                  <td className="num">{wallet.buy_trades_count}</td>
                  <td className="num">{wallet.sell_trades_count}</td>
                  <td className="num">{wallet.total_bought_qty}</td>
                  <td className="num">{wallet.total_bought_usd}</td>
                  <td className="num">{wallet.total_sold_qty}</td>
                  <td className="num">{wallet.total_sold_usd}</td>
                  <td className="num">{wallet.net_holding_qty}</td>
                  <td className="num">
                    {displayValue(wallet.avg_buy_price_usd)}
                  </td>
                  <td className="num">
                    {displayValue(wallet.avg_sell_price_usd)}
                  </td>
                  <td className={`num ${pnlClass(wallet.realized_pnl_usd)}`}>
                    {wallet.realized_pnl_usd}
                  </td>
                  <td className={`num ${pnlClass(wallet.realized_pnl_pct)}`}>
                    {displayValue(wallet.realized_pnl_pct)}
                  </td>
                  <td>{wallet.first_trade_time}</td>
                  <td>{wallet.last_trade_time}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
