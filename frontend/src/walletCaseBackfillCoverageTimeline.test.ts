import { describe, expect, it } from "vitest";

import { OLDER_SYNC_ID } from "./test/walletCaseFixtures";
import {
  backfillOutcomeHistoryFixture,
} from "./test/walletCaseStreamCheckpointFixtures";
import {
  buildWalletCaseBackfillCoverageTimeline,
  serializeWalletCaseBackfillCoverageTimeline,
  serializeWalletCaseBackfillCoverageTimelineCsv,
  type WalletCaseBackfillCoverageSource,
} from "./walletCaseBackfillCoverageTimeline";

function source(): WalletCaseBackfillCoverageSource {
  const latestPage = backfillOutcomeHistoryFixture({ totalOutcomes: 2 });
  const latest = latestPage.items[0];
  const olderHash = "7a".repeat(32);
  return {
    casePublicId: latestPage.case_public_id,
    syncCutoffPublicId: latestPage.sync_cutoff_public_id,
    totalOutcomes: 2,
    hasMore: false,
    items: [
      latest,
      {
        ...latest,
        outcome: {
          ...latest.outcome,
          public_id: `bfo_${olderHash}`,
          content_hash_sha256: olderHash,
          sync_public_id: OLDER_SYNC_ID,
          outcome: "completed",
          input_progress_public_id: `bfp_${"7b".repeat(32)}`,
          output_progress_public_id: `bfp_${"7c".repeat(32)}`,
          after_resume_state: "complete",
        },
        completed_at: "2026-08-28T12:00:04Z",
        before_continuation_pages_succeeded: 0,
        after_continuation_pages_succeeded: 1,
      },
    ],
    limitations: latestPage.limitations,
  };
}

describe("Wallet Case Backfill Coverage Timeline", () => {
  it("turns newest-first verified outcomes into a chronological coverage series", () => {
    const timeline = buildWalletCaseBackfillCoverageTimeline(source());

    expect(timeline.contractVersion).toBe(
      "wallet_case_backfill_coverage_timeline_v1",
    );
    expect(timeline.points.map((point) => point.outcome)).toEqual([
      "completed",
      "advanced",
    ]);
    expect(timeline.points.map((point) => point.sequence)).toEqual([1, 2]);
    expect(timeline.window).toMatchObject({
      totalOutcomes: 2,
      loadedOutcomes: 2,
      fullyLoaded: true,
      hasOlderOutcomes: false,
    });
    expect(timeline.summary).toEqual({
      successfulPagesAdded: 2,
      frontierChangeCount: 2,
      advancedCount: 1,
      completedCount: 1,
      blockedCount: 0,
      noProgressCount: 0,
      distinctStreamCount: 1,
      unrepresentedPageDelta: 0,
    });
  });

  it("labels a partial frozen window and preserves source limitations", () => {
    const value = source();
    value.items = value.items.slice(0, 1);
    value.hasMore = true;

    const timeline = buildWalletCaseBackfillCoverageTimeline(value);

    expect(timeline.window.fullyLoaded).toBe(false);
    expect(timeline.limitations.map((item) => item.code)).toEqual([
      "backfill_coverage_timeline_is_derived",
      "backfill_coverage_timeline_is_loaded_window",
      "backfill_outcome_history_is_finite_transitions",
    ]);
  });

  it("rejects ordering, identity, window, delta, and cross-outcome regressions", () => {
    const reversed = source();
    reversed.items.reverse();
    expect(() => buildWalletCaseBackfillCoverageTimeline(reversed)).toThrow(
      /outcome 1 is invalid/,
    );

    const duplicate = source();
    duplicate.items[1] = {
      ...duplicate.items[1],
      outcome: {
        ...duplicate.items[1].outcome,
        public_id: duplicate.items[0].outcome.public_id,
      },
    };
    expect(() => buildWalletCaseBackfillCoverageTimeline(duplicate)).toThrow(
      /outcome 1 is invalid/,
    );

    const incomplete = source();
    incomplete.items.pop();
    expect(() => buildWalletCaseBackfillCoverageTimeline(incomplete)).toThrow(
      /window is inconsistent/,
    );

    const badDelta = source();
    badDelta.items[0] = {
      ...badDelta.items[0],
      after_continuation_pages_succeeded: 3,
    };
    expect(() => buildWalletCaseBackfillCoverageTimeline(badDelta)).toThrow(
      /delta is inconsistent/,
    );

    const regression = source();
    regression.items[0] = {
      ...regression.items[0],
      before_continuation_pages_succeeded: 0,
      after_continuation_pages_succeeded: 1,
    };
    expect(() => buildWalletCaseBackfillCoverageTimeline(regression)).toThrow(
      /point 1 regresses/,
    );
  });

  it("serializes stable JSON and analysis-ready CSV", () => {
    const value = source();
    value.items[0] = {
      ...value.items[0],
      outcome: { ...value.items[0].outcome, provider: 'provider,"quoted"' },
    };
    const json = JSON.parse(serializeWalletCaseBackfillCoverageTimeline(value));
    const csv = serializeWalletCaseBackfillCoverageTimelineCsv(value);

    expect(json.points).toHaveLength(2);
    expect(csv.split("\n")).toHaveLength(4);
    expect(csv).toContain('"provider,""quoted"""');
    expect(csv).toContain(value.syncCutoffPublicId);
  });
});
