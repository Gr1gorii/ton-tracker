import { useState } from "react";
import { previewTonapiWalletIntelligence } from "../api";
import type {
  TonapiJettonPreview,
  TonapiProviderError,
  TonapiTopJettonPreview,
  TonapiWalletIntelligencePreviewResponse,
} from "../types";

const SCOPE_NOTE =
  "TonAPI wallet intelligence preview is based only on account jetton data; it is not full wallet intelligence.";

const LIMIT_NOTE =
  "It does not include full transaction history, PnL, DEX swaps, current TON balance, or full on-chain behavior.";

const PANEL_SCOPE_NOTE =
  "Lightweight intelligence based on TonAPI account jetton data. No transactions, no PnL, no DEX swaps, no current TON balance.";

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

function compactWarnings(warnings: string[]): string[] {
  return warnings.filter(
    (warning, index) =>
      warning !== SCOPE_NOTE &&
      warning !== LIMIT_NOTE &&
      warnings.indexOf(warning) === index,
  );
}

function listValue(values: string[] | undefined): string {
  if (!values || values.length === 0) return "-";
  return values.join(", ");
}

function priceValue(jetton: TonapiJettonPreview | TonapiTopJettonPreview): string {
  return displayValue(jetton.price_usd ?? jetton.price);
}

function jettonKey(jetton: TonapiJettonPreview, index: number): string {
  return [
    jetton.jetton_address,
    jetton.wallet_contract_address,
    jetton.jetton_symbol,
    String(index),
  ]
    .filter(Boolean)
    .join(":");
}

function topJettonKey(jetton: TonapiTopJettonPreview, index: number): string {
  return [
    jetton.jetton_address,
    jetton.wallet_contract_address,
    jetton.jetton_symbol,
    String(index),
  ]
    .filter(Boolean)
    .join(":");
}

function jettonLabel(
  jetton: TonapiJettonPreview | TonapiTopJettonPreview,
): string {
  const symbol = jetton.jetton_symbol;
  const name = jetton.jetton_name;
  if (symbol && name) return `${symbol} - ${name}`;
  return displayValue(symbol ?? name);
}

export default function TonapiWalletIntelligencePreviewPanel() {
  const [accountAddress, setAccountAddress] = useState("");
  const [limit, setLimit] = useState("10");
  const [loading, setLoading] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [result, setResult] =
    useState<TonapiWalletIntelligencePreviewResponse | null>(null);

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
      const data = await previewTonapiWalletIntelligence(
        cleanedAccount,
        safeLimit,
      );
      setResult(data);
    } catch (e) {
      setRequestError(
        e instanceof Error
          ? e.message
          : "Unknown TonAPI wallet intelligence preview error",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="section tonapi-wallet-panel">
      <div className="section-head">
        <h2>TonAPI Wallet Intelligence Preview</h2>
        {result && (
          <div className="muted small">
            {result.data_mode} mode - {result.source} source
          </div>
        )}
      </div>

      <div className="tonapi-wallet-note">
        <div>{PANEL_SCOPE_NOTE}</div>
      </div>

      <div className="tonapi-wallet-form">
        <div className="field tonapi-wallet-account-field">
          <label
            className="field-label"
            htmlFor="tonapi-wallet-intelligence-account-address"
          >
            Account address
          </label>
          <input
            id="tonapi-wallet-intelligence-account-address"
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

        <div className="field tonapi-wallet-limit-field">
          <label
            className="field-label"
            htmlFor="tonapi-wallet-intelligence-limit"
          >
            Limit
          </label>
          <input
            id="tonapi-wallet-intelligence-limit"
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

        <div className="tonapi-wallet-actions">
          <button
            type="button"
            className="btn btn-primary"
            onClick={handlePreview}
            disabled={loading}
          >
            {loading ? "REQUESTING_TONAPI_PREVIEW" : "Preview wallet intelligence"}
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
        <div className="state-box error-box tonapi-wallet-state">
          <strong>TonAPI request failed.</strong> {requestError}
        </div>
      )}

      {loading && (
        <div className="state-box loading-box tonapi-wallet-state">
          <span className="spinner" />
          REQUESTING_TONAPI_PREVIEW
        </div>
      )}

      {!loading && !result && !requestError && (
        <div className="state-box empty-box tonapi-wallet-state">
          Enter an account address to preview TonAPI jetton-based wallet
          signals. This panel does not fetch all wallet activity.
        </div>
      )}

      {!loading && result && <WalletIntelligenceResults result={result} />}
    </section>
  );
}

