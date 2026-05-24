import { useState } from "react";
import { analyzeImportedTrades, previewImportedTrades } from "../api";
import type {
  ImportedTradePreview,
  ImportedTradesAnalysisResponse,
  ImportedWalletAnalysis,
  ImportedWalletStatus,
  ImportFormat,
  ImportPreviewContent,
  ImportPreviewResponse,
  ImportValidationError,
} from "../types";

const PREVIEW_SUMMARY_CARDS = [
  ["Total rows", "total_rows"],
  ["Valid rows", "valid_rows"],
  ["Invalid rows", "invalid_rows"],
  ["Duplicate rows", "duplicate_rows"],
] as const;

const ANALYSIS_SUMMARY_CARDS = [
  ["Wallets", "wallets_count"],
  ["Buy trades", "buy_trades_count"],
  ["Sell trades", "sell_trades_count"],
  ["Valid rows", "valid_rows"],
  ["Invalid rows", "invalid_rows"],
  ["Duplicate rows", "duplicate_rows"],
] as const;

const STATUS_LABELS: Record<ImportedWalletStatus, string> = {
  holder: "holder",
  partial_seller: "partial seller",
  full_exit: "full exit",
  seller_only: "seller only",
  unknown: "unknown",
};

type ActiveAction = "preview" | "analysis" | null;

const SAMPLE_TRADES = [
  {
    tx_hash: "sample-buy-1",
    block_time: "2026-05-24T12:00:00Z",
    wallet: "EQsamplePartial",
    side: "buy",
    token_amount: "1000",
    usd_amount: "250",
    price_usd: "0.25",
    pool_address: "EQsamplePool",
    dex: "stonfi",
  },
  {
    tx_hash: "sample-sell-1",
    block_time: "2026-05-24T12:20:00Z",
    wallet: "EQsamplePartial",
    side: "sell",
    token_amount: "400",
    usd_amount: "140",
    price_usd: "0.35",
    pool_address: "EQsamplePool",
    dex: "stonfi",
  },
  {
    tx_hash: "sample-buy-2",
    block_time: "2026-05-24T12:35:00Z",
    wallet: "EQsampleHolder",
    side: "buy",
    token_amount: "750",
    usd_amount: "225",
    price_usd: "0.3",
    pool_address: "EQsamplePool",
    dex: "dedust",
  },
  {
    tx_hash: "sample-sell-2",
    block_time: "2026-05-24T12:45:00Z",
    wallet: "EQsampleSellerOnly",
    side: "sell",
    token_amount: "500",
    usd_amount: "175",
    price_usd: "0.35",
    pool_address: "EQsamplePool",
    dex: "dedust",
  },
] as const;

const SAMPLE_CSV = [
  "tx_hash,block_time,wallet,side,token_amount,usd_amount,price_usd,pool_address,dex",
  ...SAMPLE_TRADES.map((trade) =>
    [
      trade.tx_hash,
      trade.block_time,
      trade.wallet,
      trade.side,
      trade.token_amount,
      trade.usd_amount,
      trade.price_usd,
      trade.pool_address,
      trade.dex,
    ].join(","),
  ),
].join("\n");

const SAMPLE_JSON = JSON.stringify(SAMPLE_TRADES, null, 2);

function displayValue(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function clampPreviewLimit(value: string): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return 10;
  return Math.min(100, Math.max(1, Math.trunc(parsed)));
}

function tradeKey(trade: ImportedTradePreview, index: number): string {
  return [
    trade.tx_hash,
    trade.wallet,
    trade.side,
    trade.token_amount,
    index,
  ].join(":");
}

function pnlClass(value: string | null): string {
  if (value === null) return "pnl-zero";
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed === 0) return "pnl-zero";
  return parsed > 0 ? "pnl-pos" : "pnl-neg";
}

function walletKey(wallet: ImportedWalletAnalysis, index: number): string {
  return [
    wallet.wallet,
    wallet.buy_trades_count,
    wallet.sell_trades_count,
    index,
  ].join(":");
}

