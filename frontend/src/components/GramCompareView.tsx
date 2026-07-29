import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowsLeftRight,
  Check,
  DownloadSimple,
  Info,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import {
  compareWalletRuns,
  walletClusterCompareCsvExportUrl,
  walletClusterCompareExportUrl,
} from "../api";
import type {
  WalletClusterCompareResponse,
  WalletIngestionRunCatalogItem,
  WalletIngestionRunResponse,
} from "../types";
import { useWalletRunCatalog } from "../useWalletRunCatalog";
import { validateWalletClusterComparison } from "../walletClusterComparison";

const MAX_VISIBLE_SELECTION = 8;

export default function GramCompareView({
  activeRun,
  onOpenActivity,
}: {
  activeRun: WalletIngestionRunResponse | null;
  onOpenActivity: () => void;
}) {
  const catalog = useWalletRunCatalog();
  const availableRuns = useMemo(
    () => withActiveRun(catalog.runs, activeRun),
    [catalog.runs, activeRun],
  );
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [result, setResult] = useState<WalletClusterCompareResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const controller = useRef<AbortController | null>(null);

  useEffect(() => {
    setSelectedIds((current) => {
      const available = new Map(availableRuns.map((run) => [Number(run.run_id), run]));
      const retained = current.filter((id) => available.has(id));
      if (retained.length) {
        const mode = available.get(retained[0])?.data_mode;
        return retained.filter((id) => available.get(id)?.data_mode === mode).slice(0, MAX_VISIBLE_SELECTION);
      }
      const preferred = activeRun && available.has(activeRun.run_id)
        ? available.get(activeRun.run_id)
        : availableRuns[0];
      if (!preferred) return [];
      return availableRuns
        .filter((run) => run.data_mode === preferred.data_mode)
        .slice(0, 2)
        .map((run) => Number(run.run_id));
    });
  }, [availableRuns, activeRun?.run_id]);

  useEffect(
    () => () => controller.current?.abort(),
    [],
  );

  useEffect(() => {
    controller.current?.abort();
    controller.current = null;
    setLoading(false);
    setResult(null);
    setError(null);
  }, [selectedIds.join(":")]);

  const selectedMode = availableRuns.find((run) => Number(run.run_id) === selectedIds[0])?.data_mode ?? null;
  const canCompare = selectedIds.length >= 2 && !loading;

  function toggleRun(run: WalletIngestionRunCatalogItem) {
    if (loading) return;
    const id = Number(run.run_id);
    setSelectedIds((current) => {
      if (current.includes(id)) return current.filter((value) => value !== id);
      const currentMode = availableRuns.find((row) => Number(row.run_id) === current[0])?.data_mode;
      if ((currentMode && currentMode !== run.data_mode) || current.length >= MAX_VISIBLE_SELECTION) return current;
      return [...current, id];
    });
    setResult(null);
    setError(null);
  }

  async function compare() {
    if (!canCompare) return;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const value = await compareWalletRuns(selectedIds, nextController.signal);
      if (!nextController.signal.aborted) {
        setResult(validateWalletClusterComparison(value, selectedIds));
      }
    } catch (reason) {
      if (!nextController.signal.aborted) {
        setError(reason instanceof Error ? reason.message : "Wallet comparison is unavailable.");
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
        <div><span>Wallet comparison</span><h1>Compare behavior without guessing ownership</h1><p>Select saved runs from one data mode. Real comparisons use canonical native-activity ledgers; mock fixtures stay isolated.</p></div>
      </div>

      <section className="compare-policy-card">
        <Info size={22} weight="duotone" />
        <div><strong>Similarity is not identity.</strong><p>A high score can describe coordinated, service-driven or coincidental behavior. It never proves a shared owner.</p></div>
        <span>Cluster proof: no</span>
      </section>

      <section className="compare-builder-card">
        <header><div><span className="eyebrow">Select evidence runs</span><h2>{selectedIds.length} of {Math.min(availableRuns.length, MAX_VISIBLE_SELECTION)} selected</h2><p>Runs from live and mock modes cannot be mixed.</p></div><ArrowsLeftRight size={24} /></header>

        {catalog.loading && !availableRuns.length ? (
          <div className="compare-loading"><SpinnerGap className="spin" size={20} />Loading saved runs…</div>
        ) : availableRuns.length ? (
          <div className="compare-run-grid">
            {availableRuns.slice(0, MAX_VISIBLE_SELECTION).map((run) => {
              const id = Number(run.run_id);
              const selected = selectedIds.includes(id);
              const incompatible = Boolean(selectedMode && selectedMode !== run.data_mode);
              return (
                <button
                  type="button"
                  key={run.run_id}
                  className={selected ? "compare-run is-selected" : "compare-run"}
                  aria-pressed={selected}
                  disabled={loading || incompatible}
                  onClick={() => toggleRun(run)}
                  title={incompatible ? `Selection is locked to ${selectedMode} mode` : undefined}
                >
                  <span className={`run-mode mode-${run.data_mode}`} />
                  <div><strong>Run #{run.run_id}</strong><small>{run.wallet_hint} · {run.time_window}</small></div>
                  <em>{run.data_mode}</em>
                  <i>{selected && <Check size={14} weight="bold" />}</i>
                </button>
              );
            })}
          </div>
        ) : (
          <div className="compare-empty"><strong>No saved runs yet.</strong><p>Create at least two runs to compare wallet behavior.</p><button className="button-secondary" type="button" onClick={onOpenActivity}>Open activity <ArrowRight size={16} /></button></div>
        )}

        {catalog.error && <div className="compare-catalog-error" role="alert">Saved runs unavailable: {catalog.error}</div>}
        {availableRuns.length === 1 && <div className="compare-hint"><Info size={16} />Create one more {availableRuns[0].data_mode} run to unlock comparison.</div>}
        {selectedMode === "real" && <div className="compare-hint"><Info size={16} />Real-mode comparison requires each selected run to have a ready canonical native-activity ledger.</div>}
        {error && <div className="activity-error" role="alert"><WarningCircle size={18} weight="fill" />{error}</div>}

        <div className="compare-actions">
          <p>{selectedIds.length < 2 ? "Select at least two compatible runs." : `${selectedIds.length * (selectedIds.length - 1) / 2} wallet pairs will be evaluated.`}</p>
          <button className="button-primary" type="button" disabled={!canCompare} onClick={() => void compare()}>
            {loading ? <SpinnerGap className="spin" size={18} /> : <ArrowsLeftRight size={18} />}
            {loading ? "Comparing…" : "Compare selected runs"}
          </button>
        </div>
      </section>

      {result && <ComparisonResult result={result} runIds={selectedIds} />}
    </>
  );
}

function ComparisonResult({ result, runIds }: { result: WalletClusterCompareResponse; runIds: number[] }) {
  const pairs = [...result.pairs].sort((left, right) => right.score - left.score);
  const average = pairs.reduce((total, pair) => total + pair.score, 0) / pairs.length;
  return (
    <div className="compare-result-stack">
      <section className="compare-summary-card">
        <div><span className="eyebrow">Comparison complete</span><h2>{pairs.length} pairwise signals</h2><p>{result.signal_basis === "canonical_native_activity_ledger" ? "Provider-free canonical native activity" : "Isolated mock-fixture behavior"}</p></div>
        <dl><div><dt>Wallets</dt><dd>{result.wallets.length}</dd></div><div><dt>Average</dt><dd>{average.toFixed(1)}</dd></div><div><dt>Window</dt><dd>{formatWindow(result.comparison_window_seconds)}</dd></div></dl>
        <div className="compare-export-actions"><a href={walletClusterCompareExportUrl(runIds)} download><DownloadSimple size={16} />JSON</a><a href={walletClusterCompareCsvExportUrl(runIds)} download><DownloadSimple size={16} />CSV</a></div>
      </section>

      <section className="pair-grid" aria-label="Wallet similarity pairs">
        {pairs.map((pair, index) => (
          <article className="pair-card" key={`${pair.wallet_a_run_id}-${pair.wallet_b_run_id}`}>
            <div className="pair-rank">#{index + 1}</div>
            <div className="pair-wallets"><span><small>Run #{pair.wallet_a_run_id}</small><strong title={pair.wallet_a_address}>{shortAddress(pair.wallet_a_address)}</strong></span><ArrowsLeftRight size={17} /><span><small>Run #{pair.wallet_b_run_id}</small><strong title={pair.wallet_b_address}>{shortAddress(pair.wallet_b_address)}</strong></span></div>
            <div className="pair-score" style={{ "--score": `${pair.score * 3.6}deg` } as React.CSSProperties}><strong>{pair.score.toFixed(1)}</strong><small>/100</small></div>
            <div className="pair-band"><span>{pair.band}</span><p>{pair.note}</p></div>
            <div className="pair-shared"><span>{pair.shared_counterparties.length} shared counterparties</span><span>{pair.shared_tokens.length} shared assets</span></div>
          </article>
        ))}
      </section>
      <p className="compare-result-note"><Info size={15} />{result.note}</p>
    </div>
  );
}

function withActiveRun(
  runs: WalletIngestionRunCatalogItem[],
  activeRun: WalletIngestionRunResponse | null,
): WalletIngestionRunCatalogItem[] {
  if (!activeRun || runs.some((run) => Number(run.run_id) === activeRun.run_id)) return runs;
  return [{
    run_id: String(activeRun.run_id),
    wallet_hint: shortAddress(activeRun.wallet_address),
    time_window: activeRun.time_window,
    created_at: activeRun.created_at,
    status: activeRun.status,
    data_mode: activeRun.data_mode,
  }, ...runs];
}

function shortAddress(value: string): string {
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-7)}` : value;
}

function formatWindow(seconds: number): string {
  if (seconds >= 86_400) return `${(seconds / 86_400).toFixed(seconds % 86_400 ? 1 : 0)}d`;
  return `${(seconds / 3_600).toFixed(seconds % 3_600 ? 1 : 0)}h`;
}
