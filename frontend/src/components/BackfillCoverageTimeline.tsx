import { ChartLineUp, ShieldCheck } from "@phosphor-icons/react";

import type {
  WalletCaseBackfillCoveragePoint,
  WalletCaseBackfillCoverageTimeline as Timeline,
} from "../walletCaseBackfillCoverageTimeline";

const CHART_WIDTH = 640;
const CHART_HEIGHT = 176;
const HORIZONTAL_PADDING = 38;
const VERTICAL_PADDING = 24;

function formatTimestamp(value: string | null): string {
  if (value === null) return "—";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function xPosition(index: number, pointCount: number): number {
  const steps = Math.max(pointCount, 1);
  return HORIZONTAL_PADDING + (
    index * (CHART_WIDTH - HORIZONTAL_PADDING * 2) / steps
  );
}

function yPosition(value: number, minimum: number, maximum: number): number {
  const drawableHeight = CHART_HEIGHT - VERTICAL_PADDING * 2;
  if (maximum === minimum) return VERTICAL_PADDING + drawableHeight / 2;
  return VERTICAL_PADDING + (
    (maximum - value) * drawableHeight / (maximum - minimum)
  );
}

function chartPoints(points: WalletCaseBackfillCoveragePoint[]): {
  line: string;
  markers: Array<{ point: WalletCaseBackfillCoveragePoint; x: number; y: number }>;
  minimum: number;
  maximum: number;
} {
  if (points.length === 0) {
    return { line: "", markers: [], minimum: 0, maximum: 0 };
  }
  const values = [
    points[0].beforeContinuationPagesSucceeded,
    ...points.map((point) => point.afterContinuationPagesSucceeded),
  ];
  const minimum = Math.min(...values);
  const maximum = Math.max(...values);
  const coordinates = values.map((value, index) => (
    `${xPosition(index, points.length)},${yPosition(value, minimum, maximum)}`
  ));
  return {
    line: coordinates.join(" "),
    markers: points.map((point, index) => ({
      point,
      x: xPosition(index + 1, points.length),
      y: yPosition(point.afterContinuationPagesSucceeded, minimum, maximum),
    })),
    minimum,
    maximum,
  };
}

export default function BackfillCoverageTimeline({
  timeline,
}: {
  timeline: Timeline;
}) {
  const chart = chartPoints(timeline.points);
  const windowLabel = timeline.window.fullyLoaded
    ? "Complete frozen outcome set"
    : `Loaded window · ${timeline.window.loadedOutcomes} of ${timeline.window.totalOutcomes}`;

  return (
    <section
      className="case-backfill-timeline"
      aria-label="Backfill coverage timeline"
    >
      <header>
        <span>
          <ChartLineUp size={18} />
          <strong>Verified coverage movement</strong>
        </span>
        <small className={timeline.window.fullyLoaded ? "is-complete" : "is-bounded"}>
          <ShieldCheck size={13} /> {windowLabel}
        </small>
      </header>
      {timeline.points.length > 0 ? (
        <>
          <svg
            viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
            role="img"
            aria-label={
              `Continuation pages moved from ${timeline.points[0].beforeContinuationPagesSucceeded} ` +
              `to ${timeline.points[timeline.points.length - 1].afterContinuationPagesSucceeded} ` +
              `across ${timeline.points.length} verified outcomes`
            }
            preserveAspectRatio="none"
          >
            <title>Verified Backfill Outcome coverage movement</title>
            <desc>
              Chronological successful continuation-page totals derived from the
              loaded frozen Backfill Outcome history.
            </desc>
            <line
              className="case-backfill-timeline-grid"
              x1={HORIZONTAL_PADDING}
              x2={CHART_WIDTH - HORIZONTAL_PADDING}
              y1={VERTICAL_PADDING}
              y2={VERTICAL_PADDING}
            />
            <line
              className="case-backfill-timeline-grid"
              x1={HORIZONTAL_PADDING}
              x2={CHART_WIDTH - HORIZONTAL_PADDING}
              y1={CHART_HEIGHT - VERTICAL_PADDING}
              y2={CHART_HEIGHT - VERTICAL_PADDING}
            />
            <polyline
              className="case-backfill-timeline-line"
              points={chart.line}
              fill="none"
              stroke="currentColor"
              vectorEffect="non-scaling-stroke"
            />
            {chart.markers.map(({ point, x, y }) => (
              <circle
                key={point.outcomePublicId}
                className={`case-backfill-timeline-point is-${point.outcome}`}
                cx={x}
                cy={y}
                r={point.frontierChanged ? 6 : 4}
                fill="currentColor"
                vectorEffect="non-scaling-stroke"
              />
            ))}
            <text x={8} y={VERTICAL_PADDING + 4}>{chart.maximum}</text>
            <text x={8} y={CHART_HEIGHT - VERTICAL_PADDING + 4}>{chart.minimum}</text>
          </svg>
          <div className="case-backfill-timeline-range">
            <small>{formatTimestamp(timeline.window.oldestCompletedAt)}</small>
            <small>{formatTimestamp(timeline.window.newestCompletedAt)}</small>
          </div>
        </>
      ) : (
        <p>No verified Backfill Outcomes are available for a coverage series.</p>
      )}
      <dl>
        <div>
          <dt>Verified page gain</dt>
          <dd>+{timeline.summary.successfulPagesAdded}</dd>
        </div>
        <div>
          <dt>Frontier moves</dt>
          <dd>{timeline.summary.frontierChangeCount}</dd>
        </div>
        <div>
          <dt>Provider streams</dt>
          <dd>{timeline.summary.distinctStreamCount}</dd>
        </div>
        <div>
          <dt>No-progress steps</dt>
          <dd>{timeline.summary.noProgressCount}</dd>
        </div>
      </dl>
      {timeline.summary.unrepresentedPageDelta > 0 && (
        <small className="case-backfill-timeline-gap">
          {timeline.summary.unrepresentedPageDelta} successful continuation pages
          between loaded outcomes are not represented by this outcome series.
        </small>
      )}
    </section>
  );
}
