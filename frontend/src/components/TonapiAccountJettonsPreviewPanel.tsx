import { useEffect, useRef, useState } from "react";
import { previewTonapiAccountJettons } from "../api";
import type {
  TonapiAccountJettonsPreviewResponse,
  TonapiJettonPreview,
  TonapiProviderError,
} from "../types";
import PreviewFreshnessStrip from "./PreviewFreshnessStrip";
import PreviewReadinessStrip, {
  type PreviewReadinessTone,
} from "./PreviewReadinessStrip";
import {
  type AccountPreviewRequestSnapshot,
  type ProviderPreviewRunUpdate,
  clampPreviewLimit,
  displayPreviewValue,
  formatPreviewRequestedAt,
  previewAccountLabel,
  previewLimitLabel,
} from "./providerPreviewUtils";

const SCOPE_NOTE =
  "TonAPI preview shows account jetton data only; it is not full wallet intelligence yet.";

const PANEL_SCOPE_NOTE =
  "Scope: TonAPI account jetton preview only. No full wallet intelligence, no transaction history, no PnL, no swaps.";

const PUBLIC_MODE_WARNING =
  "TonAPI API key is not configured; public mode may be rate limited.";

interface TonapiAccountJettonsPreviewPanelProps {
  accountAddress: string;
  limit: string;
  runRequestId: number;
  onAccountAddressChange: (value: string) => void;
  onLimitChange: (value: string) => void;
  onPreviewRunStateChange?: (update: ProviderPreviewRunUpdate) => void;
}

function jettonKey(jetton: TonapiJettonPreview, index: number): string {
  return [
    jetton.wallet_address,
    jetton.jetton_address,
    jetton.wallet_contract_address,
    String(index),
  ]
    .filter(Boolean)
    .join(":");
}

function jettonLabel(jetton: TonapiJettonPreview): string {
  const symbol = jetton.jetton_symbol;
  const name = jetton.jetton_name;
  if (symbol && name) return `${symbol} - ${name}`;
  return displayPreviewValue(symbol ?? name);
}

function priceValue(jetton: TonapiJettonPreview): string {
  return displayPreviewValue(jetton.price_usd ?? jetton.price);
}

