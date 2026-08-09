import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  DownloadSimple,
  Gauge,
  Info,
  Sparkle,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import {
  getWalletRunSignals,
  walletRunSignalsCsvExportUrl,
  walletRunSignalsExportUrl,
} from "../api";
import type {
  WalletEvidenceSignalRecord,
  WalletIngestionRunResponse,
  WalletRunSignalsResponse,
} from "../types";
import { validateWalletRunSignalsResponse } from "../walletRunSignals";

export default function GramInsightsView({
  activeRun,
  onOpenActivity,
}: {
  activeRun: WalletIngestionRunResponse | null;
  onOpenActivity: () => void;
}) {
  const [result, setResult] = useState<WalletRunSignalsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setResult(null);
    setError(null);
    if (!activeRun) return;
    const controller = new AbortController();
    setLoading(true);
    void getWalletRunSignals(activeRun.run_id, controller.signal)
      .then((value) => {
        if (controller.signal.aborted) return;
        setResult(
          validateWalletRunSignalsResponse(
            value,
            activeRun.run_id,
            activeRun.wallet_address,
          ),
        );
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Wallet insights are unavailable.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [activeRun?.run_id, activeRun?.wallet_address]);

  if (!activeRun) {
    return (
      <>
        <InsightsHeading />
        <section className="clean-empty-state insights-empty">
          <span><Sparkle size={30} weight="duotone" /></span>
          <h2>No evidence run selected</h2>
          <p>Create or load a run first. Insights are calculated only from its persisted, source-labelled rows.</p>
          <button className="button-secondary" type="button" onClick={onOpenActivity}>Open activity <ArrowRight size={17} /></button>
        </section>
      </>
    );
  }

  return (
    <>
      <InsightsHeading />
      <section className="insight-policy-card">
        <Info size={22} weight="duotone" />
        <div><strong>Patterns, not a verdict.</strong><p>Confidence describes evidence volume, not danger. No matched rule never means that a wallet is verified safe.</p></div>
        <span>Risk score disabled</span>
      </section>

      {loading && <section className="insights-loading"><SpinnerGap className="spin" size={22} />Evaluating six transparent rules…</section>}
      {error && <div className="activity-error insights-error" role="alert"><WarningCircle size={18} weight="fill" />{error}</div>}
      {result && <InsightsResult result={result} runId={activeRun.run_id} />}
    </>
  );
}

function InsightsHeading() {
  return (
    <div className="page-heading">
      <div><span>Explainable insights</span><h1>Patterns worth a closer look</h1><p>Rule-based observations with visible evidence, confidence and limitations — never an opaque wallet score.</p></div>
    </div>
  );
}

function InsightsResult({ result, runId }: { result: WalletRunSignalsResponse; runId: number }) {
  const confidence = useMemo(() => ({
    high: result.signals.filter((row) => row.confidence === "high").length,
    medium: result.signals.filter((row) => row.confidence === "medium").length,
    low: result.signals.filter((row) => row.confidence === "low").length,
  }), [result]);
  const unmatched = result.evaluated.length - result.signals.length - result.insufficient_evidence.length;

  return (
    <div className="insights-stack">
      <section className="insights-overview-card">
        <div className="insights-overview-copy">
          <span className="eyebrow">Run #{runId}</span>
          <h2>{result.signals.length ? `${result.signals.length} heuristic ${result.signals.length === 1 ? "pattern" : "patterns"} matched` : "No heuristic pattern matched"}</h2>
          <p>{result.signals.length ? "Review each observation together with its exact evidence and alternative explanations." : "The evaluated rules did not match. This is not a safety assessment or proof of normal behavior."}</p>
        </div>
        <dl className="insight-metrics">
          <div><dt>Evaluated</dt><dd>{result.evaluated.length}</dd></div>
          <div><dt>Matched</dt><dd>{result.signals.length}</dd></div>
          <div><dt>Insufficient</dt><dd>{result.insufficient_evidence.length}</dd></div>
          <div><dt>No match</dt><dd>{Math.max(unmatched, 0)}</dd></div>
        </dl>
        <ConfidenceDistribution counts={confidence} total={result.signals.length} />
        <div className="insight-export-actions">
          <a href={walletRunSignalsExportUrl(runId)} download><DownloadSimple size={16} />JSON</a>
          <a href={walletRunSignalsCsvExportUrl(runId)} download><DownloadSimple size={16} />CSV</a>
        </div>
      </section>

      {result.signals.length ? (
        <section className="signal-grid" aria-label="Matched evidence signals">
          {result.signals.map((signal) => <SignalCard key={signal.code} signal={signal} />)}
        </section>
      ) : (
        <section className="signal-clear-state"><CheckCircle size={25} weight="duotone" /><div><strong>No rule matched this run.</strong><p>Continue reviewing source coverage, warnings and proofs; this result is deliberately not labelled safe.</p></div></section>
      )}

      <section className="insufficient-card">
        <header><div><span className="eyebrow">Evidence gaps</span><h2>{result.insufficient_evidence.length} rules could not be evaluated reliably</h2></div><Gauge size={22} /></header>
        {result.insufficient_evidence.length ? (
          <div className="insufficient-list">
            {result.insufficient_evidence.map((row) => (
              <article key={row.code}><span>{humanizeCode(row.code)}</span><p>{brandText(row.reason)}</p></article>
            ))}
          </div>
        ) : <p className="insufficient-none">Every rule had enough input data to produce either a match or a no-match result.</p>}
      </section>
    </div>
  );
}

function ConfidenceDistribution({ counts, total }: { counts: { high: number; medium: number; low: number }; total: number }) {
  return (
    <div className="confidence-distribution">
      <div><span>Evidence confidence</span><small>Based on sample volume</small></div>
      <div className="confidence-track" aria-label={`Confidence distribution: ${counts.high} high, ${counts.medium} medium, ${counts.low} low`}>
        {total === 0 ? <i className="is-empty" /> : (
          <>{counts.high > 0 && <i className="is-high" style={{ width: `${counts.high / total * 100}%` }} />}{counts.medium > 0 && <i className="is-medium" style={{ width: `${counts.medium / total * 100}%` }} />}{counts.low > 0 && <i className="is-low" style={{ width: `${counts.low / total * 100}%` }} />}</>
        )}
      </div>
      <div className="confidence-legend"><span><i className="is-high" />{counts.high} high</span><span><i className="is-medium" />{counts.medium} medium</span><span><i className="is-low" />{counts.low} low</span></div>
    </div>
  );
}

function SignalCard({ signal }: { signal: WalletEvidenceSignalRecord }) {
  return (
    <article className={`signal-card confidence-${signal.confidence}`}>
      <header><span><Sparkle size={18} weight="fill" /></span><div><small>{humanizeCode(signal.code)}</small><h2>{brandText(signal.title)}</h2></div><b>{signal.confidence} confidence</b></header>
      <p className="signal-observation">{brandText(signal.observation)}</p>
      <dl className="signal-evidence">
        {Object.entries(signal.evidence).map(([key, value]) => <div key={key}><dt>{humanizeCode(key)}</dt><dd title={formatEvidence(value)}>{brandText(formatEvidence(value))}</dd></div>)}
      </dl>
      <p className="signal-note"><Info size={15} />{brandText(signal.note)}</p>
    </article>
  );
}

function formatEvidence(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function humanizeCode(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (letter: string) => letter.toUpperCase());
}

function brandText(value: string): string {
  return value;
}
