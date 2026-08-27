import { useCallback, type ReactNode } from "react";
import {
  ArrowClockwise,
  CalendarBlank,
  ChartLineUp,
  Coins,
  Database,
  ShieldCheck,
  WarningCircle,
  Wallet,
} from "@phosphor-icons/react";

import {
  type WalletCase,
  type WalletCaseCoverageState,
  type WalletCaseSyncRequest,
} from "../walletCase";
import { useWalletCaseSyncJob } from "../useWalletCaseSyncJob";
import CaseSyncPanel from "./CaseSyncPanel";

const INITIAL_SYNC_REQUEST: WalletCaseSyncRequest = {
  mode: "bounded",
  time_window: "24h",
  surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"],
};

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

function snapshotStateLabel(state: string | undefined): string {
  if (state === "succeeded") return "Available";
  if (state === "partial") return "Available with limitations";
  return "Not available";
}

export default function GramCaseSummary({
  walletCase,
  refreshError,
  onRefresh,
}: {
  walletCase: WalletCase;
  refreshError: string | null;
  onRefresh: (background?: boolean) => Promise<void>;
}) {
  const caseId = walletCase.public_id;
  const refreshAfterTerminal = useCallback(async () => {
    await onRefresh(true);
  }, [onRefresh]);

  const syncController = useWalletCaseSyncJob({
    caseId,
    initialSync: walletCase?.latest_sync_attempt ?? null,
    onTerminal: refreshAfterTerminal,
  });

  const snapshot = walletCase.current_snapshot;
  const result = snapshot?.result ?? null;
  const summary = result?.summary ?? null;
  const counts = summary?.activity_counts ?? null;
  const activityTotal = counts
    ? counts.transfers + counts.transactions + counts.swaps
    : null;
  const environmentLabel = walletCase.data_environment === "live" ? "Live data" : "Demo data";
  const coverage = result?.coverage;
  const limitations = result?.limitations ?? walletCase.limitations;
  const summaryUnavailable = result === null || limitations.some(
    (item) => item.code === "summary_unavailable",
  );
  const defaultSyncRequest: WalletCaseSyncRequest = snapshot
    ? {
        mode: "incremental",
        time_window: "24h",
        surfaces: [...snapshot.requested_scope.surfaces],
      }
    : INITIAL_SYNC_REQUEST;

  return (
    <div className="case-summary-page">
      <CaseSyncPanel
        controller={syncController}
        hasSnapshot={snapshot !== null}
        defaultRequest={defaultSyncRequest}
      />

      {refreshError && (
        <div className="case-inline-error" role="alert">
          <WarningCircle size={18} weight="fill" />
          <span>Sync finished, but the updated case could not be loaded: {refreshError}</span>
          <button type="button" onClick={() => void onRefresh(true)}>Try again</button>
        </div>
      )}

      <section className="case-trust-strip" aria-label="Case trust boundaries">
        <div><Database size={19} /><span><small>Environment</small><strong>{environmentLabel}</strong></span></div>
        <div><CalendarBlank size={19} /><span><small>Coverage</small><strong>{coverageLabel(coverage?.state)}</strong></span></div>
        <div><ShieldCheck size={19} /><span><small>Full history</small><strong>Not proven</strong></span></div>
        <div><ArrowClockwise size={19} /><span><small>Published snapshot</small><strong>{formatDate(snapshot?.completed_at)}</strong></span></div>
      </section>

      <section className="case-metric-grid" aria-label="Wallet Case summary metrics">
        <CaseMetric icon={<ChartLineUp size={22} />} label="Returned activity rows" value={summaryUnavailable || activityTotal === null ? "Not available" : String(activityTotal)} detail={summaryUnavailable || !counts ? "No usable snapshot has published this metric" : `${counts.transactions} transactions · ${counts.swaps} provider-derived swaps; surfaces may overlap`} tone="blue" />
        <CaseMetric icon={<Coins size={22} />} label="Portfolio snapshot" value={summaryUnavailable || !summary ? "Not available" : formatUsd(summary.portfolio_snapshot.total_balance_usd)} detail={summaryUnavailable || !summary ? "No usable portfolio snapshot has been published" : `${summary.portfolio_snapshot.priced_assets} priced · ${summary.portfolio_snapshot.unpriced_assets} unpriced assets`} tone="coral" />
        <CaseMetric icon={<WarningCircle size={22} />} label="Data warnings" value={summaryUnavailable || !summary ? "Not available" : String(summary.warning_count)} detail={summaryUnavailable || !summary ? "Warning totals are not available without a usable snapshot" : `${summary.failed_transaction_count} failed transactions in the selected evidence`} tone="orange" />
        <CaseMetric icon={<Wallet size={22} />} label="Balance rows" value={summaryUnavailable || !counts ? "Not available" : String(counts.balances)} detail={summaryUnavailable || !counts ? "Balance-row totals have not been published" : "Point-in-time observations, not historical cost basis"} tone="aqua" />
      </section>

      <div className="case-detail-grid">
        <article className="case-detail-card">
          <header><div><span className="eyebrow">Current usable snapshot</span><h2>{snapshotStateLabel(snapshot?.state)}</h2></div><ArrowClockwise size={22} /></header>
          {snapshot && result ? (
            <dl className="case-definition-list">
              <div><dt>Snapshot ID</dt><dd><code>{snapshot.public_id}</code></dd></div>
              <div><dt>Provider</dt><dd>{snapshot.provider}</dd></div>
              <div><dt>Refresh mode</dt><dd>{snapshot.requested_scope.mode === "incremental" ? "Incremental overlap" : "Bounded interval"}</dd></div>
              <div><dt>Snapshot start</dt><dd>{formatDate(snapshot.requested_scope.start_at)}</dd></div>
              <div><dt>Snapshot end</dt><dd>{formatDate(snapshot.requested_scope.end_at)}</dd></div>
              <div><dt>Acquisition start</dt><dd>{formatDate(snapshot.requested_scope.acquisition_start_at)}</dd></div>
              <div><dt>Acquisition end</dt><dd>{formatDate(snapshot.requested_scope.acquisition_end_at)}</dd></div>
              {snapshot.requested_scope.mode === "incremental" && (
                <>
                  <div><dt>Safety overlap</dt><dd>{Math.round(snapshot.requested_scope.overlap_seconds / 60)} minutes</dd></div>
                  <div><dt>Base snapshot</dt><dd><code>{snapshot.requested_scope.base_snapshot_public_id}</code></dd></div>
                </>
              )}
              <div><dt>Surfaces</dt><dd>{snapshot.requested_scope.surfaces.join(", ")}</dd></div>
              <div><dt>Result note</dt><dd>{result.message}</dd></div>
            </dl>
          ) : (
            <div className="case-card-empty"><p>No usable snapshot exists yet. Metrics remain unavailable until a sync completes or publishes a partial result.</p></div>
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
            <div className="case-card-empty"><p>Coverage will be published with the first usable snapshot.</p></div>
          )}
        </article>
      </div>

      <section className="case-limitations">
        <header><WarningCircle size={22} weight="duotone" /><div><span className="eyebrow">Known limitations</span><h2>What this case does not prove</h2></div></header>
        <ul>{limitations.map((item) => <li key={item.code}><strong>{item.code.replace(/_/g, " ")}</strong><span>{item.message}</span></li>)}</ul>
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