function sourceClass(source: string | null | undefined): string {
  const normalized = displayPreviewValue(source).toLowerCase();
  if (normalized === "real" || normalized.includes("tonapi")) {
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

export default function TonapiAccountJettonsPreviewPanel({
  accountAddress,
  limit,
  runRequestId,
  onAccountAddressChange,
  onLimitChange,
  onPreviewRunStateChange,
}: TonapiAccountJettonsPreviewPanelProps) {
  const [loading, setLoading] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [result, setResult] =
    useState<TonapiAccountJettonsPreviewResponse | null>(null);
  const [resultSnapshot, setResultSnapshot] =
    useState<AccountPreviewRequestSnapshot | null>(null);
  const activeRequestId = useRef(0);

  useEffect(() => {
    setRequestError(null);
  }, [accountAddress, limit]);

  useEffect(() => {
    if (runRequestId <= 0) return;
    void handlePreview();
  }, [runRequestId]);

  function clearResults() {
    setRequestError(null);
    setResult(null);
    setResultSnapshot(null);
  }

  function clearPanel() {
    onAccountAddressChange("");
    onLimitChange("10");
    setLoading(false);
    clearResults();
    onPreviewRunStateChange?.({
      status: "idle",
      message: "TonAPI account jettons preview cleared.",
      accountAddress: "",
      limit: "10",
    });
  }

  async function handlePreview() {
    setRequestError(null);

    const cleanedAccount = accountAddress.trim();
    if (!cleanedAccount) {
      const message = "Account address is required.";
      setRequestError(message);
      onPreviewRunStateChange?.({
        status: "error",
        message,
        accountAddress: cleanedAccount,
        limit,
      });
      return;
    }

    const safeLimit = clampPreviewLimit(limit);
    if (safeLimit === null) {
      const message = "Limit must be a number from 1 to 100.";
      setRequestError(message);
      onPreviewRunStateChange?.({
        status: "error",
        message,
        accountAddress: cleanedAccount,
        limit,
      });
      return;
    }

    const normalizedLimit = String(safeLimit);
    onAccountAddressChange(cleanedAccount);
    onLimitChange(normalizedLimit);
    const requestId = activeRequestId.current + 1;
    activeRequestId.current = requestId;
    setResult(null);
    setResultSnapshot(null);
    setLoading(true);
    onPreviewRunStateChange?.({
      status: "running",
      message: "Requesting TonAPI account jettons from shared workspace inputs.",
      accountAddress: cleanedAccount,
      limit: normalizedLimit,
    });
    try {
      const data = await previewTonapiAccountJettons(cleanedAccount, safeLimit);
      if (activeRequestId.current !== requestId) return;
      setResult(data);
      setResultSnapshot({
        accountAddress: cleanedAccount,
        limit: normalizedLimit,
        requestedAt: formatPreviewRequestedAt(new Date()),
      });
      onPreviewRunStateChange?.({
        status: "success",
        message: `TonAPI account jettons returned ${data.summary.preview_count} preview rows. Scope remains account jettons only.`,
        accountAddress: cleanedAccount,
        limit: normalizedLimit,
      });
    } catch (e) {
      if (activeRequestId.current !== requestId) return;
      const message =
        e instanceof Error ? e.message : "Unknown TonAPI preview error";
      setRequestError(message);
      onPreviewRunStateChange?.({
        status: "error",
        message,
        accountAddress: cleanedAccount,
        limit: normalizedLimit,
      });
    } finally {
      if (activeRequestId.current === requestId) {
        setLoading(false);
      }
    }
  }

  const currentAccount = accountAddress.trim();
  const currentLimit = previewLimitLabel(limit);
  const limitIsValid = clampPreviewLimit(limit) !== null;
  const accountIsReady = currentAccount.length > 0;
  const resultIsStale = resultSnapshot
    ? resultSnapshot.accountAddress !== currentAccount ||
      resultSnapshot.limit !== currentLimit
    : false;
  const canRequestPreview = accountIsReady && limitIsValid && !loading;
  const readiness: {
    tone: PreviewReadinessTone;
    label: string;
    message: string;
  } = loading
    ? {
        tone: "running",
        label: "REQUEST RUNNING",
        message: "TonAPI account jettons preview is requesting scoped rows.",
      }
    : requestError
      ? {
          tone: "error",
          label: "REQUEST ERROR",
          message: requestError,
        }
      : !accountIsReady
        ? {
            tone: "warning",
            label: "ACCOUNT REQUIRED",
            message:
              "Enter a shared TON account address before requesting account jettons.",
          }
        : !limitIsValid
          ? {
              tone: "error",
              label: "LIMIT INVALID",
              message: "Shared limit must be a number from 1 to 100.",
            }
          : resultIsStale
            ? {
                tone: "stale",
                label: "RESULT STALE",
                message:
                  "A previous result is still visible; run again for current shared inputs.",
              }
            : result
              ? {
                  tone: "fresh",
                  label: "RESULT FRESH",
                  message: "Displayed account jettons match current shared inputs.",
                }
              : {
                  tone: "ready",
                  label: "READY",
                  message:
                    "Ready to request TonAPI account jetton rows only. No full wallet behavior.",
                };

  return (
    <section className="section tonapi-panel">
      <div className="section-head">
        <h2>TonAPI Account Jettons Preview</h2>
        {result && (
          <div className="muted small">
            {result.data_mode} mode - {result.source} source
          </div>
        )}
      </div>

      <div className="tonapi-note">{PANEL_SCOPE_NOTE}</div>

      <PreviewReadinessStrip
        tone={readiness.tone}
        label={readiness.label}
        message={readiness.message}
        items={[
          {
            label: "Provider",
            value: "TonAPI",
          },
          {
            label: "Account",
            value: accountIsReady ? currentAccount : "Required",
          },
          {
            label: "Limit",
            value: limitIsValid ? currentLimit : "Invalid",
          },
        ]}
      />

      <div className="tonapi-form">
        <div className="field tonapi-account-field">
          <label className="field-label" htmlFor="tonapi-account-address">
            Shared account address
          </label>
          <input
            id="tonapi-account-address"
            className="text-input"
            type="text"
            value={accountAddress}
            disabled={loading}
            placeholder="EQ..."
            onChange={(e) => {
              onAccountAddressChange(e.target.value);
              setRequestError(null);
            }}
          />
        </div>

        <div className="field tonapi-limit-field">
          <label className="field-label" htmlFor="tonapi-preview-limit">
            Shared limit
          </label>
          <input
            id="tonapi-preview-limit"
            className="text-input"
            type="number"
            min={1}
            max={100}
            value={limit}
            disabled={loading}
            onChange={(e) => {
              onLimitChange(e.target.value);
              setRequestError(null);
            }}
          />
        </div>

        <div className="tonapi-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePreview}
            disabled={!canRequestPreview}
          >
            {loading ? "Requesting jettons" : "Preview account jettons"}
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

      {requestError && (
        <PreviewErrorState message={requestError} />
      )}

      {loading && <PreviewLoadingState />}

      {!loading && !result && !requestError && (
        <PreviewEmptyState />
      )}

      {!loading && result && resultSnapshot && (
        <TonapiPreviewResults
          result={result}
          freshness={{
            isStale: resultIsStale,
            requestedAt: resultSnapshot.requestedAt,
            requestedAccount: resultSnapshot.accountAddress,
            currentAccount: previewAccountLabel(currentAccount),
            requestedLimit: resultSnapshot.limit,
            currentLimit,
          }}
        />
      )}
    </section>
  );
}

function TonapiPreviewResults({
  result,
  freshness,
}: {
  result: TonapiAccountJettonsPreviewResponse;
  freshness: {
    isStale: boolean;
    requestedAt: string;
    requestedAccount: string;
    currentAccount: string;
    requestedLimit: string;
    currentLimit: string;
  };
}) {
  return (
    <div className="tonapi-results">
      <div className="tonapi-result-head">
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
      </div>

      <PreviewFreshnessStrip
        isStale={freshness.isStale}
        requestedAt={freshness.requestedAt}
        message={
          freshness.isStale
            ? "Displayed account jettons belong to the requested snapshot below. Run again for current shared inputs."
            : "Displayed account jettons match the current shared inputs."
        }
        items={[
          {
            label: "Account",
            requestedValue: freshness.requestedAccount,
            currentValue: freshness.currentAccount,
          },
          {
            label: "Limit",
            requestedValue: freshness.requestedLimit,
            currentValue: freshness.currentLimit,
          },
        ]}
      />

      <div className="scope-strip">{result.message || SCOPE_NOTE}</div>

      <ProviderMessages warnings={result.warnings} error={result.error} />

      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-label">Account</div>
          <div className="stat-value mono tonapi-account-stat">
            {displayPreviewValue(result.account_address)}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Total jettons</div>
          <div className="stat-value">{result.summary.total_jettons}</div>
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

      <JettonsPreviewTable jettons={result.jettons_preview} />
    </div>
  );
}

function PreviewEmptyState() {
  return (
    <div className="state-box empty-box tonapi-state preview-state-card">
      <span className="state-kicker">NO_ACCOUNT_SELECTED</span>
      <strong>Enter account address to preview TonAPI account jettons.</strong>
      <p>
        This preview returns account jetton rows only. It does not fetch wallet
        transactions, swaps, PnL, or full wallet behavior.
      </p>
    </div>
  );
}

function PreviewLoadingState() {
  return (
    <div className="state-box loading-box tonapi-state preview-loading-card">
      <div className="preview-loading-head">
        <span className="spinner" />
        <div>
          <span className="state-kicker">REQUESTING_TONAPI_JETTONS</span>
          <strong>Requesting TonAPI account jettons.</strong>
        </div>
      </div>
      <SkeletonRows rows={4} />
    </div>
  );
}

function PreviewErrorState({ message }: { message: string }) {
  return (
    <div className="state-box error-box tonapi-state preview-state-card">
      <span className="state-kicker">TONAPI_JETTONS_FAILED</span>
      <strong>TonAPI request failed.</strong>
      <p>{message}</p>
    </div>
  );
}

function ProviderMessages({
  warnings,
  error,
}: {
  warnings: string[];
  error: TonapiProviderError | null;
}) {
  const visibleWarnings = compactWarnings(warnings);

  if (visibleWarnings.length === 0 && !error) return null;

  return (
    <div className="tonapi-provider-messages">
      {error && (
        <div className="state-box error-box tonapi-provider-error">
          <strong>Provider returned an error.</strong>
          <div className="small">
            {displayPreviewValue(error.code)}: {error.message}
          </div>
          {error.diagnostic && (
            <div className="small">Diagnostic: {error.diagnostic}</div>
          )}
        </div>
      )}
      {visibleWarnings.length > 0 && (
        <div className="tonapi-warning-list">
          {visibleWarnings.map((warning, index) => (
            <div
              className={
                warning === PUBLIC_MODE_WARNING
                  ? "import-analysis-note tonapi-public-warning"
                  : "import-analysis-note"
              }
              key={`${warning}:${index}`}
            >
              {warning}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function JettonsPreviewTable({ jettons }: { jettons: TonapiJettonPreview[] }) {
  return (
    <div className="intelligence-table-block jettons-table-block">
      <div className="table-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Jetton rows</span>
          <h2>TonAPI account jettons</h2>
          <p>Compact preview rows from TonAPI account jetton data only.</p>
        </div>
        <div className="table-meta">
          <span className="badge badge-provider">{jettons.length} rows</span>
          <span className="badge badge-warning">jetton data only</span>
        </div>
      </div>
      {jettons.length === 0 ? (
        <div className="state-box empty-box tonapi-state table-empty-state">
          <span className="state-kicker">NO_JETTON_ROWS</span>
          <strong>No TonAPI account jettons to preview.</strong>
          <p>
            The provider returned no preview rows for this account and limit.
            No wallet behavior is inferred from missing rows.
          </p>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table intelligence-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Name</th>
                <th className="num">Balance</th>
                <th className="num">Price</th>
                <th>Jetton address</th>
                <th>Wallet contract</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {jettons.map((jetton, index) => (
                <tr key={jettonKey(jetton, index)}>
                  <td title={jettonLabel(jetton)}>
                    <div className="asset-cell">
                      <strong>{displayPreviewValue(jetton.jetton_symbol)}</strong>
                      <span className="cell-sub">jetton</span>
                    </div>
                  </td>
                  <td title={displayPreviewValue(jetton.jetton_name)}>
                    {displayPreviewValue(jetton.jetton_name)}
                  </td>
                  <td className="num">{displayPreviewValue(jetton.balance)}</td>
                  <td className="num">{priceValue(jetton)}</td>
                  <td>
                    <AddressCell
                      label="jetton address"
                      value={displayPreviewValue(jetton.jetton_address)}
                    />
                  </td>
                  <td>
                    <AddressCell
                      label="wallet contract"
                      value={displayPreviewValue(jetton.wallet_contract_address)}
                    />
                  </td>
                  <td>
                    <span className={sourceClass(jetton.source)}>
                      {displayPreviewValue(jetton.source)}
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
