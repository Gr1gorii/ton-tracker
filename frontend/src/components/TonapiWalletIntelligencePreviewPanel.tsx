import { useEffect, useRef, useState } from "react";
import { previewTonapiWalletIntelligence } from "../api";
import type {
  TonapiJettonPreview,
  TonapiProviderError,
  TonapiTopJettonPreview,
  TonapiWalletIntelligencePreviewResponse,
} from "../types";
import PreviewFreshnessStrip from "./PreviewFreshnessStrip";

const SCOPE_NOTE =
  "TonAPI wallet intelligence preview is based only on account jetton data; it is not full wallet intelligence.";

const LIMIT_NOTE =
  "It does not include full transaction history, PnL, DEX swaps, current TON balance, or full on-chain behavior.";

const PANEL_SCOPE_NOTE =
  "Lightweight intelligence based on TonAPI account jetton data. No transactions, no PnL, no DEX swaps, no current TON balance.";

const PUBLIC_MODE_WARNING =
  "TonAPI API key is not configured; public mode may be rate limited.";

const LIMITATION_ITEMS = [
  "No transaction history",
  "No PnL calculation",
  "No DEX swaps",
  "No current TON balance",
];

const SUPPORTED_SCOPE_ITEMS = [
  "Account jettons",
  "Priced assets",
  "Non-zero balances",
  "Stablecoin-like markers",
];

interface TonapiWalletIntelligencePreviewPanelProps {
  accountAddress: string;
  limit: string;
  runRequestId: number;
  onAccountAddressChange: (value: string) => void;
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
  accountAddress: string;
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

function accountLabel(value: string): string {
  return value.trim() || "-";
}

function formatPreviewRequestedAt(date: Date): string {
  return date.toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
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

export default function TonapiWalletIntelligencePreviewPanel({
  accountAddress,
  limit,
  runRequestId,
  onAccountAddressChange,
  onLimitChange,
  onPreviewRunStateChange,
}: TonapiWalletIntelligencePreviewPanelProps) {
  const [loading, setLoading] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [result, setResult] =
    useState<TonapiWalletIntelligencePreviewResponse | null>(null);
  const [resultSnapshot, setResultSnapshot] =
    useState<PreviewRequestSnapshot | null>(null);
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
      message: "Wallet intelligence preview cleared.",
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

    const safeLimit = clampLimit(limit);
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
      message:
        "Requesting TonAPI wallet intelligence preview from shared workspace inputs.",
      accountAddress: cleanedAccount,
      limit: normalizedLimit,
    });
    try {
      const data = await previewTonapiWalletIntelligence(
        cleanedAccount,
        safeLimit,
      );
      if (activeRequestId.current !== requestId) return;
      setResult(data);
      setResultSnapshot({
        accountAddress: cleanedAccount,
        limit: normalizedLimit,
        requestedAt: formatPreviewRequestedAt(new Date()),
      });
      onPreviewRunStateChange?.({
        status: "success",
        message: `TonAPI wallet intelligence returned ${data.summary.preview_count} jetton preview rows. Scope remains jetton-only.`,
        accountAddress: cleanedAccount,
        limit: normalizedLimit,
      });
    } catch (e) {
      if (activeRequestId.current !== requestId) return;
      const message =
        e instanceof Error
          ? e.message
          : "Unknown TonAPI wallet intelligence preview error";
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
  const currentLimit = currentLimitLabel(limit);
  const resultIsStale = resultSnapshot
    ? resultSnapshot.accountAddress !== currentAccount ||
      resultSnapshot.limit !== currentLimit
    : false;

  return (
    <section className="section tonapi-wallet-panel wallet-intelligence-console">
      <div className="wallet-intelligence-head">
        <div>
          <span className="section-eyebrow">Jetton-only intelligence</span>
          <h2>TonAPI Wallet Intelligence Preview</h2>
          <p>
            Lightweight intelligence based on TonAPI account jetton data. This
            panel does not fetch all wallet activity.
          </p>
        </div>
        <div className="wallet-intelligence-badges">
          <span className="badge badge-provider">PREVIEW</span>
          <span className="badge badge-warning">JETTON ONLY</span>
          {result && (
            <span
              className={
                result.data_mode === "mock" ? "badge badge-mock" : "badge badge-real"
              }
            >
              {result.data_mode}
            </span>
          )}
        </div>
      </div>

      <div className="wallet-scope-board" aria-label="Wallet intelligence scope">
        <ScopeColumn
          title="Can show"
          tone="success"
          items={SUPPORTED_SCOPE_ITEMS}
        />
        <ScopeColumn title="Cannot show yet" tone="warning" items={LIMITATION_ITEMS} />
      </div>

      <div className="tonapi-wallet-note">
        <div>{PANEL_SCOPE_NOTE}</div>
      </div>

      <div className="tonapi-wallet-form wallet-query-card">
        <div className="field tonapi-wallet-account-field">
          <label
            className="field-label"
            htmlFor="tonapi-wallet-intelligence-account-address"
          >
            Shared account address
          </label>
          <input
            id="tonapi-wallet-intelligence-account-address"
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

        <div className="field tonapi-wallet-limit-field">
          <label
            className="field-label"
            htmlFor="tonapi-wallet-intelligence-limit"
          >
            Shared limit
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
              onLimitChange(e.target.value);
              setRequestError(null);
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
        <WalletErrorState message={requestError} />
      )}

