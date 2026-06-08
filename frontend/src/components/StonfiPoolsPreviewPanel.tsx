import { useEffect, useRef, useState } from "react";
import { previewStonfiPools } from "../api";
import type {
  StonfiPoolPreview,
  StonfiPoolsPreviewResponse,
} from "../types";
import PreviewFreshnessStrip from "./PreviewFreshnessStrip";

const SCOPE_NOTE =
  "STON.fi data covers STON.fi DEX pools only, not all TON DeFi.";

const PANEL_SCOPE_NOTE =
  "Scope: STON.fi DEX pools only. This is not complete TON DeFi coverage.";

interface StonfiPoolsPreviewPanelProps {
  limit: string;
  runRequestId: number;
  onLimitChange: (value: string) => void;
  onPreviewRunStateChange?: (update: ProviderPreviewRunUpdate) => void;
}

interface ProviderPreviewRunUpdate {
  status: "idle" | "running" | "success" | "error";
  message: string;
  accountAddress?: string;
  limit?: string;
}

interface PreviewRequestSnapshot {
  limit: string;
  requestedAt: string;
}

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

function currentLimitLabel(value: string): string {
  const safeLimit = clampLimit(value);
  if (safeLimit === null) return value.trim() || "Invalid";
  return String(safeLimit);
}

function formatPreviewRequestedAt(date: Date): string {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
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

function sourceClass(source: string | null | undefined): string {
  const normalized = displayValue(source).toLowerCase();
  if (normalized === "real" || normalized.includes("ston")) {
    return "source-badge source-real";
  }
  if (normalized === "mock") return "source-badge source-mock";
  return "source-badge source-unknown";
}

function compactWarnings(warnings: string[]): string[] {
  return warnings.filter(
    (warning, index) => warning !== SCOPE_NOTE && warnings.indexOf(warning) === index,
  );
}

export default function StonfiPoolsPreviewPanel({
  limit,
  runRequestId,
  onLimitChange,
  onPreviewRunStateChange,
}: StonfiPoolsPreviewPanelProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<StonfiPoolsPreviewResponse | null>(null);
  const [resultSnapshot, setResultSnapshot] =
    useState<PreviewRequestSnapshot | null>(null);
  const activeRequestId = useRef(0);

  useEffect(() => {
    setError(null);
  }, [limit]);

  useEffect(() => {
    if (runRequestId <= 0) return;
    void handlePreview();
  }, [runRequestId]);

  function clearPanel() {
    onLimitChange("10");
    setLoading(false);
    setError(null);
    setResult(null);
    setResultSnapshot(null);
    onPreviewRunStateChange?.({
      status: "idle",
      message: "STON.fi pools preview cleared.",
      accountAddress: "Not used",
      limit: "10",
    });
  }

  async function handlePreview() {
    setError(null);
    const safeLimit = clampLimit(limit);
    if (safeLimit === null) {
      const message = "Limit must be a number from 1 to 100.";
      setError(message);
      onPreviewRunStateChange?.({
        status: "error",
        message,
        accountAddress: "Not used",
        limit,
      });
      return;
    }

    const normalizedLimit = String(safeLimit);
    onLimitChange(normalizedLimit);
    const requestId = activeRequestId.current + 1;
    activeRequestId.current = requestId;
    setResult(null);
    setResultSnapshot(null);
    setLoading(true);
    onPreviewRunStateChange?.({
      status: "running",
      message: "Requesting STON.fi pools from the shared workspace limit.",
      accountAddress: "Not used",
      limit: normalizedLimit,
    });
    try {
      const data = await previewStonfiPools(safeLimit);
      if (activeRequestId.current !== requestId) return;
      setResult(data);
      setResultSnapshot({
        limit: normalizedLimit,
        requestedAt: formatPreviewRequestedAt(new Date()),
      });
      onPreviewRunStateChange?.({
        status: "success",
        message: `STON.fi returned ${data.summary.preview_count} pool preview rows. Scope remains STON.fi pools only.`,
        accountAddress: "Not used",
        limit: normalizedLimit,
      });
    } catch (e) {
      if (activeRequestId.current !== requestId) return;
      const message =
        e instanceof Error ? e.message : "Unknown STON.fi preview error";
      setError(message);
      onPreviewRunStateChange?.({
        status: "error",
        message,
        accountAddress: "Not used",
        limit: normalizedLimit,
      });
    } finally {
      if (activeRequestId.current === requestId) {
        setLoading(false);
      }
    }
  }

  const currentLimit = currentLimitLabel(limit);
  const resultIsStale = resultSnapshot
    ? resultSnapshot.limit !== currentLimit
    : false;

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

      <div className="stonfi-note">{PANEL_SCOPE_NOTE}</div>

      <div className="stonfi-form">
        <div className="field stonfi-limit-field">
          <label className="field-label" htmlFor="stonfi-preview-limit">
            Shared limit
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
              onLimitChange(e.target.value);
              setError(null);
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
            {loading ? "REQUESTING_STONFI_POOLS" : "Preview STON.fi pools"}
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
        <PreviewErrorState message={error} />
      )}

      {loading && <PreviewLoadingState />}

      {!loading && !result && !error && (
        <PreviewEmptyState />
      )}

      {!loading && result && resultSnapshot && (
        <StonfiPreviewResults
          result={result}
          freshness={{
            isStale: resultIsStale,
            requestedAt: resultSnapshot.requestedAt,
            requestedLimit: resultSnapshot.limit,
            currentLimit,
          }}
        />
      )}
    </section>
  );
}

