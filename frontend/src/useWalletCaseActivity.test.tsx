// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useCallback, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_CASE_ACTIVITY_FILTERS, type CaseActivityUrlState } from "./caseActivityQuery";
import {
  ACTIVITY_ID,
  SECOND_ACTIVITY_ID,
  activityDetailFixture,
  activityItemFixture,
  activityResponseFixture,
} from "./test/walletCaseActivityFixtures";
import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";

const apiMocks = vi.hoisted(() => ({
  getWalletCaseActivity: vi.fn(),
  getWalletCaseActivityDetail: vi.fn(),
}));

vi.mock("./walletCaseApi", () => apiMocks);

import { useWalletCaseActivity } from "./useWalletCaseActivity";

const BASE_STATE: CaseActivityUrlState = {
  snapshot: SYNC_ID,
  selectedActivityId: null,
  filters: DEFAULT_CASE_ACTIVITY_FILTERS,
};
const onSnapshotPinned = vi.fn();

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => { resolve = resolvePromise; });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getWalletCaseActivity.mockResolvedValue(activityResponseFixture());
  apiMocks.getWalletCaseActivityDetail.mockResolvedValue(activityDetailFixture());
});
afterEach(() => cleanup());

describe("useWalletCaseActivity", () => {
  it("pins the first resolved snapshot into query state and keeps refreshes on that revision", async () => {
    apiMocks.getWalletCaseActivity.mockResolvedValue(activityResponseFixture());

    const { result } = renderHook(() => {
      const [urlState, setUrlState] = useState<CaseActivityUrlState>({ ...BASE_STATE, snapshot: null });
      const pin = useCallback((snapshot: string) => {
        setUrlState((current) => ({ ...current, snapshot }));
      }, []);
      return { urlState, controller: useWalletCaseActivity({ caseId: CASE_ID, urlState, onSnapshotPinned: pin }) };
    });

    await waitFor(() => expect(result.current.urlState.snapshot).toBe(SYNC_ID));
    await waitFor(() => expect(apiMocks.getWalletCaseActivity).toHaveBeenCalledTimes(2));
    expect(apiMocks.getWalletCaseActivity.mock.calls[0][1].snapshot).toBeNull();
    expect(apiMocks.getWalletCaseActivity.mock.calls[1][1].snapshot).toBe(SYNC_ID);

    act(() => result.current.controller.reload());
    await waitFor(() => expect(apiMocks.getWalletCaseActivity).toHaveBeenCalledTimes(3));
    expect(apiMocks.getWalletCaseActivity.mock.calls[2][1].snapshot).toBe(SYNC_ID);
  });

  it("keeps pagination single-flight and appends a non-overlapping pinned page", async () => {
    const first = activityItemFixture();
    const second = activityItemFixture({
      public_id: SECOND_ACTIVITY_ID,
      transaction: { linkage: "self", hash: "5".repeat(64), event_id: null },
    });
    apiMocks.getWalletCaseActivity
      .mockResolvedValueOnce(activityResponseFixture({
        aggregate: { ...activityResponseFixture().aggregate, total_items: 2, transactions: 2 },
        items: [first],
        page: { limit: 1, has_more: true, next_cursor: "opaque-next" },
      }))
      .mockResolvedValueOnce(activityResponseFixture({
        aggregate: { ...activityResponseFixture().aggregate, total_items: 2, transactions: 2 },
        items: [second],
        page: { limit: 1, has_more: false, next_cursor: null },
      }));
    const { result } = renderHook(() => useWalletCaseActivity({
      caseId: CASE_ID,
      urlState: BASE_STATE,
      onSnapshotPinned,
    }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await Promise.all([result.current.loadMore(), result.current.loadMore()]);
    });
    expect(apiMocks.getWalletCaseActivity).toHaveBeenCalledTimes(2);
    expect(apiMocks.getWalletCaseActivity.mock.calls[1][1]).toMatchObject({
      snapshot: SYNC_ID,
      cursor: "opaque-next",
    });
    expect(result.current.items.map((item) => item.public_id)).toEqual([ACTIVITY_ID, SECOND_ACTIVITY_ID]);
  });

  it("contains an overlapping page as a controlled error without throwing from React state", async () => {
    apiMocks.getWalletCaseActivity
      .mockResolvedValueOnce(activityResponseFixture({
        page: { limit: 1, has_more: true, next_cursor: "opaque-next" },
      }))
      .mockResolvedValueOnce(activityResponseFixture({
        page: { limit: 1, has_more: false, next_cursor: null },
      }));
    const { result } = renderHook(() => useWalletCaseActivity({
      caseId: CASE_ID,
      urlState: BASE_STATE,
      onSnapshotPinned,
    }));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => { await result.current.loadMore(); });
    expect(result.current.error).toMatch(/pages overlap/);
    expect(result.current.items).toHaveLength(1);
  });

  it("ignores a stale first page after filters change", async () => {
    const stale = deferred<ReturnType<typeof activityResponseFixture>>();
    const current = activityResponseFixture({
      filters: { ...DEFAULT_CASE_ACTIVITY_FILTERS, kinds: ["swap"] },
      aggregate: { ...activityResponseFixture().aggregate, total_items: 0, transactions: 0 },
      observed_period: null,
      items: [],
    });
    apiMocks.getWalletCaseActivity.mockReturnValueOnce(stale.promise).mockResolvedValueOnce(current);
    const { result, rerender } = renderHook(
      ({ state }) => useWalletCaseActivity({ caseId: CASE_ID, urlState: state, onSnapshotPinned }),
      { initialProps: { state: BASE_STATE } },
    );
    rerender({ state: { ...BASE_STATE, filters: current.filters } });
    await waitFor(() => expect(result.current.loading).toBe(false));
    act(() => stale.resolve(activityResponseFixture()));
    await act(async () => { await Promise.resolve(); });
    expect(result.current.items).toEqual([]);
    expect(result.current.response?.filters.kinds).toEqual(["swap"]);
  });

  it("never requests detail without both a selected public id and pinned snapshot", async () => {
    const noSnapshotState: CaseActivityUrlState = {
      ...BASE_STATE,
      snapshot: null,
      selectedActivityId: ACTIVITY_ID,
    };
    const { rerender } = renderHook(
      ({ state }) => useWalletCaseActivity({ caseId: CASE_ID, urlState: state, onSnapshotPinned }),
      { initialProps: { state: noSnapshotState } },
    );
    await waitFor(() => expect(apiMocks.getWalletCaseActivity).toHaveBeenCalled());
    expect(apiMocks.getWalletCaseActivityDetail).not.toHaveBeenCalled();

    rerender({ state: { ...BASE_STATE, selectedActivityId: ACTIVITY_ID } });
    await waitFor(() => expect(apiMocks.getWalletCaseActivityDetail).toHaveBeenCalledWith(
      CASE_ID,
      SYNC_ID,
      ACTIVITY_ID,
      expect.any(AbortSignal),
    ));
  });
});
