// @vitest-environment jsdom

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID } from "./test/walletCaseFixtures";
import { observedHistoryFloorFixture } from "./test/walletCaseStreamCheckpointFixtures";

const api = vi.hoisted(() => ({
  getWalletCaseObservedHistoryFloor: vi.fn(),
}));

vi.mock("./walletCaseApi", () => api);

import { useWalletCaseObservedHistoryFloor } from "./useWalletCaseObservedHistoryFloor";

const OTHER_CASE_ID = "550e8400-e29b-41d4-a716-446655440099";

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("useWalletCaseObservedHistoryFloor", () => {
  it("loads a verified observed floor with an abortable request", async () => {
    const floor = observedHistoryFloorFixture();
    api.getWalletCaseObservedHistoryFloor.mockResolvedValue(floor);
    const { result } = renderHook(() => useWalletCaseObservedHistoryFloor(CASE_ID));

    await act(() => result.current.verify());

    expect(result.current.floor).toEqual(floor);
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBeNull();
    expect(api.getWalletCaseObservedHistoryFloor).toHaveBeenCalledWith(
      CASE_ID,
      expect.any(AbortSignal),
    );
  });

  it("fails closed and exposes a safe verification error", async () => {
    api.getWalletCaseObservedHistoryFloor.mockRejectedValue(
      new Error("Observed history floor integrity check failed."),
    );
    const { result } = renderHook(() => useWalletCaseObservedHistoryFloor(CASE_ID));

    await act(() => result.current.verify());

    expect(result.current.floor).toBeNull();
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toMatch(/integrity check failed/);
  });

  it("aborts and clears evidence when the snapshot scope changes", async () => {
    let resolveRequest: ((value: ReturnType<typeof observedHistoryFloorFixture>) => void) | null = null;
    api.getWalletCaseObservedHistoryFloor.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    const { result, rerender } = renderHook(
      ({ scope }) => useWalletCaseObservedHistoryFloor(CASE_ID, scope),
      { initialProps: { scope: CASE_ID } },
    );

    let pending: Promise<void>;
    act(() => {
      pending = result.current.verify();
    });
    expect(result.current.state).toBe("loading");
    rerender({ scope: OTHER_CASE_ID });
    await act(async () => {
      resolveRequest?.(observedHistoryFloorFixture());
      await pending;
    });

    expect(result.current.floor).toBeNull();
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBeNull();
  });
});
