import { useCallback, useEffect, useState, type ReactNode } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  CalendarBlank,
  ChartLineUp,
  Coins,
  Database,
  ShieldCheck,
  SpinnerGap,
  WarningCircle,
  Wallet,
} from "@phosphor-icons/react";
import { createWalletCaseSync, getWalletCase } from "../api";
import {
  walletCaseEnvironmentLabel,
  type WalletCase,
  type WalletCaseCoverageState,
} from "../walletCase";

const DEFAULT_SURFACES = [
  "transfers",
  "transactions",
  "swaps",
  "balances",
  "jettons",
] as const;

function shortAddress(value: string): string {
  if (value.length <= 24) return value;
  return `${value.slice(0, 12)}…${value.slice(-9)}`;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatUsd(value: string | null): string {
  if (value === null) return "Not available";
  const amount = Number(value);
  return Number.isFinite(amount)
    ? amount.toLocaleString(undefined, { style: "currency", currency: "USD" })
    : value;
}

function coverageLabel(state: WalletCaseCoverageState | undefined): string {
  switch (state) {
    case "bounded_complete":
      return "Selected interval covered";
    case "bounded_partial":
      return "Partial interval coverage";
    default:
      return "Coverage not established";
  }
}

export default function GramCaseSummary({
  caseId,
  onOpenLegacyActivity,
}: {
  caseId: string;
  onOpenLegacyActivity?: (walletAddress: string) => void;
}) {
  const [walletCase, setWalletCase] = useState<WalletCase | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const result = await getWalletCase(caseId, signal);
      setWalletCase(result);
    } catch (caught) {
      if (signal?.aborted) return;
      setError(caught instanceof Error ? caught.message : "Wallet Case is unavailable");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [caseId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  async function syncLastDay() {
    if (!walletCase || syncing) return;
    setSyncing(true);
    setSyncError(null);
    try {
      await createWalletCaseSync(walletCase.public_id, {
        time_window: "24h",
        surfaces: [...DEFAULT_SURFACES],
      });
      await load();
    } catch (caught) {
      setSyncError(caught instanceof Error ? caught.message : "Wallet Case sync failed");
    } finally {
      setSyncing(false);
    }
  }

  if (loading) {
    return (
      <section className="case-state-panel" aria-live="polite">
        <SpinnerGap className="spin" size={25} />
        <div><h1>Opening Wallet Case</h1><p>Loading persisted scope and evidence summary…</p></div>
      </section>
    );
  }

  if (error || !walletCase) {
    return (
      <section className="case-state-panel is-error" role="alert">
        <WarningCircle size={27} weight="fill" />
        <div><h1>Wallet Case unavailable</h1><p>{error ?? "The response did not contain a Wallet Case."}</p></div>
        <button type="button" className="button-secondary" onClick={() => void load()}>
          Try again <ArrowClockwise size={17} />
        </button>
      </section>
    );
  }

  const latest = walletCase.latest_sync;
  const counts = walletCase.summary.activity_counts;
  const activityTotal = counts.transfers + counts.transactions + counts.swaps;
  const environmentLabel = walletCaseEnvironmentLabel(walletCase.data_environment);
  const coverage = latest?.coverage;
  const summaryUnavailable = walletCase.limitations.some(
    (item) => item.code === "summary_unavailable",
  );

  return (
    <div className="case-summary-page">
      <header className="case-heading">
        <div>
          <div className="case-eyebrow-row">
            <span>Wallet Case</span>
            <strong className={`case-mode-badge is-${walletCase.data_environment}`}>
              {environmentLabel}
            </strong>
            <strong className="case-network-badge">
              {walletCase.network === "ton-mainnet" ? "TON mainnet" : "TON testnet"}
            </strong>
          </div>
          <h1>{walletCase.label ?? shortAddress(walletCase.display_address)}</h1>
          <p>
            One persistent case for this canonical TON address. Every result below remains
            bounded by its selected interval and evidence source.
          </p>
          <code title={walletCase.canonical_wallet_key}>{walletCase.canonical_wallet_key}</code>
        </div>
        <button className="button-primary case-sync-button" type="button" onClick={syncLastDay} disabled={syncing}>
          {syncing ? <SpinnerGap className="spin" size={18} /> : <ArrowClockwise size={18} />}
          {syncing ? "Syncing bounded data…" : "Sync last 24 hours"}
        </button>
      </header>

      {syncError && <div className="case-inline-error" role="alert"><WarningCircle size={18} weight="fill" />{syncError}</div>}

      <section className="case-trust-strip" aria-label="Case trust boundaries">
        <div><Database size={19} /><span><small>Environment</small><strong>{environmentLabel}</strong></span></div>
        <div><CalendarBlank size={19} /><span><small>Coverage</small><strong>{coverageLabel(coverage?.state)}</strong></span></div>
        <div><ShieldCheck size={19} /><span><small>Full history</small><strong>Not proven</strong></span></div>
        <div><ArrowClockwise size={19} /><span><small>Last sync</small><strong>{formatDate(latest?.completed_at)}</strong></span></div>
      </section>

      <section className="case-metric-grid" aria-label="Wallet Case summary metrics">
        <CaseMetric icon={<ChartLineUp size={22} />} label="Returned activity rows" value={summaryUnavailable ? "Not available" : String(activityTotal)} detail={summaryUnavailable ? "This sync predates compact summary capture" : `${counts.transactions} transactions · ${counts.swaps} provider-derived swaps; surfaces may overlap`} tone="blue" />
        <CaseMetric icon={<Coins size={22} />} label="Portfolio snapshot" value={summaryUnavailable ? "Not available" : formatUsd(walletCase.summary.portfolio_snapshot.total_balance_usd)} detail={summaryUnavailable ? "No portfolio aggregate was captured for this sync" : `${walletCase.summary.portfolio_snapshot.priced_assets} priced · ${walletCase.summary.portfolio_snapshot.unpriced_assets} unpriced assets`} tone="coral" />
        <CaseMetric icon={<WarningCircle size={22} />} label="Data warnings" value={summaryUnavailable ? "Not available" : String(walletCase.summary.warning_count)} detail={summaryUnavailable ? "Warning totals are unavailable for this sync" : `${walletCase.summary.failed_transaction_count} failed transactions in the selected evidence`} tone="orange" />
        <CaseMetric icon={<Wallet size={22} />} label="Balance rows" value={summaryUnavailable ? "Not available" : String(counts.balances)} detail={summaryUnavailable ? "Balance-row totals were not captured" : "Point-in-time observations, not historical cost basis"} tone="aqua" />
      </section>

      <div className="case-detail-grid">
        <article className="case-detail-card">
          <header><div><span className="eyebrow">Latest bounded sync</span><h2>{latest ? latest.state : "Not started"}</h2></div><ArrowClockwise size={22} /></header>
          {latest ? (
            <dl className="case-definition-list">
              <div><dt>Provider</dt><dd>{latest.provider}</dd></div>
              <div><dt>Requested window</dt><dd>{latest.requested_scope.time_window}</dd></div>
              <div><dt>Interval start</dt><dd>{formatDate(latest.requested_scope.start_at)}</dd></div>
              <div><dt>Interval end</dt><dd>{formatDate(latest.requested_scope.end_at)}</dd></div>
              <div><dt>Surfaces</dt><dd>{latest.requested_scope.surfaces.join(", ")}</dd></div>
              <div><dt>Stage</dt><dd>{latest.stage}</dd></div>
              <div><dt>Result note</dt><dd>{latest.message}</dd></div>
            </dl>
          ) : (
            <div className="case-card-empty"><p>No sync has been run for this case. Start with a bounded 24-hour interval.</p></div>
          )}
        </article>

        <article className="case-detail-card">
          <header><div><span className="eyebrow">Coverage and gaps</span><h2>{coverageLabel(coverage?.state)}</h2></div><ShieldCheck size={22} /></header>
          {coverage ? (
            <>
              <div className="case-coverage-row"><span>Requested</span><strong>{coverage.requested_surfaces.length} surfaces</strong></div>
              <div className="case-coverage-row"><span>Incomplete</span><strong>{coverage.incomplete_surfaces.length}</strong></div>
              <div className="case-coverage-row"><span>Unavailable</span><strong>{coverage.unavailable_surfaces.length}</strong></div>
              <div className="case-coverage-row"><span>Provider streams</span><strong>{coverage.streams.length}</strong></div>
            </>
          ) : (
            <div className="case-card-empty"><p>Coverage will be calculated from the first persisted sync.</p></div>
          )}
        </article>
      </div>

      <section className="case-limitations">
        <header><WarningCircle size={22} weight="duotone" /><div><span className="eyebrow">Known limitations</span><h2>What this case does not prove</h2></div></header>
        <ul>{walletCase.limitations.map((item) => <li key={item.code}><strong>{item.code.replace(/_/g, " ")}</strong><span>{item.message}</span></li>)}</ul>
      </section>

      <section className="case-next-slice">
        <div><span className="eyebrow">Compatibility view</span><h2>Need the detailed run tools?</h2><p>The new Summary keeps run IDs internal. The existing Activity workspace remains available during the migration window.</p></div>
        {onOpenLegacyActivity && <button type="button" className="button-secondary" onClick={() => onOpenLegacyActivity(walletCase.display_address)}>Open advanced activity <ArrowRight size={17} /></button>}
      </section>
    </div>
  );
}

function CaseMetric({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
  tone: string;
}) {
  return <article className="case-metric"><span className={`tone-${tone}`}>{icon}</span><div><small>{label}</small><strong>{value}</strong><p>{detail}</p></div></article>;
}
