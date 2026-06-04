import { useState } from "react";
import { previewStonfiPools } from "../api";
import type {
  StonfiPoolPreview,
  StonfiPoolsPreviewResponse,
} from "../types";

const SCOPE_NOTE =
  "STON.fi data covers STON.fi DEX pools only, not all TON DeFi.";

function displayValue(value: string | number | boolean | null | undefined): string {
  if (value === null || value === undefined || value === "") return "-";
  return String(value);
}

function clampLimit(value: string): number | null {
  if (!value.trim()) return 10;
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.min(100, Math.max(1, Math.trunc(parsed)));
}

function poolKey(pool: StonfiPoolPreview, index: number): string {
  return [
    pool.address,
    pool.router_address,
    pool.token0_address,
    pool.token1_address,
    String(index),
  ]
    .filter(Boolean)
    .join(":");
}

function tokenPair(pool: StonfiPoolPreview): string {
  const token0 = pool.token0_symbol || pool.token0_address;
  const token1 = pool.token1_symbol || pool.token1_address;
  if (!token0 && !token1) return "-";
  return `${displayValue(token0)} / ${displayValue(token1)}`;
}

function liquidityValue(pool: StonfiPoolPreview): string {
  return displayValue(pool.liquidity_usd ?? pool.lp_total_supply_usd);
}

function reserveValue(pool: StonfiPoolPreview): string {
  const reserve0 = pool.reserve0 ?? pool.token0_balance;
  const reserve1 = pool.reserve1 ?? pool.token1_balance;
  if (reserve0 === undefined && reserve1 === undefined) return "-";
  return `${displayValue(reserve0)} / ${displayValue(reserve1)}`;
}

export default function StonfiPoolsPreviewPanel() {
  const [limit, setLimit] = useState("10");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<StonfiPoolsPreviewResponse | null>(null);

  function clearPanel() {
    setLimit("10");
    setLoading(false);
    setError(null);
    setResult(null);
  }

  async function handlePreview() {
    setError(null);
    setResult(null);
    const safeLimit = clampLimit(limit);
    if (safeLimit === null) {
      setError("Limit must be a number from 1 to 100.");
      return;
    }

    setLimit(String(safeLimit));
    setLoading(true);
    try {
      const data = await previewStonfiPools(safeLimit);
      setResult(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown STON.fi preview error");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="section stonfi-panel">
      <div className="section-head">
        <h2>STON.fi Pools Preview</h2>
        {result && (
          <div className="muted small">
            {result.data_mode} mode - {result.source} source
          </div>
        )}
      </div>

      <div className="stonfi-note">{SCOPE_NOTE}</div>

      <div className="stonfi-form">
        <div className="field stonfi-limit-field">
          <label className="field-label" htmlFor="stonfi-preview-limit">
            Limit
          </label>
          <input
            id="stonfi-preview-limit"
            className="text-input"
            type="number"
            min={1}
            max={100}
            value={limit}
            disabled={loading}
            onChange={(e) => {
              setLimit(e.target.value);
              setError(null);
              setResult(null);
            }}
          />
        </div>

        <div className="stonfi-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePreview}
            disabled={loading}
          >
            {loading ? "Previewing..." : "Preview STON.fi pools"}
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
        <div className="state-box error-box stonfi-state">
          <strong>STON.fi preview failed.</strong> {error}
        </div>
      )}

      {loading && (
        <div className="state-box loading-box stonfi-state">
          <span className="spinner" />
          Previewing STON.fi pools...
        </div>
      )}

      {!loading && !result && !error && (
        <div className="state-box empty-box stonfi-state">
          Choose a preview limit and request STON.fi pool data.
        </div>
      )}

      {!loading && result && <StonfiPreviewResults result={result} />}
    </section>
  );
}

function StonfiPreviewResults({
  result,
}: {
  result: StonfiPoolsPreviewResponse;
}) {
  return (
    <div className="stonfi-results">
      <div className="stonfi-result-head">
        <span className="badge badge-group">success: {String(result.success)}</span>
        <span className="badge badge-provider">Provider: {result.provider}</span>
        <span
          className={
            result.data_mode === "mock" ? "badge badge-mock" : "badge badge-real"
          }
        >
          {result.data_mode}
        </span>
        <span className="badge badge-provider">source: {result.source}</span>
      </div>

      <div className="import-analysis-note">{result.message || SCOPE_NOTE}</div>

      <ProviderMessages warnings={result.warnings} error={result.error} />

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Total pools</div>
          <div className="stat-value">{result.summary.total_pools}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Preview count</div>
          <div className="stat-value">{result.summary.preview_count}</div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Requested limit</div>
          <div className="stat-value">{result.summary.requested_limit}</div>
        </div>
      </div>

      <PoolsPreviewTable pools={result.pools_preview} />
    </div>
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
    <div className="stonfi-provider-messages">
      {error && (
        <div className="state-box error-box stonfi-provider-error">
          <strong>Provider returned an error.</strong>
          <div className="small">
            {displayValue(error.code)}: {error.message}
          </div>
        </div>
      )}
      {warnings.length > 0 && (
        <div className="stonfi-warning-list">
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

function PoolsPreviewTable({ pools }: { pools: StonfiPoolPreview[] }) {
  return (
    <div>
      <div className="section-head import-subhead">
        <h2>STON.fi pools</h2>
        <div className="muted small">{pools.length} rows</div>
      </div>
      {pools.length === 0 ? (
        <div className="state-box empty-box stonfi-state">
          No STON.fi pools to preview.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Pool address</th>
                <th>Router</th>
                <th>Token pair</th>
                <th className="num">TVL / liquidity USD</th>
                <th className="num">Volume 24h USD</th>
                <th>Reserves</th>
                <th>APY</th>
                <th>Tags</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {pools.map((pool, index) => (
                <tr key={poolKey(pool, index)}>
                  <td className="mono" title={displayValue(pool.address)}>
                    {displayValue(pool.address)}
                    {pool.deprecated && (
                      <div className="cell-sub">deprecated</div>
                    )}
                  </td>
                  <td className="mono" title={displayValue(pool.router_address)}>
                    {displayValue(pool.router_address)}
                  </td>
                  <td className="mono" title={tokenPair(pool)}>
                    {tokenPair(pool)}
                  </td>
                  <td className="num">{liquidityValue(pool)}</td>
                  <td className="num">{displayValue(pool.volume_24h_usd)}</td>
                  <td className="mono">{reserveValue(pool)}</td>
                  <td>
                    <div>{displayValue(pool.apy_1d)} 1d</div>
                    <div className="cell-sub">
                      {displayValue(pool.apy_7d)} 7d /{" "}
                      {displayValue(pool.apy_30d)} 30d
                    </div>
                  </td>
                  <td>
                    {pool.tags && pool.tags.length > 0 ? (
                      <div className="token-chips">
                        {pool.tags.map((tag) => (
                          <span className="chip" key={tag}>
                            {tag}
                          </span>
                        ))}
                      </div>
                    ) : (
                      "-"
                    )}
                  </td>
                  <td>{displayValue(pool.source)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
