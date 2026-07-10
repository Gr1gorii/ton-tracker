import { useState, type FormEvent } from "react";
import { inspectWalletHistoryReadiness } from "../api";
import type {
  WalletHistoryAcceptedIntervalRecord,
  WalletHistoryGapIntervalRecord,
  WalletHistoryIntervalCoverageLayerRecord,
  WalletHistoryIntervalRecord,
  WalletHistoryIntervalRunEvidenceRecord,
  WalletHistoryOverlapIntervalRecord,
  WalletHistoryReadinessResponse,
} from "../types";
import PreviewReadinessStrip, {
  type PreviewReadinessTone,
} from "./PreviewReadinessStrip";
import { parseSelectedRunIds } from "./selectedRunIds";

interface WalletHistoryIntervalCoverageCardProps {
  targetRunId: number;
}

export default function WalletHistoryIntervalCoverageCard({
  targetRunId,
}: WalletHistoryIntervalCoverageCardProps) {
  const [otherRunIds, setOtherRunIds] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] =
    useState<WalletHistoryReadinessResponse | null>(null);

  const inputId = `wallet-history-other-runs-${targetRunId}`;
  const helpId = `${inputId}-help`;
  const readiness = intervalReadiness({ loading, error, result });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parseSelectedRunIds(otherRunIds, targetRunId);
    if ("error" in parsed) {
      setError(parsed.error);
      setResult(null);
      return;
    }

    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const data = await inspectWalletHistoryReadiness({
        target_run_id: targetRunId,
        run_ids: parsed.runIds,
      });
      setResult(data);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Interval coverage inspection failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  function handleRunIdsChange(value: string) {
    setOtherRunIds(value);
    setError(null);
    setResult(null);
  }

  return (
    <section
      className="intelligence-table-block interval-coverage-card"
      aria-labelledby={`interval-coverage-title-${targetRunId}`}
    >
      <div className="table-toolbar interval-coverage-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Diagnostic only</span>
          <h2 id={`interval-coverage-title-${targetRunId}`}>
            Selected-run interval coverage
          </h2>
          <p>
            Compare validated bounded stream intervals for selected stored runs.
            Time outside the earliest and latest eligible bounds is unknown.
          </p>
        </div>
        <div className="table-meta" aria-label="Interval coverage limitations">
          <span className="badge badge-mock">NOT GLOBAL HISTORY</span>
          <span className="badge badge-mock">NO DEDUPLICATION</span>
          <span className="badge badge-mock">NOT USED BY PNL</span>
        </div>
      </div>

      <div className="interval-coverage-safety" role="note">
        <strong>Two evidence layers stay separate.</strong>
        <span>
          Low-level transaction intervals and provider-display event intervals
          are never combined. Neither layer establishes full wallet history,
          ownership, cost basis, or authoritative transfer/swap coverage.
        </span>
      </div>

      <form
        className="wallet-ingestion-form wallet-query-card interval-coverage-form"
        onSubmit={handleSubmit}
      >
        <div className="field">
          <label className="field-label" htmlFor={inputId}>
            Other run IDs for interval check
          </label>
          <input
            id={inputId}
            className="text-input"
            type="text"
            value={otherRunIds}
            disabled={loading}
            maxLength={512}
            placeholder="e.g. 12, 15, 20"
            aria-describedby={helpId}
            onChange={(event) => handleRunIdsChange(event.target.value)}
          />
          <small className="interval-coverage-help" id={helpId}>
            Run #{targetRunId} is the target and is included automatically. Add
            1–49 runs for the same wallet and data mode.
          </small>
        </div>
        <button
          className="btn btn-primary"
          type="submit"
          disabled={loading || otherRunIds.trim() === ""}
        >
          {loading ? "Inspecting intervals" : "Inspect interval coverage"}
        </button>
      </form>

      <PreviewReadinessStrip
        tone={readiness.tone}
        label={readiness.label}
        message={readiness.message}
        items={[
          { label: "Target", value: `Run #${targetRunId}` },
          {
            label: "Selected runs",
            value: result ? String(result.run_ids.length) : "2–50 required",
          },
          { label: "Scope", value: "Bounded intervals only" },
        ]}
      />

      {result && (
        <div className="interval-coverage-results">
          <div className="interval-contract-strip" role="note">
            <div>
              <span>Contract</span>
              <strong>
                {result.bounded_interval_coverage.contract_version}
              </strong>
            </div>
            <div>
              <span>Interval semantics</span>
              <strong>
                {result.bounded_interval_coverage.interval_semantics}
              </strong>
            </div>
            <div>
              <span>Gap scope</span>
              <strong>Inside validated selected span only</strong>
            </div>
          </div>

          <IntervalCoverageLayer
            layer={result.bounded_interval_coverage.low_level_transactions}
            targetRunId={targetRunId}
            title="Low-level transaction intervals"
            description="Only runs with a validated complete bounded low-level transaction stream enter this union."
          />

          <IntervalCoverageLayer
            layer={result.bounded_interval_coverage.provider_display_events}
            targetRunId={targetRunId}
            title="Provider-display event intervals"
            description="This is TonAPI page-chain coverage for mutable display actions, not authoritative transfer or swap history."
            providerDisplay
          />

          <details className="interval-detail-block interval-blocker-details">
            <summary>
              <span>All history-readiness blockers</span>
              <span>{result.blockers.length}</span>
            </summary>
            {result.blockers.length === 0 ? (
              <p className="interval-empty-message">
                No additional blocker records were returned. Global history,
                cost-basis, deduplication, and PnL flags still remain false.
              </p>
            ) : (
              <ul className="interval-blocker-list">
                {result.blockers.map((blocker) => (
                  <li key={blocker.code}>
                    <strong>{blocker.code}</strong>
                    <span>{blocker.reason}</span>
                    {blocker.run_ids.length > 0 && (
                      <small>Runs {formatRunIds(blocker.run_ids)}</small>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </details>

          <p className="muted small interval-coverage-note">
            {result.bounded_interval_coverage.note} {result.note}
          </p>
        </div>
      )}
    </section>
  );
}

function intervalReadiness({
  loading,
  error,
  result,
}: {
  loading: boolean;
  error: string | null;
  result: WalletHistoryReadinessResponse | null;
}): { tone: PreviewReadinessTone; label: string; message: string } {
  if (loading) {
    return {
      tone: "running",
      label: "INSPECTING INTERVALS",
      message: "Validating bounded stream evidence for the selected runs.",
    };
  }
  if (error) {
    return { tone: "error", label: "INTERVAL CHECK FAILED", message: error };
  }
  if (result) {
    return {
      tone: "fresh",
      label: "DIAGNOSTIC READY",
      message: `${result.run_ids.length} runs inspected. Coverage remains bounded, selected-run scoped, and non-authoritative.`,
    };
  }
  return {
    tone: "warning",
    label: "RUNS REQUIRED",
    message: "Add at least one other stored run for the same wallet and data mode.",
  };
}

function IntervalCoverageLayer({
  layer,
  targetRunId,
  title,
  description,
  providerDisplay = false,
}: {
  layer: WalletHistoryIntervalCoverageLayerRecord;
  targetRunId: number;
  title: string;
  description: string;
  providerDisplay?: boolean;
}) {
  const layerId = `interval-layer-${layer.stream_key}-${targetRunId}`;
  const state = layerState(layer);

  return (
    <section className="interval-layer" aria-labelledby={`${layerId}-title`}>
      <div className="interval-layer-head">
        <div>
          <span className="section-eyebrow">
            {providerDisplay
              ? "Provider display acquisition"
              : "Validated low-level acquisition"}
          </span>
          <h3 id={`${layerId}-title`}>{title}</h3>
          <p>{description}</p>
        </div>
        <div className="table-meta" aria-label={`${title} state`}>
          <span className={`source-badge ${state.className}`}>
            {state.label}
          </span>
          {providerDisplay && (
            <span className="badge badge-mock">NON-AUTHORITATIVE</span>
          )}
        </div>
      </div>

      <div className="interval-layer-metrics">
        <IntervalMetric
          label="Eligible runs"
          value={`${layer.included_run_count}/${layer.selected_run_count}`}
          detail={layer.selected_run_coverage_state}
        />
        <IntervalMetric
          label="Selected span"
          value={formatDuration(layer.span_duration_microseconds)}
          detail={
            layer.selected_span
              ? `${formatTimestamp(layer.selected_span.start)} → ${formatTimestamp(layer.selected_span.end)}`
              : "No validated intervals"
          }
        />
        <IntervalMetric
          label="Internal gaps"
          value={String(layer.gap_intervals.length)}
          detail={formatDuration(layer.gap_duration_microseconds)}
        />
        <IntervalMetric
          label="Overlap segments"
          value={String(layer.overlap_intervals.length)}
          detail={`${formatDuration(layer.overlapped_duration_microseconds)} · max depth ${layer.max_coverage_depth}`}
        />
      </div>

      <RunEvidenceTable
        rows={layer.run_evidence}
        targetRunId={targetRunId}
        label={title}
      />

      <AcceptedIntervalsTable
        rows={layer.accepted_intervals}
        targetRunId={targetRunId}
        label={title}
      />

      <GapIntervals
        rows={layer.gap_intervals}
        layerId={layerId}
        state={layer.state}
      />

      <details className="interval-detail-block">
        <summary>
          <span>Validated union intervals</span>
          <span>{layer.union_intervals.length}</span>
        </summary>
        <PlainIntervalsTable
          rows={layer.union_intervals}
          caption={`${title}: server-computed union intervals.`}
        />
      </details>

      <OverlapIntervals rows={layer.overlap_intervals} title={title} />

      <div className="interval-layer-footnote" role="note">
        <strong>Outside selected span: unknown.</strong>
        <span>
          No gap is inferred before the earliest or after the latest validated
          interval. Activity rows are not merged or deduplicated.
        </span>
      </div>
    </section>
  );
}

function IntervalMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function RunEvidenceTable({
  rows,
  targetRunId,
  label,
}: {
  rows: WalletHistoryIntervalRunEvidenceRecord[];
  targetRunId: number;
  label: string;
}) {
  return (
    <div className="interval-table-section">
      <h4>Selected-run evidence</h4>
      <div className="table-wrap interval-table-wrap">
        <table className="data-table intelligence-table interval-table">
          <caption>{label}: evidence classification for every selected run.</caption>
          <thead>
            <tr>
              <th scope="col">Run</th>
              <th scope="col">Classification</th>
              <th scope="col">Source state</th>
              <th scope="col">Recorded bounds</th>
              <th scope="col">Accepted bounds</th>
              <th scope="col">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.run_id}>
                <th scope="row">
                  #{row.run_id}
                  {row.run_id === targetRunId && (
                    <span className="source-badge source-real interval-target-badge">
                      TARGET
                    </span>
                  )}
                </th>
                <td>
                  <span className={classificationClass(row.classification)}>
                    {row.classification.replace("_", " ")}
                  </span>
                </td>
                <td>{row.source_state ?? "Unavailable"}</td>
                <td>
                  <IntervalBounds
                    start={row.recorded_interval_start}
                    end={row.recorded_interval_end}
                  />
                </td>
                <td>
                  <IntervalBounds
                    start={row.interval_start}
                    end={row.interval_end}
                  />
                </td>
                <td>{evidenceReason(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function AcceptedIntervalsTable({
  rows,
  targetRunId,
  label,
}: {
  rows: WalletHistoryAcceptedIntervalRecord[];
  targetRunId: number;
  label: string;
}) {
  return (
    <div className="interval-table-section">
      <h4>Accepted interval timeline</h4>
      {rows.length === 0 ? (
        <p className="interval-empty-message">
          No validated intervals were accepted for this evidence layer.
        </p>
      ) : (
        <div className="table-wrap interval-table-wrap">
          <table className="data-table intelligence-table interval-table interval-timeline-table">
            <caption>
              {label}: server-accepted half-open intervals in timeline order.
            </caption>
            <thead>
              <tr>
                <th scope="col">Run</th>
                <th scope="col">Start · included</th>
                <th scope="col">End · excluded</th>
                <th scope="col">Duration</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.run_id}:${row.start}:${row.end}`}>
                  <th scope="row">
                    #{row.run_id}
                    {row.run_id === targetRunId ? " · target" : ""}
                  </th>
                  <td>
                    <Timestamp value={row.start} />
                  </td>
                  <td>
                    <Timestamp value={row.end} />
                  </td>
                  <td>{formatDuration(row.duration_microseconds)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function GapIntervals({
  rows,
  layerId,
  state,
}: {
  rows: WalletHistoryGapIntervalRecord[];
  layerId: string;
  state: WalletHistoryIntervalCoverageLayerRecord["state"];
}) {
  return (
    <section
      className={`interval-gap-section ${rows.length > 0 ? "interval-gap-section-warning" : ""}`}
      aria-labelledby={`${layerId}-gaps`}
    >
      <div className="interval-subhead">
        <h4 id={`${layerId}-gaps`}>Internal gaps</h4>
        <span className={rows.length > 0 ? "badge badge-mock" : "badge badge-real"}>
          {rows.length}
        </span>
      </div>
      {rows.length === 0 ? (
        <p className="interval-empty-message">
          {state === "no_validated_intervals"
            ? "No internal-gap conclusion is available without a validated interval."
            : "No internal gaps inside the eligible interval span."}
        </p>
      ) : (
        <div className="table-wrap interval-table-wrap">
          <table className="data-table intelligence-table interval-table">
            <caption>
              Server-computed gaps inside the validated selected span only.
            </caption>
            <thead>
              <tr>
                <th scope="col">Gap start</th>
                <th scope="col">Gap end</th>
                <th scope="col">Duration</th>
                <th scope="col">Left runs</th>
                <th scope="col">Right runs</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.start}:${row.end}`}>
                  <td>
                    <Timestamp value={row.start} />
                  </td>
                  <td>
                    <Timestamp value={row.end} />
                  </td>
                  <td>{formatDuration(row.duration_microseconds)}</td>
                  <td>{formatRunIds(row.left_run_ids)}</td>
                  <td>{formatRunIds(row.right_run_ids)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function PlainIntervalsTable({
  rows,
  caption,
}: {
  rows: WalletHistoryIntervalRecord[];
  caption: string;
}) {
  if (rows.length === 0) {
    return <p className="interval-empty-message">No union intervals returned.</p>;
  }
  return (
    <div className="table-wrap interval-table-wrap">
      <table className="data-table intelligence-table interval-table">
        <caption>{caption}</caption>
        <thead>
          <tr>
            <th scope="col">Start</th>
            <th scope="col">End</th>
            <th scope="col">Duration</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={`${row.start}:${row.end}`}>
              <td>
                <Timestamp value={row.start} />
              </td>
              <td>
                <Timestamp value={row.end} />
              </td>
              <td>{formatDuration(row.duration_microseconds)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function OverlapIntervals({
  rows,
  title,
}: {
  rows: WalletHistoryOverlapIntervalRecord[];
  title: string;
}) {
  return (
    <details className="interval-detail-block">
      <summary>
        <span>Overlap intervals</span>
        <span>{rows.length}</span>
      </summary>
      {rows.length === 0 ? (
        <p className="interval-empty-message">
          No overlap intervals were returned for this evidence layer.
        </p>
      ) : (
        <div className="table-wrap interval-table-wrap">
          <table className="data-table intelligence-table interval-table">
            <caption>{title}: server-computed overlap intervals.</caption>
            <thead>
              <tr>
                <th scope="col">Start</th>
                <th scope="col">End</th>
                <th scope="col">Duration</th>
                <th scope="col">Runs</th>
                <th scope="col">Depth</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={`${row.start}:${row.end}:${row.run_ids.join("-")}`}>
                  <td>
                    <Timestamp value={row.start} />
                  </td>
                  <td>
                    <Timestamp value={row.end} />
                  </td>
                  <td>{formatDuration(row.duration_microseconds)}</td>
                  <td>{formatRunIds(row.run_ids)}</td>
                  <td>{row.coverage_depth}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

function IntervalBounds({
  start,
  end,
}: {
  start?: string | null;
  end?: string | null;
}) {
  if (!start || !end) return <span className="muted">Unavailable</span>;
  return (
    <span className="interval-bounds">
      [<Timestamp value={start} />, <Timestamp value={end} />)
    </span>
  );
}

function Timestamp({ value }: { value: string }) {
  return <time dateTime={value}>{formatTimestamp(value)}</time>;
}

function layerState(layer: WalletHistoryIntervalCoverageLayerRecord): {
  label: string;
  className: string;
} {
  if (layer.selected_run_coverage_state === "none") {
    return { label: "NO ELIGIBLE INTERVALS", className: "source-mock" };
  }
  if (layer.selected_run_coverage_state === "partial") {
    return layer.state === "gapped_selected_span"
      ? { label: "PARTIAL · GAPS FOUND", className: "source-mock" }
      : { label: "PARTIAL · NO INTERNAL GAPS", className: "source-mock" };
  }
  return layer.state === "gapped_selected_span"
    ? {
        label: "ALL SELECTED RUNS ELIGIBLE · GAPS FOUND",
        className: "source-mock",
      }
    : {
        label: "ALL SELECTED RUNS ELIGIBLE · NO INTERNAL GAPS",
        className: "source-real",
      };
}

function classificationClass(
  classification: WalletHistoryIntervalRunEvidenceRecord["classification"],
): string {
  if (classification === "included") return "source-badge source-real";
  if (classification === "not_requested") return "source-badge source-unknown";
  return "source-badge source-mock";
}

function evidenceReason(row: WalletHistoryIntervalRunEvidenceRecord): string {
  const reasons = [row.reason, ...row.source_reason_codes].filter(
    (value): value is string => Boolean(value),
  );
  return reasons.length > 0 ? reasons.join(" · ") : "—";
}

function formatTimestamp(value: string): string {
  return value.replace("T", " ").replace("Z", " UTC");
}

function formatRunIds(runIds: number[]): string {
  return runIds.length > 0 ? runIds.map((runId) => `#${runId}`).join(", ") : "—";
}

function formatDuration(value: string): string {
  if (!/^(?:0|[1-9][0-9]*)$/.test(value)) return "—";
  const microseconds = BigInt(value);
  if (microseconds === 0n) return "0s";
  if (microseconds < 1_000n) return `${microseconds.toString()}µs`;
  if (microseconds < 1_000_000n) {
    return `${formatBigIntRatio(microseconds, 1_000n, 3)}ms`;
  }
  if (microseconds < 60_000_000n) {
    return `${formatBigIntRatio(microseconds, 1_000_000n, 3)}s`;
  }
  if (microseconds < 3_600_000_000n) {
    return `${formatBigIntRatio(microseconds, 60_000_000n, 2)}m`;
  }
  if (microseconds < 86_400_000_000n) {
    return `${formatBigIntRatio(microseconds, 3_600_000_000n, 2)}h`;
  }
  return `${formatBigIntRatio(microseconds, 86_400_000_000n, 2)}d`;
}

function formatBigIntRatio(
  value: bigint,
  divisor: bigint,
  maximumFractionDigits: number,
): string {
  const scale = 10n ** BigInt(maximumFractionDigits);
  let whole = value / divisor;
  const remainder = value % divisor;
  let fraction = (remainder * scale + divisor / 2n) / divisor;
  if (fraction >= scale) {
    whole += 1n;
    fraction = 0n;
  }
  const wholeText = new Intl.NumberFormat("en-US").format(whole);
  const fractionText = fraction
    .toString()
    .padStart(maximumFractionDigits, "0")
    .replace(/0+$/, "");
  return fractionText ? `${wholeText}.${fractionText}` : wholeText;
}

function formatNumber(value: number, maximumFractionDigits: number): string {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits }).format(value);
}
