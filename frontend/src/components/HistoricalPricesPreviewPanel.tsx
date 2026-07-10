import { useState } from "react";
import { previewHistoricalPrices } from "../api";
import type { HistoricalPricesPreviewResponse } from "../types";

const SAMPLE_REQUEST = {
  token: "ton",
  start: "2026-06-28T00:00:00Z",
  end: "2026-07-05T00:00:00Z",
};

const HONESTY_NOTE =
  "Standalone inspection only: this panel does not alter a stored run. The PnL preview requests the same provider-reported (or deterministic mock) rate source only when historical enrichment is explicitly enabled; match coverage and failures remain visible.";

const DISPLAY_LIMIT = 50;

function sourceBadgeClass(status: HistoricalPricesPreviewResponse["source_status"]): string {
  switch (status) {
    case "real":
      return "badge-real";
    case "mock":
      return "badge-mock";
    default:
      return "badge-warning";
  }
}

export default function HistoricalPricesPreviewPanel() {
  const [token, setToken] = useState("");
  const [start, setStart] = useState("");
  const [end, setEnd] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] =
    useState<HistoricalPricesPreviewResponse | null>(null);

  function clearResults() {
    setError(null);
    setResult(null);
  }

  function loadSampleRequest() {
    setToken(SAMPLE_REQUEST.token);
    setStart(SAMPLE_REQUEST.start);
    setEnd(SAMPLE_REQUEST.end);
    clearResults();
  }

  function clearPanel() {
    setToken("");
    setStart("");
    setEnd("");
    clearResults();
  }

  async function handlePreview() {
    clearResults();
    if (!token.trim()) {
      setError("Token is required.");
      return;
    }
    if (!start.trim() || !end.trim()) {
      setError("Start and end datetime values are required.");
      return;
    }
    setLoading(true);
    try {
      const data = await previewHistoricalPrices(
        token.trim(),
        start.trim(),
        end.trim(),
      );
      setResult(data);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Unknown historical prices error",
      );
    } finally {
      setLoading(false);
    }
  }

  const visiblePoints = result?.points.slice(0, DISPLAY_LIMIT) ?? [];

  return (
    <section className="section bitquery-panel">
      <div className="section-head">
        <h2>Historical Prices Preview</h2>
        {result && <div className="muted small">{result.data_mode} mode</div>}
      </div>

      <div className="bitquery-note">{HONESTY_NOTE}</div>

      <div className="bitquery-form">
        <div className="field bitquery-token-field">
          <label className="field-label" htmlFor="historical-prices-token">
            Token
          </label>
          <input
            id="historical-prices-token"
            className="text-input"
            type="text"
            value={token}
            disabled={loading}
            placeholder='"ton" or jetton master address'
            onChange={(e) => {
              setToken(e.target.value);
              clearResults();
            }}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="historical-prices-start">
            Start datetime
          </label>
          <input
            id="historical-prices-start"
            className="text-input"
            type="text"
            value={start}
            disabled={loading}
            placeholder="2026-06-28T00:00:00Z"
            onChange={(e) => {
              setStart(e.target.value);
              clearResults();
            }}
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor="historical-prices-end">
            End datetime
          </label>
          <input
            id="historical-prices-end"
            className="text-input"
            type="text"
            value={end}
            disabled={loading}
            placeholder="2026-07-05T00:00:00Z"
            onChange={(e) => {
              setEnd(e.target.value);
              clearResults();
            }}
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
            {loading ? "Previewing..." : "Preview historical prices"}
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
          <strong>Historical prices request failed.</strong> {error}
        </div>
      )}

      {loading && (
        <div className="state-box loading-box bitquery-state">
          <span className="spinner" />
          Previewing historical prices...
        </div>
      )}

      {!loading && !result && !error && (
        <div className="state-box empty-box bitquery-state">
          Enter a token and time range to preview provider-reported historical
          rate points.
        </div>
      )}

      {result && (
        <>
          <div className="tonapi-wallet-result-head">
            <span className={`badge ${sourceBadgeClass(result.source_status)}`}>
              SOURCE {result.source_status.toUpperCase()}
            </span>
            <span className="badge badge-provider">
              POINTS {result.point_count}
            </span>
            <span className="badge badge-mock">NOT COST BASIS</span>
          </div>
          <p className="muted small">{result.message}</p>

          {result.points.length > 0 ? (
            <table className="data-table">
              <thead>
                <tr>
                  <th>Timestamp</th>
                  <th>Price ({result.currency.toUpperCase()})</th>
                </tr>
              </thead>
              <tbody>
                {visiblePoints.map((point) => (
                  <tr key={point.timestamp}>
                    <td>{point.timestamp}</td>
                    <td>{point.price_usd}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted small">
              No price points for the requested window; missing coverage stays
              visible instead of being inferred.
            </p>
          )}
          {result.point_count > DISPLAY_LIMIT && (
            <p className="muted small">
              Showing first {DISPLAY_LIMIT} of {result.point_count} points.
            </p>
          )}

          {result.warnings.map((warning) => (
            <p className="muted small" key={warning}>
              {warning}
            </p>
          ))}
          <p className="muted small">{result.note}</p>
        </>
      )}
    </section>
  );
}
