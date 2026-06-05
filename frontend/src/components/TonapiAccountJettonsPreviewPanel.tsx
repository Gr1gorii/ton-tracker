import { useState } from "react";
import { previewTonapiAccountJettons } from "../api";
import type {
  TonapiAccountJettonsPreviewResponse,
  TonapiJettonPreview,
  TonapiProviderError,
} from "../types";

const SCOPE_NOTE =
  "TonAPI preview shows account jetton data only; it is not full wallet intelligence yet.";

const PANEL_SCOPE_NOTE =
  "Scope: TonAPI account jetton preview only. Full wallet limitations remain in Evidence & limitations.";

const PUBLIC_MODE_WARNING =
  "TonAPI API key is not configured; public mode may be rate limited.";

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
  return displayValue(symbol ?? name);
}

function priceValue(jetton: TonapiJettonPreview): string {
  return displayValue(jetton.price_usd ?? jetton.price);
}

function compactWarnings(warnings: string[]): string[] {
  return warnings.filter(
    (warning, index) => warning !== SCOPE_NOTE && warnings.indexOf(warning) === index,
  );
}

export default function TonapiAccountJettonsPreviewPanel() {
  const [accountAddress, setAccountAddress] = useState("");
  const [limit, setLimit] = useState("10");
  const [loading, setLoading] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [result, setResult] =
    useState<TonapiAccountJettonsPreviewResponse | null>(null);

  function clearResults() {
    setRequestError(null);
    setResult(null);
  }

  function clearPanel() {
    setAccountAddress("");
    setLimit("10");
    setLoading(false);
    clearResults();
  }

  async function handlePreview() {
    setRequestError(null);
    setResult(null);

    const cleanedAccount = accountAddress.trim();
    if (!cleanedAccount) {
      setRequestError("Account address is required.");
      return;
    }

    const safeLimit = clampLimit(limit);
    if (safeLimit === null) {
      setRequestError("Limit must be a number from 1 to 100.");
      return;
    }

    setAccountAddress(cleanedAccount);
    setLimit(String(safeLimit));
    setLoading(true);
    try {
      const data = await previewTonapiAccountJettons(cleanedAccount, safeLimit);
      setResult(data);
    } catch (e) {
      setRequestError(
        e instanceof Error ? e.message : "Unknown TonAPI preview error",
      );
    } finally {
      setLoading(false);
    }
  }

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

      <div className="tonapi-form">
        <div className="field tonapi-account-field">
          <label className="field-label" htmlFor="tonapi-account-address">
            Account address
          </label>
          <input
            id="tonapi-account-address"
            className="text-input"
            type="text"
            value={accountAddress}
            disabled={loading}
            placeholder="EQ..."
            onChange={(e) => {
              setAccountAddress(e.target.value);
              clearResults();
            }}
          />
        </div>

        <div className="field tonapi-limit-field">
          <label className="field-label" htmlFor="tonapi-preview-limit">
            Limit
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
              setLimit(e.target.value);
              clearResults();
            }}
          />
        </div>

        <div className="tonapi-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePreview}
            disabled={loading}
          >
            {loading ? "Previewing..." : "Preview account jettons"}
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
        <div className="state-box error-box tonapi-state">
          <strong>TonAPI request failed.</strong> {requestError}
        </div>
      )}

      {loading && (
        <div className="state-box loading-box tonapi-state">
          <span className="spinner" />
          Previewing TonAPI account jettons...
        </div>
      )}

      {!loading && !result && !requestError && (
        <div className="state-box empty-box tonapi-state">
          Enter an account address to preview TonAPI account jettons.
        </div>
      )}

      {!loading && result && <TonapiPreviewResults result={result} />}
    </section>
  );
}

function TonapiPreviewResults({
  result,
}: {
  result: TonapiAccountJettonsPreviewResponse;
}) {
  return (
    <div className="tonapi-results">
      <div className="tonapi-result-head">
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
          <div className="stat-label">Account</div>
          <div className="stat-value mono tonapi-account-stat">
            {displayValue(result.account_address)}
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
            {displayValue(error.code)}: {error.message}
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
    <div>
      <div className="section-head import-subhead">
        <h2>TonAPI account jettons</h2>
        <div className="muted small">{jettons.length} rows</div>
      </div>
      {jettons.length === 0 ? (
        <div className="state-box empty-box tonapi-state">
          No TonAPI account jettons to preview.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Image</th>
                <th>Wallet address</th>
                <th>Jetton</th>
                <th>Jetton address</th>
                <th className="num">Balance</th>
                <th className="num">Decimals</th>
                <th className="num">Price</th>
                <th>Wallet contract</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {jettons.map((jetton, index) => (
                <tr key={jettonKey(jetton, index)}>
                  <td>
                    {jetton.image ? (
                      <img
                        className="tonapi-jetton-image"
                        src={jetton.image}
                        alt=""
                        loading="lazy"
                      />
                    ) : (
                      "-"
                    )}
                  </td>
                  <td className="mono" title={displayValue(jetton.wallet_address)}>
                    {displayValue(jetton.wallet_address)}
                  </td>
                  <td title={jettonLabel(jetton)}>
                    <div>{jettonLabel(jetton)}</div>
                    <div className="cell-sub">
                      {displayValue(jetton.jetton_name)}
                    </div>
                  </td>
                  <td
                    className="mono"
                    title={displayValue(jetton.jetton_address)}
                  >
                    {displayValue(jetton.jetton_address)}
                  </td>
                  <td className="num">{displayValue(jetton.balance)}</td>
                  <td className="num">{displayValue(jetton.decimals)}</td>
                  <td className="num">{priceValue(jetton)}</td>
                  <td
                    className="mono"
                    title={displayValue(jetton.wallet_contract_address)}
                  >
                    {displayValue(jetton.wallet_contract_address)}
                  </td>
                  <td>{displayValue(jetton.source)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
