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

function dotClass(info: ProviderStatusInfo): string {
  if (info.available) return "dot dot-green";
  if (info.configured) return "dot dot-amber";
  return "dot dot-gray";
}

function providerMode(label: string, info: ProviderStatusInfo): string {
  const message = info.message.toLowerCase();
  if (label === "Bitquery" && message.includes("coverage")) return "limited";
  if (info.available && message.includes("mock")) return "preview";
  if (message.includes("public mode") || message.includes("rate limit")) {
    return "public mode";
  }
  if (!info.configured || !info.available) return "unavailable";
  return "real";
}

function providerChipClass(mode: string): string {
  if (mode === "real") return "provider-chip provider-chip-real";
  if (mode === "public mode") return "provider-chip provider-chip-warning";
  if (mode === "limited") return "provider-chip provider-chip-warning";
  if (mode === "preview") return "provider-chip provider-chip-muted";
  return "provider-chip provider-chip-error";
}

function providerShortMessage(label: string, info: ProviderStatusInfo): string {
  const message = info.message.toLowerCase();
  if (!info.configured || !info.available) {
    if (label === "Bitquery" && message.includes("ton")) {
      return "TON coverage unavailable";
    }
    return info.message;
  }
  if (label === "STON.fi") return "Real STON.fi pools source";
  if (label === "TonAPI" && message.includes("api key is not configured")) {
    return "Public mode may be rate limited";
  }
  if (label === "TonAPI") return "Account jetton preview provider";
  if (label === "Bitquery") return "Provider-limited TON coverage";
  if (label === "GeckoTerminal") return "Market data provider";
  return "Legacy/provider status";
}

function providerStateLine(info: ProviderStatusInfo): string {
  if (info.available) return "online";
  if (info.configured) return "degraded";
  return "offline";
}

function providerStatusClass(info: ProviderStatusInfo): string {
  if (info.available) return "provider-status-value provider-status-online";
  if (info.configured) return "provider-status-value provider-status-degraded";
  return "provider-status-value provider-status-offline";
}

function ProviderRow({
  label,
  info,
}: {
  label: string;
  info: ProviderStatusInfo;
}) {
  const mode = providerMode(label, info);
  return (
    <div className="provider-matrix-row" title={info.message} role="row">
      <div className="provider-source-cell" role="cell">
        <span className={dotClass(info)} />
        <span className="provider-name">{label}</span>
      </div>
      <span className={providerStatusClass(info)} role="cell">
        {providerStateLine(info)}
      </span>
      <span className={providerChipClass(mode)} role="cell">
        {mode}
      </span>
      <span className="provider-msg muted small" role="cell">
        {providerShortMessage(label, info)}
      </span>
    </div>
  );
}

function providerRows(
  providers: ProvidersStatus,
): Array<[string, ProviderStatusInfo]> {
  const rows: Array<[string, ProviderStatusInfo]> = [
    ["GeckoTerminal", providers.geckoterminal],
  ];
  if (providers.stonfi) rows.push(["STON.fi", providers.stonfi]);
  if (providers.tonapi) rows.push(["TonAPI", providers.tonapi]);
  rows.push(["Bitquery", providers.bitquery]);
  rows.push(["TON provider", providers.ton_provider]);
  return rows;
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
  const rows = providers ? providerRows(providers) : [];
  const onlineCount = rows.filter(([, info]) => info.available).length;
  const degradedCount = rows.filter(
    ([, info]) => !info.available && info.configured,
  ).length;
  const offlineCount = rows.filter(
    ([, info]) => !info.available && !info.configured,
  ).length;
  const endpointSummaryLabel = `Provider status endpoint returned ${rows.length} providers: ${onlineCount} online, ${degradedCount} degraded, ${offlineCount} offline.`;

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
        <div className="state-box error-box provider-status-error">
          Could not load provider status: {error}
        </div>
      )}

      {providers && (
        <>
          <div
            className="provider-endpoint-summary"
            role="status"
            aria-label={endpointSummaryLabel}
          >
            <div>
              <span>Endpoint coverage</span>
              <strong>{rows.length}/5 providers</strong>
            </div>
            <div>
              <span>Runtime state</span>
              <strong>
                {onlineCount} online / {degradedCount} degraded /{" "}
                {offlineCount} offline
              </strong>
            </div>
            <p>Status endpoint only; no network probe is performed here.</p>
          </div>

          <div
            className="provider-matrix"
            role="table"
            aria-label="Provider evidence matrix"
          >
            <div className="provider-matrix-row provider-matrix-head" role="row">
              <span role="columnheader">Source</span>
              <span role="columnheader">Status</span>
              <span role="columnheader">Mode</span>
              <span role="columnheader">Limitation</span>
            </div>
            {rows.map(([label, info]) => (
              <ProviderRow key={label} label={label} info={info} />
            ))}
          </div>
        </>
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
