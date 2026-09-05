import type { WalletCaseLimitation } from "./walletCase";
import type {
  WalletCaseBackfillOutcomeHistoryItem,
  WalletCaseBackfillOutcomeState,
} from "./walletCaseStreamCheckpoint";

const PUBLIC_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const OUTCOME_ID = /^bfo_[0-9a-f]{64}$/;
const OUTCOME_STATES = new Set<WalletCaseBackfillOutcomeState>([
  "advanced",
  "completed",
  "blocked",
  "no_progress",
]);

export interface WalletCaseBackfillCoverageSource {
  casePublicId: string;
  syncCutoffPublicId: string | null;
  totalOutcomes: number;
  items: WalletCaseBackfillOutcomeHistoryItem[];
  hasMore: boolean;
  limitations: WalletCaseLimitation[];
}

export interface WalletCaseBackfillCoveragePoint {
  sequence: number;
  outcomePublicId: string;
  syncPublicId: string;
  completedAt: string;
  provider: string;
  streamKey: string;
  outcome: WalletCaseBackfillOutcomeState;
  beforeContinuationPagesSucceeded: number;
  afterContinuationPagesSucceeded: number;
  pagesSucceededDelta: number;
  frontierChanged: boolean;
  unrepresentedPageDelta: number;
}

export interface WalletCaseBackfillCoverageTimeline {
  contractVersion: "wallet_case_backfill_coverage_timeline_v1";
  sourceContractVersion: "wallet_case_backfill_outcome_history_v1";
  casePublicId: string;
  syncCutoffPublicId: string | null;
  window: {
    totalOutcomes: number;
    loadedOutcomes: number;
    hasOlderOutcomes: boolean;
    fullyLoaded: boolean;
    oldestCompletedAt: string | null;
    newestCompletedAt: string | null;
  };
  summary: {
    successfulPagesAdded: number;
    frontierChangeCount: number;
    advancedCount: number;
    completedCount: number;
    blockedCount: number;
    noProgressCount: number;
    distinctStreamCount: number;
    unrepresentedPageDelta: number;
  };
  points: WalletCaseBackfillCoveragePoint[];
  limitations: WalletCaseLimitation[];
}

function finiteInteger(value: number, label: string): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error(`${label} is invalid.`);
  }
  return value;
}

function timestamp(value: string, label: string): number {
  const parsed = Date.parse(value);
  if (!value || !Number.isFinite(parsed)) throw new Error(`${label} is invalid.`);
  return parsed;
}

function validateSource(source: WalletCaseBackfillCoverageSource): void {
  if (!PUBLIC_ID.test(source.casePublicId)) {
    throw new Error("Backfill coverage timeline case id is invalid.");
  }
  if (
    source.syncCutoffPublicId !== null &&
    !PUBLIC_ID.test(source.syncCutoffPublicId)
  ) {
    throw new Error("Backfill coverage timeline cutoff id is invalid.");
  }
  const total = finiteInteger(
    source.totalOutcomes,
    "Backfill coverage timeline total outcomes",
  );
  if (
    !Array.isArray(source.items) ||
    source.items.length > total ||
    (source.syncCutoffPublicId === null) !== (total === 0) ||
    source.hasMore !== (source.items.length < total)
  ) {
    throw new Error("Backfill coverage timeline window is inconsistent.");
  }
}

function limitationSet(
  limitations: WalletCaseLimitation[],
  fullyLoaded: boolean,
): WalletCaseLimitation[] {
  const derived: WalletCaseLimitation[] = [{
    code: "backfill_coverage_timeline_is_derived",
    message:
      "The timeline is derived from verified Backfill Outcome descriptors; reopen an outcome to verify its complete evidence document.",
  }];
  if (!fullyLoaded) {
    derived.push({
      code: "backfill_coverage_timeline_is_loaded_window",
      message:
        "The timeline covers only the loaded frozen outcome window; older outcomes remain outside this view.",
    });
  }
  return [...new Map(
    [...derived, ...limitations].map((item) => [item.code, item]),
  ).values()];
}

