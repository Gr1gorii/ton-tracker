import type {
  DataQuality,
  DataQualityComponents,
  ProvidersStatus,
  ProviderStatusInfo,
} from "../types";

interface Props {
  providers: ProvidersStatus | null;
  dataQuality: DataQuality | null;
  error?: string | null;
}

// Pick a status dot color: green = available, amber = configured but not
// available, gray = not configured.
function dotClass(info: ProviderStatusInfo): string {
  if (info.available) return "dot dot-green";
  if (info.configured) return "dot dot-amber";
  return "dot dot-gray";
}

function ProviderRow({
  label,
  info,
}: {
  label: string;
  info: ProviderStatusInfo;
}) {
  return (
    <div className="provider-row">
      <span className={dotClass(info)} />
      <span className="provider-name">{label}</span>
      <span className="provider-msg muted small">{info.message}</span>
    </div>
  );
}

const componentLabels: Array<[keyof DataQualityComponents, string]> = [
  ["pool_data", "Pool data"],
  ["token_data", "Token data"],
  ["wallet_buyers", "Wallet buyers"],
  ["wallet_balances", "Wallet balances"],
  ["pnl", "PnL"],
  ["clustering", "Clustering"],
  ["common_holdings", "Common holdings"],
];

function formatComponentValue(value: string): string {
  return value.replace(/_/g, " ");
}

function componentClass(value: string): string {
  if (value === "real") return "component-source component-real";
  if (value === "fallback_mock") return "component-source component-fallback";
  return "component-source component-mock";
}

export default function ProviderStatus({
  providers,
  dataQuality,
  error,
}: Props) {
  const mode = providers?.data_mode ?? dataQuality?.mode ?? "unknown";
  const isRealMode = mode === "real";
  const modeLabel =
    mode === "real" ? "Real mode" : mode === "mock" ? "Mock mode" : "Unknown mode";

  return (
    <section className="provider-status-card">
      <div className="provider-status-head">
        <h3>Data mode / Provider status</h3>
        <span
          className={`badge ${isRealMode ? "badge-real" : "badge-mock"}`}
        >
          {modeLabel}
        </span>
      </div>

      {isRealMode && (
        <div className="dq-critical">
          Pool/token data may be real. Wallets, PnL and clusters are mock in
          v0.2.1. Not real wallet-level analysis yet.
        </div>
      )}

      {error && (
        <div className="muted small">
          Could not load provider status: {error}
        </div>
      )}

      {providers && (
        <div className="provider-rows">
          <ProviderRow label="GeckoTerminal" info={providers.geckoterminal} />
          <ProviderRow label="TON provider" info={providers.ton_provider} />
          <ProviderRow label="Bitquery" info={providers.bitquery} />
        </div>
      )}

      {dataQuality?.components && (
        <div className="component-provenance">
          {componentLabels.map(([key, label]) => {
            const value = dataQuality.components[key];
            return (
              <div className="component-row" key={key}>
                <span className="component-label">{label}</span>
                <span className={componentClass(value)}>
                  {formatComponentValue(value)}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {dataQuality && dataQuality.warnings.length > 0 && (
        <ul className="dq-warnings">
          {dataQuality.warnings.map((w, i) => (
            <li key={i}>Warning: {w}</li>
          ))}
        </ul>
      )}

      {dataQuality && dataQuality.provider_notes.length > 0 && (
        <ul className="dq-notes">
          {dataQuality.provider_notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}
    </section>
  );
}
