// @vitest-environment jsdom

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID } from "./test/walletCaseFixtures";
import {
  streamCheckpointDetailFixture,
  streamCheckpointChainFixture,
  streamCheckpointHistoryFixture,
} from "./test/walletCaseStreamCheckpointFixtures";

const api = vi.hoisted(() => ({
  getWalletCaseStreamCheckpoint: vi.fn(),
  getWalletCaseStreamCheckpointChain: vi.fn(),
  getWalletCaseStreamCheckpointHistory: vi.fn(),
}));

vi.mock("./walletCaseApi", () => api);

import { useWalletCaseCheckpointHistory } from "./useWalletCaseCheckpointHistory";

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

function olderPage() {
  const page = streamCheckpointHistoryFixture({ hasMore: false });
  const hash = "ef".repeat(32);
  return {
    ...page,
    items: [{
      ...page.items[0],
      checkpoint: {
        ...page.items[0].checkpoint,
        public_id: `scp_${hash}`,
        checkpoint_hash_sha256: hash,
        created_at: "2026-08-28T11:00:03Z",
      },
    }],
    aggregate: { total_revisions: 2, returned_count: 1 },
  };
}

describe("useWalletCaseCheckpointHistory", () => {
  it("loads, appends, and inspects immutable checkpoint revisions", async () => {
    const first = streamCheckpointHistoryFixture();
    const older = olderPage();
    older.revision_cutoff_public_id = first.revision_cutoff_public_id;
    api.getWalletCaseStreamCheckpointHistory
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(older);
    api.getWalletCaseStreamCheckpoint.mockResolvedValue(
      streamCheckpointDetailFixture(),
    );
    api.getWalletCaseStreamCheckpointChain.mockResolvedValue(
      streamCheckpointChainFixture(),
    );
    const { result } = renderHook(() => useWalletCaseCheckpointHistory(CASE_ID));

    await act(() => result.current.load());
    expect(result.current.history?.items).toHaveLength(1);
    expect(result.current.history?.hasMore).toBe(true);

    await act(() => result.current.loadMore());
    expect(result.current.history?.items.map(
      (item) => item.checkpoint.public_id,
    )).toEqual([
      first.items[0].checkpoint.public_id,
      older.items[0].checkpoint.public_id,
    ]);
    expect(result.current.history?.hasMore).toBe(false);
    expect(api.getWalletCaseStreamCheckpointHistory.mock.calls[1][0]).toMatchObject({
      caseId: CASE_ID,
      limit: 10,
      cursor: first.page.next_cursor,
    });

    await act(() => result.current.inspect(first.items[0].checkpoint.public_id));
    expect(result.current.selected).toEqual(streamCheckpointDetailFixture());
    await act(() => result.current.loadChain(first.items[0].checkpoint.public_id));
    expect(result.current.chain).toEqual(streamCheckpointChainFixture());
  });

  it("keeps loaded evidence when a continuation changes its cutoff", async () => {
    const first = streamCheckpointHistoryFixture();
    const changed = olderPage();
    changed.revision_cutoff_public_id = `scp_${"12".repeat(32)}`;
    api.getWalletCaseStreamCheckpointHistory
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(changed);
    const { result } = renderHook(() => useWalletCaseCheckpointHistory(CASE_ID));

    await act(() => result.current.load());
    await act(() => result.current.loadMore());

    expect(result.current.history?.items).toEqual(first.items);
    expect(result.current.historyError).toMatch(/changed its frozen revision set/);
  });
});
