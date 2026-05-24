import { useState } from "react";
import { previewImportedTrades } from "../api";
import type {
  ImportedTradePreview,
  ImportFormat,
  ImportPreviewContent,
  ImportPreviewResponse,
} from "../types";

const SUMMARY_CARDS = [
  ["Total rows", "total_rows"],
  ["Valid rows", "valid_rows"],
  ["Invalid rows", "invalid_rows"],
  ["Duplicate rows", "duplicate_rows"],
] as const;

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

export default function ImportPreviewPanel() {
  const [format, setFormat] = useState<ImportFormat>("csv");
  const [content, setContent] = useState("");
  const [previewLimit, setPreviewLimit] = useState("10");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportPreviewResponse | null>(null);

  async function handlePreview() {
    setError(null);
    setResult(null);

    let requestContent: ImportPreviewContent;
    if (format === "json") {
      try {
        requestContent = content.trim() ? JSON.parse(content) : [];
      } catch (e) {
        setError(e instanceof Error ? `Invalid JSON: ${e.message}` : "Invalid JSON.");
        return;
      }
    } else {
      requestContent = content;
    }

    setLoading(true);
    try {
      const data = await previewImportedTrades({
        format,
        content: requestContent,
        preview_limit: clampPreviewLimit(previewLimit),
      });
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown import preview error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="section import-preview-panel">
      <div className="section-head">
        <h2>Import Trades Preview</h2>
        {result && (
          <div className="muted small">
            {result.source.replace("_", " ")}
            {result.has_more
              ? ` - showing ${result.trades_preview.length} of ${result.summary.valid_rows}`
              : ""}
          </div>
        )}
      </div>

      <div className="import-preview-note">
        Import preview only validates and normalizes trades. It does not run
        wallet analysis yet.
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
                onClick={() => setFormat(option)}
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
            onChange={(e) => setPreviewLimit(e.target.value)}
          />
        </div>

        <div className="field import-content-field">
          <label className="field-label" htmlFor="import-content">
            Trade data
          </label>
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
            onChange={(e) => setContent(e.target.value)}
          />
        </div>

        <div className="import-preview-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePreview}
            disabled={loading}
          >
            {loading ? "Previewing..." : "Preview imported trades"}
          </button>
        </div>
      </div>

      {error && (
        <div className="state-box error-box import-state">
          <strong>Import preview failed.</strong> {error}
        </div>
      )}

      {loading && (
        <div className="state-box loading-box import-state">
          <span className="spinner" /> Validating import data...
        </div>
      )}

      {!loading && !result && !error && (
        <div className="state-box empty-box import-state">
          Paste CSV or JSON trade data to validate rows and preview normalized
          trades.
        </div>
      )}

      {!loading && result && (
        <div className="import-preview-results">
          <div className="stat-grid">
            {SUMMARY_CARDS.map(([label, field]) => (
              <div className="stat-card" key={field}>
                <div className="stat-label">{label}</div>
                <div className="stat-value">{result.summary[field]}</div>
              </div>
            ))}
          </div>

          {result.summary.errors.length > 0 && (
            <div>
              <div className="section-head import-subhead">
                <h2>Validation errors</h2>
                <div className="muted small">
                  {result.summary.errors.length} errors
                </div>
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
                    {result.summary.errors.map((item, index) => (
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
          )}

          <div>
            <div className="section-head import-subhead">
              <h2>Normalized trades preview</h2>
              <div className="muted small">
                {result.trades_preview.length} rows
              </div>
            </div>
            {result.trades_preview.length === 0 ? (
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
                    {result.trades_preview.map((trade, index) => (
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
                        <td className="mono">
                          {displayValue(trade.pool_address)}
                        </td>
                        <td>{displayValue(trade.dex)}</td>
                        <td>{trade.source}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}
