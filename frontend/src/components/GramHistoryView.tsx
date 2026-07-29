import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  ClockCounterClockwise,
  Info,
  Path,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import { inspectWalletHistoryReadiness } from "../api";
import type {
  WalletHistoryIntervalCoverageLayerRecord,
  WalletHistoryReadinessResponse,
  WalletIngestionRunCatalogItem,
  WalletIngestionRunResponse,
} from "../types";
import { useWalletRunCatalog } from "../useWalletRunCatalog";
import {
  historyCoveragePercent,
  validateWalletHistoryReadiness,
} from "../walletHistoryReadiness";

const MAX_SELECTION = 8;

export default function GramHistoryView({
  activeRun,
  onOpenActivity,
}: {
  activeRun: WalletIngestionRunResponse | null;
  onOpenActivity: () => void;
}) {
  const catalog = useWalletRunCatalog();
  const runs = useMemo(() => withActiveRun(catalog.runs, activeRun), [catalog.runs, activeRun]);
  const [targetRunId, setTargetRunId] = useState<number | null>(null);
  const [selectedRunIds, setSelectedRunIds] = useState<number[]>([]);
  const [result, setResult] = useState<WalletHistoryReadinessResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    setTargetRunId((current) => {
      if (current && runs.some((run) => Number(run.run_id) === current)) return current;
      if (activeRun && runs.some((run) => Number(run.run_id) === activeRun.run_id)) return activeRun.run_id;
      return runs[0] ? Number(runs[0].run_id) : null;
    });
  }, [runs, activeRun?.run_id]);

  const targetRun = runs.find((run) => Number(run.run_id) === targetRunId) ?? null;
  const compatibleRuns = useMemo(
    () => targetRun
      ? runs.filter((run) => run.data_mode === targetRun.data_mode && run.wallet_hint === targetRun.wallet_hint)
      : [],
    [runs, targetRun],
  );

  useEffect(() => {
    if (!targetRunId) {
      setSelectedRunIds([]);
      return;
    }
    const compatibleIds = compatibleRuns.map((run) => Number(run.run_id));
    setSelectedRunIds((current) => {
      const retained = current.filter((id) => compatibleIds.includes(id) && id !== targetRunId);
      const fallback = compatibleIds.find((id) => id !== targetRunId);
      return [targetRunId, ...(retained.length ? retained : fallback ? [fallback] : [])].slice(0, MAX_SELECTION);
    });
  }, [compatibleRuns, targetRunId]);

  useEffect(() => () => controller.current?.abort(), []);

  useEffect(() => {
    controller.current?.abort();
    controller.current = null;
    setLoading(false);
    setResult(null);
    setError(null);
  }, [targetRunId, selectedRunIds.join(":")]);

  const canInspect = Boolean(targetRunId && selectedRunIds.length >= 2 && !loading);

  function chooseTarget(run: WalletIngestionRunCatalogItem) {
    if (loading) return;
    setTargetRunId(Number(run.run_id));
  }

  function toggleRun(run: WalletIngestionRunCatalogItem) {
    if (loading || !targetRun || run.data_mode !== targetRun.data_mode || run.wallet_hint !== targetRun.wallet_hint) return;
    const id = Number(run.run_id);
    if (id === targetRunId) return;
    setSelectedRunIds((current) => current.includes(id)
      ? current.filter((value) => value !== id)
      : current.length < MAX_SELECTION ? [...current, id] : current);
  }

  async function inspect() {
    if (!canInspect || !targetRunId) return;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const response = await inspectWalletHistoryReadiness(
        { target_run_id: targetRunId, run_ids: selectedRunIds },
        nextController.signal,
      );
      if (!nextController.signal.aborted) {
        setResult(validateWalletHistoryReadiness(response, targetRunId, selectedRunIds));
      }
    } catch (reason) {
      if (!nextController.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "History evidence is unavailable.");
      }
    } finally {
      if (!nextController.signal.aborted) {
        controller.current = null;
        setLoading(false);
      }
    }
  }

  return (
    <>
      <div className="page-heading">
        <div><span>History evidence</span><h1>See what the selected runs cover — and what they do not</h1><p>Inspect bounded acquisition intervals, identity coverage and blockers for persisted runs of one wallet.</p></div>
      </div>

      <section className="history-policy-card">
        <Info size={22} weight="duotone" />
        <div><strong>Selected evidence is not complete wallet history.</strong><p>Transaction and provider-display streams remain separate. Time outside validated intervals stays unknown.</p></div>
        <div className="history-policy-flags"><span>No dedup</span><span>Not cost basis</span><span>Not PnL</span></div>
      </section>

      <section className="history-builder-card">
        <header><div><span className="eyebrow">Evidence scope</span><h2>{targetRun ? `Run #${targetRun.run_id} is the target` : "Choose a target run"}</h2><p>Matching wallet hints reduce mistakes; the backend still revalidates full canonical identity and data mode.</p></div><ClockCounterClockwise size={24} /></header>

        {catalog.loading && !runs.length ? (
          <div className="history-loading"><SpinnerGap className="spin" size={20} />Loading saved runs…</div>
        ) : runs.length ? (
          <div className="history-run-grid">
            {runs.slice(0, MAX_SELECTION).map((run) => {
              const id = Number(run.run_id);
              const target = id === targetRunId;
              const selected = selectedRunIds.includes(id);
              const compatible = !targetRun || (run.data_mode === targetRun.data_mode && run.wallet_hint === targetRun.wallet_hint);
              return (
                <article className={target ? "history-run is-target" : selected ? "history-run is-selected" : "history-run"} key={run.run_id}>
                  <button className="history-run-main" type="button" disabled={loading || !compatible || target} aria-pressed={selected} onClick={() => toggleRun(run)}>
                    <i>{selected && <Check size={13} weight="bold" />}</i>
                    <span><strong>Run #{run.run_id}</strong><small>{run.wallet_hint} · {run.time_window} · {run.data_mode}</small></span>
                  </button>
                  {target ? <em>Target</em> : <button className="history-target-action" type="button" disabled={loading} onClick={() => chooseTarget(run)}>Use as target</button>}
                </article>
              );
            })}
          </div>
        ) : (
          <div className="history-empty"><Path size={28} weight="duotone" /><strong>No persisted runs</strong><p>Create at least two runs for the same wallet.</p><button className="button-secondary" type="button" onClick={onOpenActivity}>Open activity <ArrowRight size={16} /></button></div>
        )}

        {catalog.error && <div className="history-catalog-error" role="alert">Saved runs unavailable: {catalog.error}</div>}
        {targetRun && compatibleRuns.length < 2 && <div className="history-hint"><Info size={16} />Create another {targetRun.data_mode} run for wallet {targetRun.wallet_hint} to inspect history evidence.</div>}
        {error && <div className="activity-error" role="alert"><WarningCircle size={18} weight="fill" />{error}</div>}

        <div className="history-actions">
          <p>{selectedRunIds.length < 2 ? "Two matching runs are required." : `${selectedRunIds.length} runs selected · target included automatically.`}</p>
          <button className="button-primary" type="button" disabled={!canInspect} onClick={() => void inspect()}>{loading ? <SpinnerGap className="spin" size={18} /> : <Path size={18} />}{loading ? "Inspecting…" : "Inspect history evidence"}</button>
        </div>
      </section>

      {result && <HistoryResult result={result} />}
    </>
  );
}

