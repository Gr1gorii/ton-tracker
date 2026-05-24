import type {
  DataQuality,
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

export default function ProviderStatus({
  providers,
  dataQuality,
  error,
}: Props) {
  const mode = providers?.data_mode ?? dataQuality?.mode ?? "unknown";

  return (
    <section className="provider-status-card">
      <div className="provider-status-head">
        <h3>Data mode / Provider status</h3>
        <span
          className={`badge ${mode === "real" ? "badge-real" : "badge-mock"}`}
        >
          {mode === "real" ? "REAL MODE" : "MOCK MODE"}
        </span>
      </div>

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

      {dataQuality && dataQuality.warnings.length > 0 && (
        <ul className="dq-warnings">
          {dataQuality.warnings.map((w, i) => (
            <li key={i}>⚠ {w}</li>
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