      {loading && <WalletLoadingState />}

      {!loading && !result && !requestError && (
        <WalletEmptyState />
      )}

      {!loading && result && resultSnapshot && (
        <WalletIntelligenceResults
          result={result}
          freshness={{
            isStale: resultIsStale,
            requestedAt: resultSnapshot.requestedAt,
            requestedAccount: resultSnapshot.accountAddress,
            currentAccount: accountLabel(currentAccount),
            requestedLimit: resultSnapshot.limit,
            currentLimit,
          }}
        />
      )}
    </section>
  );
}

function WalletIntelligenceResults({
  result,
  freshness,
}: {
  result: TonapiWalletIntelligencePreviewResponse;
  freshness: {
    isStale: boolean;
    requestedAt: string;
    requestedAccount: string;
    currentAccount: string;
    requestedLimit: string;
    currentLimit: string;
  };
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

      <PreviewFreshnessStrip
        isStale={freshness.isStale}
        requestedAt={freshness.requestedAt}
        message={
          freshness.isStale
            ? "Displayed wallet intelligence belongs to the requested snapshot below. Run again for current shared inputs."
            : "Displayed wallet intelligence matches the current shared inputs."
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

      <div className="wallet-result-overview">
        <div className="wallet-account-card">
          <span className="section-eyebrow">Preview account</span>
          <strong className="mono tonapi-account-stat">
            {displayValue(result.account_address)}
          </strong>
          <p>
            Account identity is shown only as the requested TonAPI preview
            target. It is not a behavioral profile.
          </p>
        </div>

        <div className="wallet-metric-grid">
          <WalletMetric label="Total jettons" value={result.summary.total_jettons} />
          <WalletMetric label="Preview count" value={result.summary.preview_count} />
          <WalletMetric
            label="Non-zero balances"
            value={displayValue(result.summary.non_zero_balance_count)}
          />
          <WalletMetric
            label="Priced jettons"
            value={displayValue(result.summary.jettons_with_price_count)}
          />
          <WalletMetric
            label="Stablecoin-like"
            value={displayValue(result.summary.stablecoin_like_count)}
          />
          <WalletMetric label="Requested limit" value={result.summary.requested_limit} muted />
        </div>
      </div>

      <div className="wallet-evidence-grid">
        <EvidenceCard
          label="Scope"
          value={displayValue(intelligence.scope)}
          text="Jetton account data only."
        />
        <EvidenceCard
          label="Data sources"
          value={listValue(intelligence.data_sources)}
          text="Source labels are preserved from the provider response."
        />
        <EvidenceCard
          label="Unavailable signals"
          value={LIMITATION_ITEMS.join(" / ")}
          text="These are intentionally not inferred or fabricated."
        />
      </div>

      <BasicNotes notes={basicNotes} />
      <TopJettonsList jettons={topJettons} />
      <JettonsPreviewTable jettons={result.jettons_preview} />
    </div>
  );
}

function ScopeColumn({
  title,
  tone,
  items,
}: {
  title: string;
  tone: "success" | "warning";
  items: string[];
}) {
  return (
    <div className={`wallet-scope-column wallet-scope-${tone}`}>
      <span>{title}</span>
      <ul>
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

function WalletMetric({
  label,
  value,
  muted,
}: {
  label: string;
  value: string | number;
  muted?: boolean;
}) {
  return (
    <div className={muted ? "wallet-metric wallet-metric-muted" : "wallet-metric"}>
      <span>{label}</span>
      <strong>{displayValue(value)}</strong>
    </div>
  );
}

function EvidenceCard({
  label,
  value,
  text,
}: {
  label: string;
  value: string;
  text: string;
}) {
  return (
    <div className="wallet-evidence-card">
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{text}</p>
    </div>
  );
}

function WalletEmptyState() {
  return (
    <div className="state-box empty-box tonapi-wallet-state wallet-intelligence-state">
      <span className="state-kicker">NO_ACCOUNT_SELECTED</span>
      <strong>Enter account address to preview jetton-based signals.</strong>
      <p>
        The request returns TonAPI account jetton data only. It does not fetch
        transactions, PnL, swaps, current TON balance, or full wallet behavior.
      </p>
    </div>
  );
}

function WalletLoadingState() {
  return (
    <div className="state-box loading-box tonapi-wallet-state wallet-intelligence-state">
      <span className="spinner" />
      <div>
        <span className="state-kicker">REQUESTING_TONAPI_PREVIEW</span>
        <strong>Requesting TonAPI jetton preview.</strong>
        <p>Provider response will be shown with scope and limitation labels.</p>
      </div>
    </div>
  );
}

function WalletErrorState({ message }: { message: string }) {
  return (
    <div className="state-box error-box tonapi-wallet-state wallet-intelligence-state">
      <span className="state-kicker">TONAPI_REQUEST_FAILED</span>
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
    <div className="wallet-notes-section">
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
            <li key={`${note}:${index}`}>
              <span className="note-index">{String(index + 1).padStart(2, "0")}</span>
              <span>{note}</span>
            </li>
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
