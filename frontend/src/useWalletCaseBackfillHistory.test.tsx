// @vitest-environment jsdom

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID, OLDER_SYNC_ID } from "./test/walletCaseFixtures";
import {
  backfillOutcomeFixture,
  backfillOutcomeHistoryFixture,
} from "./test/walletCaseStreamCheckpointFixtures";

const api = vi.hoisted(() => ({
  getWalletCaseBackfillOutcome: vi.fn(),
  getWalletCaseBackfillOutcomeHistory: vi.fn(),
}));

vi.mock("./walletCaseApi", () => api);

import { useWalletCaseBackfillHistory } from "./useWalletCaseBackfillHistory";

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

function olderPage() {
  const page = backfillOutcomeHistoryFixture({ totalOutcomes: 2 });
  const hash = "7a".repeat(32);
  return {
    ...page,
    items: [{
      ...page.items[0],
      outcome: {
        ...page.items[0].outcome,
        public_id: `bfo_${hash}`,
        content_hash_sha256: hash,
        sync_public_id: OLDER_SYNC_ID,
        input_progress_public_id: `bfp_${"7b".repeat(32)}`,
        output_progress_public_id: `bfp_${"7c".repeat(32)}`,
      },
      completed_at: "2026-08-28T12:00:04Z",
      before_continuation_pages_succeeded: 0,
      after_continuation_pages_succeeded: 1,
    }],
  };
}

describe("useWalletCaseBackfillHistory", () => {
  it("loads, appends, and verifies immutable Backfill Outcomes", async () => {
    const first = backfillOutcomeHistoryFixture({
      hasMore: true,
      totalOutcomes: 2,
    });
    const older = olderPage();
    older.sync_cutoff_public_id = first.sync_cutoff_public_id;
    api.getWalletCaseBackfillOutcomeHistory
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(older);
    api.getWalletCaseBackfillOutcome.mockResolvedValue(backfillOutcomeFixture());
    const { result } = renderHook(() => useWalletCaseBackfillHistory(CASE_ID));

    await act(() => result.current.load());
    expect(result.current.history?.items).toHaveLength(1);
    expect(result.current.history?.hasMore).toBe(true);
    expect(result.current.timeline?.window).toMatchObject({
      loadedOutcomes: 1,
      totalOutcomes: 2,
      fullyLoaded: false,
    });

    await act(() => result.current.loadMore());
    expect(result.current.history?.items.map(
      (item) => item.outcome.sync_public_id,
    )).toEqual([
      first.items[0].outcome.sync_public_id,
      older.items[0].outcome.sync_public_id,
    ]);
    expect(result.current.history?.hasMore).toBe(false);
    expect(result.current.timeline?.points.map((point) => point.syncPublicId)).toEqual([
      older.items[0].outcome.sync_public_id,
      first.items[0].outcome.sync_public_id,
    ]);
    expect(result.current.timeline?.window.fullyLoaded).toBe(true);
    expect(api.getWalletCaseBackfillOutcomeHistory.mock.calls[1][0]).toMatchObject({
      caseId: CASE_ID,
      limit: 10,
      cursor: first.page.next_cursor,
    });

    await act(() => result.current.inspect(first.items[0].outcome.sync_public_id));
    expect(result.current.selected).toEqual(backfillOutcomeFixture());
    expect(api.getWalletCaseBackfillOutcome).toHaveBeenCalledWith(
      CASE_ID,
      first.items[0].outcome.sync_public_id,
      expect.any(AbortSignal),
    );
  });

  it("keeps loaded outcomes when continuation changes its frozen cutoff", async () => {
    const first = backfillOutcomeHistoryFixture({
      hasMore: true,
      totalOutcomes: 2,
    });
    const changed = olderPage();
    changed.sync_cutoff_public_id = OLDER_SYNC_ID;
    api.getWalletCaseBackfillOutcomeHistory
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(changed);
    const { result } = renderHook(() => useWalletCaseBackfillHistory(CASE_ID));

    await act(() => result.current.load());
    await act(() => result.current.loadMore());

    expect(result.current.history?.items).toEqual(first.items);
    expect(result.current.historyError).toMatch(/changed its frozen result set/);
  });

  it("keeps loaded outcomes when a continuation changes case scope", async () => {
    const first = backfillOutcomeHistoryFixture({
      hasMore: true,
      totalOutcomes: 2,
    });
    const changed = olderPage();
    changed.sync_cutoff_public_id = first.sync_cutoff_public_id;
    changed.case_public_id = OLDER_SYNC_ID;
    api.getWalletCaseBackfillOutcomeHistory
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(changed);
    const { result } = renderHook(() => useWalletCaseBackfillHistory(CASE_ID));

    await act(() => result.current.load());
    await act(() => result.current.loadMore());

    expect(result.current.history?.items).toEqual(first.items);
    expect(result.current.timeline?.window.loadedOutcomes).toBe(1);
    expect(result.current.historyError).toMatch(/changed its frozen result set/);
  });

  it("rejects a repeated outcome without discarding the verified page", async () => {
    const first = backfillOutcomeHistoryFixture({
      hasMore: true,
      totalOutcomes: 2,
    });
    const repeated = {
      ...backfillOutcomeHistoryFixture({ totalOutcomes: 2 }),
      sync_cutoff_public_id: first.sync_cutoff_public_id,
    };
    api.getWalletCaseBackfillOutcomeHistory
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(repeated);
    const { result } = renderHook(() => useWalletCaseBackfillHistory(CASE_ID));

    await act(() => result.current.load());
    await act(() => result.current.loadMore());

    expect(result.current.history?.items).toEqual(first.items);
    expect(result.current.historyError).toMatch(/repeated a result/);
  });
});