export function buildWalletCaseBackfillCoverageTimeline(
  source: WalletCaseBackfillCoverageSource,
): WalletCaseBackfillCoverageTimeline {
  validateSource(source);
  const seenOutcomeIds = new Set<string>();
  const seenSyncIds = new Set<string>();
  let previousNewestTimestamp: number | null = null;
  for (const [index, item] of source.items.entries()) {
    const descriptor = item.outcome;
    const completedAt = timestamp(
      item.completed_at,
      `Backfill coverage timeline outcome ${index} completion time`,
    );
    if (
      !OUTCOME_ID.test(descriptor.public_id) ||
      !PUBLIC_ID.test(descriptor.sync_public_id) ||
      !OUTCOME_STATES.has(descriptor.outcome) ||
      seenOutcomeIds.has(descriptor.public_id) ||
      seenSyncIds.has(descriptor.sync_public_id) ||
      (previousNewestTimestamp !== null && completedAt > previousNewestTimestamp)
    ) {
      throw new Error(`Backfill coverage timeline outcome ${index} is invalid.`);
    }
    const before = finiteInteger(
      item.before_continuation_pages_succeeded,
      `Backfill coverage timeline outcome ${index} before pages`,
    );
    const after = finiteInteger(
      item.after_continuation_pages_succeeded,
      `Backfill coverage timeline outcome ${index} after pages`,
    );
    const delta = finiteInteger(
      descriptor.pages_succeeded_delta,
      `Backfill coverage timeline outcome ${index} page delta`,
    );
    if (after - before !== delta) {
      throw new Error(`Backfill coverage timeline outcome ${index} delta is inconsistent.`);
    }
    seenOutcomeIds.add(descriptor.public_id);
    seenSyncIds.add(descriptor.sync_public_id);
    previousNewestTimestamp = completedAt;
  }

  const chronological = [...source.items].reverse();
  let previousAfter: number | null = null;
  const points = chronological.map((item, index): WalletCaseBackfillCoveragePoint => {
    const before = item.before_continuation_pages_succeeded;
    if (previousAfter !== null && before < previousAfter) {
      throw new Error(`Backfill coverage timeline point ${index} regresses.`);
    }
    const unrepresentedPageDelta = previousAfter === null
      ? 0
      : before - previousAfter;
    previousAfter = item.after_continuation_pages_succeeded;
    return {
      sequence: index + 1,
      outcomePublicId: item.outcome.public_id,
      syncPublicId: item.outcome.sync_public_id,
      completedAt: item.completed_at,
      provider: item.outcome.provider,
      streamKey: item.outcome.stream_key,
      outcome: item.outcome.outcome,
      beforeContinuationPagesSucceeded:
        item.before_continuation_pages_succeeded,
      afterContinuationPagesSucceeded:
        item.after_continuation_pages_succeeded,
      pagesSucceededDelta: item.outcome.pages_succeeded_delta,
      frontierChanged: item.frontier_changed,
      unrepresentedPageDelta,
    };
  });
  const stateCount = (state: WalletCaseBackfillOutcomeState) =>
    points.filter((point) => point.outcome === state).length;
  const fullyLoaded = !source.hasMore;
  return {
    contractVersion: "wallet_case_backfill_coverage_timeline_v1",
    sourceContractVersion: "wallet_case_backfill_outcome_history_v1",
    casePublicId: source.casePublicId,
    syncCutoffPublicId: source.syncCutoffPublicId,
    window: {
      totalOutcomes: source.totalOutcomes,
      loadedOutcomes: points.length,
      hasOlderOutcomes: source.hasMore,
      fullyLoaded,
      oldestCompletedAt: points[0]?.completedAt ?? null,
      newestCompletedAt: points.length > 0
        ? points[points.length - 1].completedAt
        : null,
    },
    summary: {
      successfulPagesAdded: points.reduce(
        (total, point) => total + point.pagesSucceededDelta,
        0,
      ),
      frontierChangeCount: points.filter((point) => point.frontierChanged).length,
      advancedCount: stateCount("advanced"),
      completedCount: stateCount("completed"),
      blockedCount: stateCount("blocked"),
      noProgressCount: stateCount("no_progress"),
      distinctStreamCount: new Set(
        points.map((point) => `${point.provider}\u0000${point.streamKey}`),
      ).size,
      unrepresentedPageDelta: points.reduce(
        (total, point) => total + point.unrepresentedPageDelta,
        0,
      ),
    },
    points,
    limitations: limitationSet(source.limitations, fullyLoaded),
  };
}

export function serializeWalletCaseBackfillCoverageTimeline(
  source: WalletCaseBackfillCoverageSource,
): string {
  return `${JSON.stringify(buildWalletCaseBackfillCoverageTimeline(source), null, 2)}\n`;
}

function csvCell(value: string | number | boolean): string {
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

export function serializeWalletCaseBackfillCoverageTimelineCsv(
  source: WalletCaseBackfillCoverageSource,
): string {
  const timeline = buildWalletCaseBackfillCoverageTimeline(source);
  const header = [
    "sequence",
    "completed_at",
    "provider",
    "stream_key",
    "outcome",
    "before_continuation_pages_succeeded",
    "after_continuation_pages_succeeded",
    "pages_succeeded_delta",
    "frontier_changed",
    "unrepresented_page_delta",
    "outcome_public_id",
    "sync_public_id",
    "sync_cutoff_public_id",
  ];
  const rows = timeline.points.map((point) => [
    point.sequence,
    point.completedAt,
    point.provider,
    point.streamKey,
    point.outcome,
    point.beforeContinuationPagesSucceeded,
    point.afterContinuationPagesSucceeded,
    point.pagesSucceededDelta,
    point.frontierChanged,
    point.unrepresentedPageDelta,
    point.outcomePublicId,
    point.syncPublicId,
    timeline.syncCutoffPublicId ?? "",
  ].map(csvCell).join(","));
  return `${[header.join(","), ...rows].join("\n")}\n`;
}
