// @vitest-environment jsdom

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID } from "./test/walletCaseFixtures";
import { completeHistoryGateFixture } from "./test/walletCaseStreamCheckpointFixtures";

const api = vi.hoisted(() => ({
  getWalletCaseCompleteHistoryGate: vi.fn(),
}));

vi.mock("./walletCaseApi", () => api);

import { useWalletCaseCompleteHistoryGate } from "./useWalletCaseCompleteHistoryGate";

const OTHER_CASE_ID = "550e8400-e29b-41d4-a716-446655440099";

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("useWalletCaseCompleteHistoryGate", () => {
  it("loads a verified gate with an abortable request", async () => {
    const gate = completeHistoryGateFixture();
    api.getWalletCaseCompleteHistoryGate.mockResolvedValue(gate);
    const { result } = renderHook(() => useWalletCaseCompleteHistoryGate(CASE_ID));

    await act(() => result.current.verify());

    expect(result.current.gate).toEqual(gate);
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBeNull();
    expect(api.getWalletCaseCompleteHistoryGate).toHaveBeenCalledWith(
      CASE_ID,
      expect.any(AbortSignal),
    );
  });

  it("fails closed and surfaces a safe verification error", async () => {
    api.getWalletCaseCompleteHistoryGate.mockRejectedValue(
      new Error("Complete-history gate integrity check failed."),
    );
    const { result } = renderHook(() => useWalletCaseCompleteHistoryGate(CASE_ID));

    await act(() => result.current.verify());

    expect(result.current.gate).toBeNull();
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toMatch(/integrity check failed/);
  });

  it("aborts and clears an obsolete Case request", async () => {
    let resolveRequest: ((value: ReturnType<typeof completeHistoryGateFixture>) => void) | null = null;
    api.getWalletCaseCompleteHistoryGate.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    const { result, rerender } = renderHook(
      ({ caseId }) => useWalletCaseCompleteHistoryGate(caseId),
      { initialProps: { caseId: CASE_ID } },
    );

    let pending: Promise<void>;
    act(() => {
      pending = result.current.verify();
    });
    expect(result.current.state).toBe("loading");
    rerender({ caseId: OTHER_CASE_ID });
    await act(async () => {
      resolveRequest?.(completeHistoryGateFixture());
      await pending;
    });

    expect(result.current.gate).toBeNull();
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBeNull();
  });
});