function WalletIntelligenceResults({
  result,
}: {
  result: TonapiWalletIntelligencePreviewResponse;
}) {
  const intelligence = result.intelligence ?? {};
  const topJettons = intelligence.top_jettons_by_display_balance ?? [];
  const basicNotes = intelligence.basic_notes ?? [];

  return (
    <div className="tonapi-wallet-results">
      <div className="tonapi-wallet-result-head">
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

      <div className="scope-strip">{result.message || SCOPE_NOTE}</div>

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
        <div className="stat-card">
          <div className="stat-label">Non-zero balances</div>
          <div className="stat-value">
            {displayValue(result.summary.non_zero_balance_count)}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Jettons with price</div>
          <div className="stat-value">
            {displayValue(result.summary.jettons_with_price_count)}
          </div>
        </div>
        <div className="stat-card">
          <div className="stat-label">Stablecoin-like</div>
          <div className="stat-value">
            {displayValue(result.summary.stablecoin_like_count)}
          </div>
        </div>
      </div>

      <div className="tonapi-intelligence-grid">
        <div className="tonapi-intelligence-card">
          <div className="stat-label">Scope</div>
          <div className="mono">{displayValue(intelligence.scope)}</div>
        </div>
        <div className="tonapi-intelligence-card">
          <div className="stat-label">Data sources</div>
          <div>{listValue(intelligence.data_sources)}</div>
        </div>
        <div className="tonapi-intelligence-card">
          <div className="stat-label">Account address</div>
          <div className="mono tonapi-account-stat">
            {displayValue(intelligence.account_address)}
          </div>
        </div>
      </div>

      <BasicNotes notes={basicNotes} />
      <TopJettonsList jettons={topJettons} />
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
    <div className="tonapi-wallet-provider-messages">
      {error && (
        <div className="state-box error-box tonapi-wallet-provider-error">
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
        <div className="tonapi-wallet-warning-list">
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

function BasicNotes({ notes }: { notes: string[] }) {
  return (
    <div>
      <div className="section-head import-subhead">
        <h2>Basic notes</h2>
        <div className="muted small">{notes.length} notes</div>
      </div>
      {notes.length === 0 ? (
        <div className="state-box empty-box tonapi-wallet-state">
          No TonAPI wallet intelligence notes were returned.
        </div>
      ) : (
        <ul className="tonapi-basic-notes">
          {notes.map((note, index) => (
            <li key={`${note}:${index}`}>{note}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TopJettonsList({ jettons }: { jettons: TonapiTopJettonPreview[] }) {
  return (
    <div>
      <div className="section-head import-subhead">
        <h2>Top jettons by display balance</h2>
        <div className="muted small">{jettons.length} rows</div>
      </div>
      {jettons.length === 0 ? (
        <div className="state-box empty-box tonapi-wallet-state">
          No top jettons were returned from the preview rows.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
            <thead>
              <tr>
                <th>Jetton</th>
                <th>Jetton address</th>
                <th className="num">Balance</th>
                <th className="num">Display balance</th>
                <th className="num">Decimals</th>
                <th className="num">Price</th>
                <th>Wallet contract</th>
                <th>Source</th>
              </tr>
            </thead>
            <tbody>
              {jettons.map((jetton, index) => (
                <tr key={topJettonKey(jetton, index)}>
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
                  <td className="num">{displayValue(jetton.display_balance)}</td>
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

function JettonsPreviewTable({ jettons }: { jettons: TonapiJettonPreview[] }) {
  return (
    <div>
      <div className="section-head import-subhead">
        <h2>Jettons preview rows</h2>
        <div className="muted small">{jettons.length} rows</div>
      </div>
      {jettons.length === 0 ? (
        <div className="state-box empty-box tonapi-wallet-state">
          No TonAPI jetton preview rows were returned.
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data-table">
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
                    <strong>{displayValue(jetton.jetton_symbol)}</strong>
                  </td>
                  <td title={displayValue(jetton.jetton_name)}>
                    {displayValue(jetton.jetton_name)}
                  </td>
                  <td className="num">{displayValue(jetton.balance)}</td>
                  <td className="num">{priceValue(jetton)}</td>
                  <td
                    className="mono copy-cell"
                    title={displayValue(jetton.jetton_address)}
                  >
                    {displayValue(jetton.jetton_address)}
                  </td>
                  <td
                    className="mono copy-cell"
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
