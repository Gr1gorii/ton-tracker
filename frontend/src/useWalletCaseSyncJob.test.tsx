// @vitest-environment jsdom

import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WalletCaseSync, WalletCaseSyncRequest } from "./walletCase";
import {
  activeSyncFixture,
  CASE_ID,
  IDEMPOTENCY_KEY,
  incrementalSyncFixture,
  succeededSyncFixture,
} from "./test/walletCaseFixtures";

const apiMocks = vi.hoisted(() => ({
  cancelWalletCaseSync: vi.fn(),
  createWalletCaseSync: vi.fn(),
  getWalletCaseSync: vi.fn(),
}));

vi.mock("./walletCaseApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./walletCaseApi")>();
  return { ...actual, ...apiMocks };
});

import { WalletCaseApiError } from "./walletCaseApi";
import { useWalletCaseSyncJob } from "./useWalletCaseSyncJob";

const REQUEST: WalletCaseSyncRequest = {
  mode: "bounded",
  time_window: "24h",
  surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"],
};

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => IDEMPOTENCY_KEY) });
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  Object.defineProperty(navigator, "onLine", {
    configurable: true,
    value: true,
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("useWalletCaseSyncJob", () => {
  it("resumes an active job, honors server polling, never overlaps, and stops once terminal", async () => {
    const first = deferred<ReturnType<typeof activeSyncFixture>>();
    const onTerminal = vi.fn();
    apiMocks.getWalletCaseSync
      .mockReturnValueOnce(first.promise)
      .mockResolvedValueOnce(succeededSyncFixture({ status_version: 3 }));
    const initial = activeSyncFixture("queued", { poll_after_ms: 500 });
    const { result } = renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: initial,
      onTerminal,
    }));

    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(1);

    await act(async () => {
      first.resolve(activeSyncFixture("running", { status_version: 2, poll_after_ms: 1_000 }));
      await Promise.resolve();
    });
    expect(result.current.sync?.status_version).toBe(2);
    await act(async () => { await vi.advanceTimersByTimeAsync(999); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(2);
    expect(result.current.sync?.state).toBe("succeeded");
    expect(onTerminal).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(2);
  });

  it("ignores stale poll results after a newer cancellation response", async () => {
    const pendingPoll = deferred<ReturnType<typeof activeSyncFixture>>();
    const initial = activeSyncFixture("running", { status_version: 2, poll_after_ms: 500 });
    const cancellationAccepted = activeSyncFixture("running", {
      status_version: 4,
      cancel_requested: true,
      message: "Cancellation requested.",
    });
    apiMocks.getWalletCaseSync.mockReturnValue(pendingPoll.promise);
    apiMocks.cancelWalletCaseSync.mockResolvedValue(cancellationAccepted);
    const { result } = renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: initial,
      onTerminal: vi.fn(),
    }));

    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    await act(async () => { await result.current.cancel(); });
    expect(result.current.sync?.status_version).toBe(4);
    await act(async () => {
      pendingPoll.resolve(activeSyncFixture("running", { status_version: 3 }));
      await Promise.resolve();
    });
    expect(result.current.sync?.status_version).toBe(4);
    expect(result.current.sync?.cancel_requested).toBe(true);
  });

  it("reuses one idempotency key when the POST outcome is ambiguous", async () => {
    apiMocks.createWalletCaseSync
      .mockRejectedValueOnce(new TypeError("Network connection reset"))
      .mockResolvedValueOnce(activeSyncFixture("queued"));
    const { result } = renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: null,
      onTerminal: vi.fn(),
    }));

    await act(async () => { await result.current.start(REQUEST); });
    expect(result.current.transportError).toContain("Network connection reset");
    await act(async () => { await result.current.start(REQUEST); });

    expect(apiMocks.createWalletCaseSync).toHaveBeenCalledTimes(2);
    expect(apiMocks.createWalletCaseSync.mock.calls[0][2]).toBe(IDEMPOTENCY_KEY);
    expect(apiMocks.createWalletCaseSync.mock.calls[1][2]).toBe(IDEMPOTENCY_KEY);
    expect(result.current.sync?.state).toBe("queued");
  });

  it("retries an incremental failure as a fresh forward refresh", async () => {
    const failedRefresh = incrementalSyncFixture({
      state: "failed",
      stage: "failed",
      status_version: 5,
      result: null,
      error: {
        code: "provider_unavailable",
        message_safe: "Provider unavailable.",
        retryable: true,
      },
      completed_at: "2026-08-09T12:02:00Z",
    });
    apiMocks.createWalletCaseSync.mockResolvedValue(activeSyncFixture("queued"));
    const { result } = renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: failedRefresh,
      onTerminal: vi.fn(),
    }));

    await act(async () => { await result.current.retry(); });

    expect(apiMocks.createWalletCaseSync).toHaveBeenCalledWith(
      CASE_ID,
      {
        mode: "incremental",
        time_window: "24h",
        surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"],
      },
      IDEMPOTENCY_KEY,
      expect.any(AbortSignal),
    );
  });

  it("uses Retry-After for reconnect backoff without converting transport loss into job failure", async () => {
    apiMocks.getWalletCaseSync
      .mockRejectedValueOnce(new WalletCaseApiError({
        message: "Provider gateway unavailable",
        status: 503,
        retryable: true,
        retryAfterMs: 3_000,
      }))
      .mockResolvedValueOnce(activeSyncFixture("running", { status_version: 2 }));
    const { result } = renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: activeSyncFixture("queued", { poll_after_ms: 500 }),
      onTerminal: vi.fn(),
    }));

    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    expect(result.current.transportState).toBe("reconnecting");
    expect(result.current.sync?.state).toBe("queued");
    await act(async () => { await vi.advanceTimersByTimeAsync(2_999); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(1); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(2);
    expect(result.current.sync?.state).toBe("running");
  });

  it("honors a same-version polling hint and lets Check now bypass the wait", async () => {
    apiMocks.getWalletCaseSync
      .mockResolvedValueOnce(activeSyncFixture("queued", {
        status_version: 1,
        poll_after_ms: 1_500,
      }))
      .mockResolvedValueOnce(activeSyncFixture("running", { status_version: 2 }));
    const { result } = renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: activeSyncFixture("queued", { status_version: 1, poll_after_ms: 500 }),
      onTerminal: vi.fn(),
    }));

    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    await act(async () => { await vi.advanceTimersByTimeAsync(1_499); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(1);
    act(() => result.current.checkNow());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(2);
  });

  it("aborts but never overlaps an in-flight poll when Check now is requested", async () => {
    const pending = deferred<ReturnType<typeof activeSyncFixture>>();
    apiMocks.getWalletCaseSync
      .mockReturnValueOnce(pending.promise)
      .mockResolvedValueOnce(activeSyncFixture("running", { status_version: 3 }));
    const { result } = renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: activeSyncFixture("running", { status_version: 2, poll_after_ms: 500 }),
      onTerminal: vi.fn(),
    }));

    await act(async () => { await vi.advanceTimersByTimeAsync(500); });
    act(() => result.current.checkNow());
    await act(async () => { await vi.advanceTimersByTimeAsync(0); });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(1);

    await act(async () => {
      pending.resolve(activeSyncFixture("running", { status_version: 2 }));
      await Promise.resolve();
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(2);
  });

  it("slows background polling and checks immediately when visibility returns", async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });
    apiMocks.getWalletCaseSync.mockResolvedValue(activeSyncFixture("running", { status_version: 2 }));
    renderHook(() => useWalletCaseSyncJob({
      caseId: CASE_ID,
      initialSync: activeSyncFixture("queued", { poll_after_ms: 500 }),
      onTerminal: vi.fn(),
    }));

    await act(async () => { await vi.advanceTimersByTimeAsync(14_999); });
    expect(apiMocks.getWalletCaseSync).not.toHaveBeenCalled();
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    await act(async () => {
      document.dispatchEvent(new Event("visibilitychange"));
      await Promise.resolve();
    });
    expect(apiMocks.getWalletCaseSync).toHaveBeenCalledTimes(1);
  });

  it("aborts an old case and rejects its late result after route identity changes", async () => {
    const pending = deferred<ReturnType<typeof activeSyncFixture>>();
    apiMocks.getWalletCaseSync.mockReturnValue(pending.promise);
    const initial = activeSyncFixture("running", { poll_after_ms: 500 });
    const onTerminal = vi.fn();
    const { result, rerender } = renderHook(
      ({ caseId, initialSync }) => useWalletCaseSyncJob({ caseId, initialSync, onTerminal }),
      { initialProps: { caseId: CASE_ID, initialSync: initial as WalletCaseSync | null } },
    );
    await act(async () => { await vi.advanceTimersByTimeAsync(500); });

    const otherCaseId = "550e8400-e29b-41d4-a716-446655440099";
    rerender({ caseId: otherCaseId, initialSync: null });
    await act(async () => {
      pending.resolve(succeededSyncFixture());
      await Promise.resolve();
    });
    expect(result.current.sync).toBeNull();
    expect(onTerminal).not.toHaveBeenCalled();
  });
});