function HistoryResult({ result }: { result: WalletHistoryReadinessResponse }) {
  const coverage = result.coverage;
  return (
    <div className="history-result-stack">
      <section className="history-summary-card">
        <div><span className="eyebrow">Diagnostic complete</span><h2>Coverage remains bounded</h2><p>{result.wallet_address}</p></div>
        <dl><div><dt>Runs</dt><dd>{result.run_ids.length}</dd></div><div><dt>Observations</dt><dd>{coverage.activity_observations}</dd></div><div><dt>Blockers</dt><dd>{result.blockers.length}</dd></div></dl>
        <span className="history-not-ready">Full history: no</span>
      </section>

      <div className="history-layer-grid">
        <HistoryLayer title="Low-level transactions" description="Validated bounded transaction acquisition only." layer={result.bounded_interval_coverage.low_level_transactions} />
        <HistoryLayer title="Provider-display events" description="Display actions remain non-authoritative activity." layer={result.bounded_interval_coverage.provider_display_events} />
      </div>

      <section className="history-identity-card">
        <header><div><span className="eyebrow">Identity health</span><h2>Can observations be joined safely?</h2></div><Path size={22} /></header>
        <div className="history-identity-grid">
          <IdentityMetric label="Exact transactions" value={`${coverage.transaction_observations_with_exact_identity}/${coverage.transaction_observations}`} state={coverage.transaction_identity_coverage_state} />
          <IdentityMetric label="Scoped event actions" value={`${coverage.event_action_observations_with_provider_scoped_identity}/${coverage.event_action_observations}`} state={coverage.event_action_identity_coverage_state} />
          <IdentityMetric label="Addressed asset legs" value={`${coverage.addressed_non_ton_swap_legs}/${coverage.non_ton_swap_legs}`} state={coverage.asset_address_coverage_state} />
          <IdentityMetric label="Fee-link candidates" value={`${coverage.same_run_fee_hash_match_candidates}/${coverage.fee_link_candidate_swaps}`} state={coverage.fee_hash_match_coverage_state} />
        </div>
      </section>

      <section className="history-blocker-card">
        <header><div><span className="eyebrow">Why history stays locked</span><h2>{result.blockers.length ? `${result.blockers.length} explicit blocker${result.blockers.length === 1 ? "" : "s"}` : "No blocker records returned"}</h2></div><WarningCircle size={23} weight="duotone" /></header>
        {result.blockers.length ? <div className="history-blocker-list">{result.blockers.map((blocker) => <article key={blocker.code}><strong>{humanize(blocker.code)}</strong><p>{blocker.reason}</p>{blocker.run_ids.length > 0 && <span>Runs {blocker.run_ids.map((id) => `#${id}`).join(", ")}</span>}</article>)}</div> : <p className="history-blocker-empty">No additional blocker rows were returned. The immutable safety flags above still remain false.</p>}
      </section>

      <p className="history-result-note"><Info size={15} />{result.note}</p>
    </div>
  );
}