export default function ImportPreviewPanel() {
  const [format, setFormat] = useState<ImportFormat>("csv");
  const [content, setContent] = useState("");
  const [previewLimit, setPreviewLimit] = useState("10");
  const [activeAction, setActiveAction] = useState<ActiveAction>(null);
  const [error, setError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] =
    useState<ImportPreviewResponse | null>(null);
  const [analysisResult, setAnalysisResult] =
    useState<ImportedTradesAnalysisResponse | null>(null);

  const loading = activeAction !== null;

  function clearStaleResults() {
    setError(null);
    setPreviewResult(null);
    setAnalysisResult(null);
  }

  function handleFormatChange(nextFormat: ImportFormat) {
    setFormat(nextFormat);
    clearStaleResults();
  }

  function handleContentChange(nextContent: string) {
    setContent(nextContent);
    clearStaleResults();
  }

  function handlePreviewLimitChange(nextLimit: string) {
    setPreviewLimit(nextLimit);
    clearStaleResults();
  }

  function loadSampleCsv() {
    setFormat("csv");
    setContent(SAMPLE_CSV);
    clearStaleResults();
  }

  function loadSampleJson() {
    setFormat("json");
    setContent(SAMPLE_JSON);
    clearStaleResults();
  }

  function clearInput() {
    setContent("");
    clearStaleResults();
  }

  function requestContentFromInput(): ImportPreviewContent | null {
    if (format === "json") {
      try {
        return content.trim() ? JSON.parse(content) : [];
      } catch (e) {
        setError(e instanceof Error ? `Invalid JSON: ${e.message}` : "Invalid JSON.");
        return null;
      }
    }
    return content;
  }

  async function handlePreview() {
    setError(null);
    setPreviewResult(null);
    setAnalysisResult(null);
    const requestContent = requestContentFromInput();
    if (requestContent === null) return;

    setActiveAction("preview");
    try {
      const data = await previewImportedTrades({
        format,
        content: requestContent,
        preview_limit: clampPreviewLimit(previewLimit),
      });
      setPreviewResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown import preview error");
    } finally {
      setActiveAction(null);
    }
  }

  async function handleAnalyze() {
    setError(null);
    setPreviewResult(null);
    setAnalysisResult(null);
    const requestContent = requestContentFromInput();
    if (requestContent === null) return;

    setActiveAction("analysis");
    try {
      const data = await analyzeImportedTrades({
        format,
        content: requestContent,
        preview_limit: clampPreviewLimit(previewLimit),
      });
      setAnalysisResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown import analysis error");
    } finally {
      setActiveAction(null);
    }
  }

  return (
    <section className="section import-preview-panel">
      <div className="section-head">
        <h2>Import Trades Preview</h2>
        {(previewResult || analysisResult) && (
          <div className="muted small">
            {(analysisResult?.source ?? previewResult?.source ?? "").replace("_", " ")}
            {previewResult?.has_more
              ? ` - showing ${previewResult.trades_preview.length} of ${previewResult.summary.valid_rows}`
              : ""}
          </div>
        )}
      </div>

      <div className="import-preview-note">
        Import preview only validates and normalizes trades. Imported analysis is
        not full wallet intelligence yet. It does not fetch wallet balances,
        current holdings, or on-chain history.
      </div>

      <div className="import-preview-form">
        <div className="field">
          <label className="field-label">Format</label>
          <div className="segmented" aria-label="Import format">
            {(["csv", "json"] as const).map((option) => (
              <button
                key={option}
                type="button"
                className={`segment ${format === option ? "segment-active" : ""}`}
                onClick={() => handleFormatChange(option)}
                disabled={loading}
              >
                {option.toUpperCase()}
              </button>
            ))}
          </div>
        </div>

        <div className="field">
          <label className="field-label" htmlFor="import-preview-limit">
            Preview limit
          </label>
          <input
            id="import-preview-limit"
            className="text-input import-limit-input"
            type="number"
            min={1}
            max={100}
            value={previewLimit}
            disabled={loading}
            onChange={(e) => handlePreviewLimitChange(e.target.value)}
          />
        </div>

        <div className="field import-content-field">
          <label className="field-label" htmlFor="import-content">
            Trade data
          </label>
          <div className="import-sample-row">
            <span className="field-sublabel">
              Use the sample data to test preview and imported-trade analysis
              without connecting real APIs.
            </span>
            <div className="import-sample-actions">
              <button
                type="button"
                className="btn btn-ghost"
                onClick={loadSampleCsv}
                disabled={loading}
              >
                Load sample CSV
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={loadSampleJson}
                disabled={loading}
              >
                Load sample JSON
              </button>
              <button
                type="button"
                className="btn btn-ghost"
                onClick={clearInput}
                disabled={loading}
              >
                Clear input
              </button>
            </div>
          </div>
          <textarea
            id="import-content"
            className="text-input import-textarea"
            placeholder={
              format === "csv"
                ? "tx_hash,block_time,wallet,side,token_amount,usd_amount"
                : '[{"tx_hash":"tx1","block_time":"2026-05-24T12:00:00Z","wallet":"EQwallet1","side":"buy","token_amount":"1000","usd_amount":"250"}]'
            }
            value={content}
            disabled={loading}
            onChange={(e) => handleContentChange(e.target.value)}
          />
        </div>

        <div className="import-preview-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePreview}
            disabled={loading}
          >
            {activeAction === "preview"
              ? "Previewing..."
              : "Preview imported trades"}
          </button>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={handleAnalyze}
            disabled={loading}
          >
            {activeAction === "analysis"
              ? "Analyzing..."
              : "Analyze imported trades"}
          </button>
        </div>
      </div>

      {error && (
        <div className="state-box error-box import-state">
          <strong>Import request failed.</strong> {error}
        </div>
      )}

      {loading && (
        <div className="state-box loading-box import-state">
          <span className="spinner" />
          {activeAction === "analysis"
            ? "Analyzing imported trades..."
            : "Validating import data..."}
        </div>
      )}

      {!loading && !previewResult && !analysisResult && !error && (
        <div className="state-box empty-box import-state">
          Paste CSV or JSON trade data to validate rows and preview normalized
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

function PreviewResults({ result }: { result: ImportPreviewResponse }) {
  return (
    <div className="import-preview-results">
      <div className="stat-grid">
        {PREVIEW_SUMMARY_CARDS.map(([label, field]) => (
          <div className="stat-card" key={field}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{result.summary[field]}</div>
          </div>
        ))}
      </div>

      {result.summary.errors.length > 0 && (
        <ValidationErrorsTable errors={result.summary.errors} />
      )}

      <TradesPreviewTable trades={result.trades_preview} />
    </div>
  );
}

function AnalysisResults({
  result,
}: {
  result: ImportedTradesAnalysisResponse;
}) {
  return (
    <div className="import-preview-results">
      <div className="section-head import-subhead">
        <h2>Imported wallet analysis</h2>
        <div className="muted small">
          {result.has_more_wallets
            ? `showing ${result.wallets.length} of ${result.summary.wallets_count}`
            : `${result.wallets.length} wallets`}
        </div>
      </div>

      <div className="import-analysis-note">{result.analysis_note}</div>

      <div className="stat-grid">
        {ANALYSIS_SUMMARY_CARDS.map(([label, field]) => (
          <div className="stat-card" key={field}>
            <div className="stat-label">{label}</div>
            <div className="stat-value">{result.summary[field]}</div>
          </div>
        ))}
      </div>

      {result.summary.errors.length > 0 && (
        <ValidationErrorsTable errors={result.summary.errors} />
      )}

      <WalletAnalysisTable wallets={result.wallets} />
    </div>
  );
}

function ValidationErrorsTable({ errors }: { errors: ImportValidationError[] }) {
  return (
    <div>
      <div className="section-head import-subhead">
        <h2>Validation errors</h2>
        <div className="muted small">{errors.length} errors</div>
      </div>
      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th className="num">Row</th>
              <th>Field</th>
              <th>Message</th>
            </tr>
          </thead>
          <tbody>
            {errors.map((item, index) => (
              <tr key={`${item.row}:${item.field}:${index}`}>
                <td className="num">{item.row}</td>
                <td className="mono">{item.field}</td>
                <td>{item.message}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TradesPreviewTable({ trades }: { trades: ImportedTradePreview[] }) {
  return (
    <div>
      <div className="section-head import-subhead">
        <h2>Normalized trades preview</h2>
        <div className="muted small">{trades.length} rows</div>
      </div>
      {trades.length === 0 ? (
        <div className="state-box empty-box import-state">
          No valid trades to preview.
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
  wallets: ImportedWalletAnalysis[];
}) {
  return (
    <div>
      {wallets.length === 0 ? (
        <div className="state-box empty-box import-state">
          No wallet analysis available from the provided valid trades.
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
                  <td className="num">{displayValue(wallet.avg_buy_price_usd)}</td>
                  <td className="num">{displayValue(wallet.avg_sell_price_usd)}</td>
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