function PreviewEmptyState() {
  return (
    <div className="state-box empty-box stonfi-state preview-state-card">
      <span className="state-kicker">NO_POOL_REQUEST</span>
      <strong>Choose a limit and request STON.fi pool data.</strong>
      <p>
        This preview covers STON.fi DEX pools only. It is not complete TON DeFi
        coverage.
      </p>
    </div>
  );
}

function PreviewLoadingState() {
  return (
    <div className="state-box loading-box stonfi-state preview-loading-card">
      <div className="preview-loading-head">
        <span className="spinner" />
        <div>
          <span className="state-kicker">REQUESTING_STONFI_POOLS</span>
          <strong>Requesting STON.fi pool preview rows.</strong>
        </div>
      </div>
      <SkeletonRows rows={4} />
    </div>
  );
}

function PreviewErrorState({ message }: { message: string }) {
  return (
    <div className="state-box error-box stonfi-state preview-state-card">
      <span className="state-kicker">STONFI_POOLS_FAILED</span>
      <strong>STON.fi preview failed.</strong>
      <p>{message}</p>
    </div>
  );
}

function StonfiPreviewResults({
  result,
  freshness,
}: {
  result: StonfiPoolsPreviewResponse;
  freshness: {
    isStale: boolean;
    requestedAt: string;
    requestedLimit: string;
    currentLimit: string;
  };
}) {
  return (
    <div className="stonfi-results">
      <div className="stonfi-result-head">
        <span className="badge badge-group">SUCCESS {String(result.success)}</span>
        <span className="badge badge-provider">PROVIDER {result.provider}</span>
        <span
          className={
            result.data_mode === "mock" ? "badge badge-mock" : "badge badge-real"
          }
        >
          {result.data_mode}
        </span>
        <span className="badge badge-provider">SOURCE {result.source}</span>
        <span className="badge badge-warning">STON.fi POOLS ONLY</span>
      </div>

      <PreviewFreshnessStrip
        isStale={freshness.isStale}
        requestedAt={freshness.requestedAt}
        message={
          freshness.isStale
            ? "Displayed STON.fi pools belong to the requested limit below. Run again for current shared limit."
            : "Displayed STON.fi pools match the current shared limit."
        }
        items={[
          {
            label: "Limit",
            requestedValue: freshness.requestedLimit,
            currentValue: freshness.currentLimit,
          },
          {
            label: "Account",
            requestedValue: "Not used",
            currentValue: "Not used",
          },
        ]}
      />

      <div className="scope-strip">{result.message || SCOPE_NOTE}</div>

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
  const visibleWarnings = compactWarnings(warnings);

  if (visibleWarnings.length === 0 && !error) return null;

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
      {visibleWarnings.length > 0 && (
        <div className="stonfi-warning-list">
          {visibleWarnings.map((warning, index) => (
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
    <div className="intelligence-table-block stonfi-table-block">
      <div className="table-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">DEX pool rows</span>
          <h2>STON.fi pools</h2>
          <p>Real provider preview scoped to STON.fi DEX pools only.</p>
        </div>
        <div className="table-meta">
          <span className="badge badge-provider">{pools.length} rows</span>
          <span className="badge badge-warning">STON.fi pools only</span>
        </div>
      </div>
      {pools.length === 0 ? (
        <div className="state-box empty-box stonfi-state table-empty-state">
          <span className="state-kicker">NO_STONFI_POOL_ROWS</span>
          <strong>No STON.fi pools to preview.</strong>
          <p>
            The provider returned no pool rows for this limit. This does not
            imply complete TON DeFi coverage.
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table pools-table">
            <thead>
              <tr>
                <th>Pool address</th>
                <th>Pair</th>
                <th>Router</th>
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
                  <td>
                    <AddressCell
                      label="pool address"
                      value={displayValue(pool.address)}
                    />
                    {pool.deprecated && (
                      <div className="cell-sub pool-flag">deprecated</div>
                    )}
                  </td>
                  <td title={tokenPair(pool)}>
                    <div className="pair-cell">
                      <strong>{tokenPair(pool)}</strong>
                      <span className="cell-sub">STON.fi pair</span>
                    </div>
                  </td>
                  <td>
                    <AddressCell
                      label="router address"
                      value={displayValue(pool.router_address)}
                    />
                  </td>
                  <td className="num">{liquidityValue(pool)}</td>
                  <td className="num">{displayValue(pool.volume_24h_usd)}</td>
                  <td className="mono reserve-cell">{reserveValue(pool)}</td>
                  <td className="num apy-cell">
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
                  <td>
                    <span className={sourceClass(pool.source)}>
                      {displayValue(pool.source)}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function AddressCell({ value, label }: { value: string; label: string }) {
  const [copied, setCopied] = useState(false);
  const canCopy = value !== "-";

  async function handleCopy() {
    if (!canCopy) return;
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="address-cell">
      <span className="mono address-value" title={value}>
        {value}
      </span>
      <button
        className="address-copy"
        type="button"
        onClick={handleCopy}
        disabled={!canCopy}
        aria-label={`Copy ${label}`}
      >
        {copied ? "COPIED" : "COPY"}
      </button>
    </div>
  );
}

function SkeletonRows({ rows }: { rows: number }) {
  return (
    <div className="skeleton-table" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton-row" key={index}>
          <span />
          <span />
          <span />
          <span />
        </div>
      ))}
    </div>
  );
}
