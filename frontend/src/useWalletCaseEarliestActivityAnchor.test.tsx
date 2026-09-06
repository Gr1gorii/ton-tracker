// @vitest-environment jsdom

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID } from "./test/walletCaseFixtures";
import { verifiedEarliestActivityAnchorFixture } from "./test/walletCaseStreamCheckpointFixtures";

const api = vi.hoisted(() => ({
  getWalletCaseEarliestActivityAnchor: vi.fn(),
}));

vi.mock("./walletCaseApi", () => api);

import { useWalletCaseEarliestActivityAnchor } from "./useWalletCaseEarliestActivityAnchor";

const OTHER_SCOPE = "550e8400-e29b-41d4-b716-446655440099";

beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

describe("useWalletCaseEarliestActivityAnchor", () => {
  it("loads a verified anchor with an abortable no-store request", async () => {
    const anchor = verifiedEarliestActivityAnchorFixture();
    api.getWalletCaseEarliestActivityAnchor.mockResolvedValue(anchor);
    const { result } = renderHook(() => useWalletCaseEarliestActivityAnchor(CASE_ID));

    await act(() => result.current.verify());

    expect(result.current.anchor).toEqual(anchor);
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBeNull();
    expect(api.getWalletCaseEarliestActivityAnchor).toHaveBeenCalledWith(
      CASE_ID,
      expect.any(AbortSignal),
    );
  });

  it("fails closed and exposes a safe verification error", async () => {
    api.getWalletCaseEarliestActivityAnchor.mockRejectedValue(
      new Error("Earliest activity anchor integrity check failed."),
    );
    const { result } = renderHook(() => useWalletCaseEarliestActivityAnchor(CASE_ID));

    await act(() => result.current.verify());

    expect(result.current.anchor).toBeNull();
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toMatch(/integrity check failed/);
  });

  it("aborts and clears the anchor when the evidence scope changes", async () => {
    let resolveRequest: (
      (value: ReturnType<typeof verifiedEarliestActivityAnchorFixture>) => void
    ) | null = null;
    api.getWalletCaseEarliestActivityAnchor.mockReturnValue(new Promise((resolve) => {
      resolveRequest = resolve;
    }));
    const { result, rerender } = renderHook(
      ({ scope }) => useWalletCaseEarliestActivityAnchor(CASE_ID, scope),
      { initialProps: { scope: CASE_ID } },
    );

    let pending: Promise<void>;
    act(() => {
      pending = result.current.verify();
    });
    expect(result.current.state).toBe("loading");
    rerender({ scope: OTHER_SCOPE });
    await act(async () => {
      resolveRequest?.(verifiedEarliestActivityAnchorFixture());
      await pending;
    });

    expect(result.current.anchor).toBeNull();
    expect(result.current.state).toBe("idle");
    expect(result.current.error).toBeNull();
  });
});