function HistoryLayer({ title, description, layer }: { title: string; description: string; layer: WalletHistoryIntervalCoverageLayerRecord }) {
  const percent = historyCoveragePercent(layer);
  return (
    <article className="history-layer-card">
      <header><div><span className="eyebrow">{layer.stream_key.replace("_", " ")}</span><h2>{title}</h2><p>{description}</p></div><span className={`history-layer-state state-${layer.selected_run_coverage_state}`}>{layer.selected_run_coverage_state}</span></header>
      <div className="history-coverage-track" aria-label={`${percent}% of selected runs included`}><i style={{ width: `${percent}%` }} /></div>
      <dl><div><dt>Included</dt><dd>{layer.included_run_count}/{layer.selected_run_count}</dd></div><div><dt>Internal gaps</dt><dd>{layer.gap_intervals.length}</dd></div><div><dt>Overlaps</dt><dd>{layer.overlap_intervals.length}</dd></div><div><dt>Outside span</dt><dd>Unknown</dd></div></dl>
      <footer><span>{humanize(layer.state)}</span><small>{formatDuration(layer.covered_duration_microseconds)} covered inside accepted intervals</small></footer>
    </article>
  );
}

function IdentityMetric({ label, value, state }: { label: string; value: string; state: string }) {
  return <div><span>{label}</span><strong>{value}</strong><small className={`identity-state state-${state}`}>{humanize(state)}</small></div>;
}

function withActiveRun(runs: WalletIngestionRunCatalogItem[], activeRun: WalletIngestionRunResponse | null): WalletIngestionRunCatalogItem[] {
  if (!activeRun || runs.some((run) => Number(run.run_id) === activeRun.run_id)) return runs;
  return [{ run_id: String(activeRun.run_id), wallet_hint: catalogHint(activeRun.wallet_address), time_window: activeRun.time_window, created_at: activeRun.created_at, status: activeRun.status, data_mode: activeRun.data_mode }, ...runs];
}

function catalogHint(address: string): string {
  return address.length >= 16 ? `${address.slice(0, 6)}…${address.slice(-4)}` : "stored…run";
}

function formatDuration(microseconds: string): string {
  const seconds = Number(microseconds) / 1_000_000;
  if (!Number.isFinite(seconds) || seconds <= 0) return "0s";
  if (seconds >= 86_400) return `${(seconds / 86_400).toFixed(1)}d`;
  if (seconds >= 3_600) return `${(seconds / 3_600).toFixed(1)}h`;
  return `${Math.round(seconds)}s`;
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (character: string) => character.toUpperCase());
}
