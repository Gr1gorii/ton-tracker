// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const catalogApiMock = vi.hoisted(() => vi.fn());

vi.mock("./api", () => ({
  getWalletIngestionRunCatalog: catalogApiMock,
}));

import { RECENT_RUN_CATALOG_LIMIT, useWalletRunCatalog } from "./useWalletRunCatalog";

function response(runId: string) {
  return {
    runs: [
      {
        run_id: runId,
        wallet_hint: "EQwall…llet",
        time_window: "24h",
        created_at: "2026-07-10T00:00:00Z",
        status: "success",
        data_mode: "real",
      },
    ],
    limit: RECENT_RUN_CATALOG_LIMIT,
    truncated: false,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("useWalletRunCatalog", () => {
  beforeEach(() => {
    catalogApiMock.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("loads the bounded catalog through its own abortable request", async () => {
    catalogApiMock.mockResolvedValue(response("25"));

    const { result } = renderHook(() => useWalletRunCatalog());

    await waitFor(() => expect(result.current.runs[0]?.run_id).toBe("25"));
    expect(catalogApiMock).toHaveBeenCalledWith(
      RECENT_RUN_CATALOG_LIMIT,
      expect.any(AbortSignal),
    );
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("aborts and ignores a stale response when a newer refresh wins", async () => {
    const first = deferred<ReturnType<typeof response>>();
    const second = deferred<ReturnType<typeof response>>();
    catalogApiMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    const { result } = renderHook(() => useWalletRunCatalog());
    await waitFor(() => expect(catalogApiMock).toHaveBeenCalledTimes(1));

    let refreshPromise!: Promise<void>;
    act(() => {
      refreshPromise = result.current.refresh();
    });
    expect(
      (catalogApiMock.mock.calls[0][1] as AbortSignal).aborted,
    ).toBe(true);

    second.resolve(response("26"));
    await act(async () => refreshPromise);
    expect(result.current.runs[0]?.run_id).toBe("26");

    first.resolve(response("25"));
    await act(async () => Promise.resolve());
    expect(result.current.runs[0]?.run_id).toBe("26");
  });

  it("keeps the last successful list when refresh fails", async () => {
    catalogApiMock.mockResolvedValueOnce(response("25"));
    const { result } = renderHook(() => useWalletRunCatalog());
    await waitFor(() => expect(result.current.runs[0]?.run_id).toBe("25"));

    catalogApiMock.mockRejectedValueOnce(new Error("Catalog offline"));
    await act(async () => result.current.refresh());

    expect(result.current.runs[0]?.run_id).toBe("25");
    expect(result.current.error).toBe("Catalog offline");
    expect(result.current.loading).toBe(false);
  });

  it("aborts the StrictMode probe request and the active request on unmount", async () => {
    const first = deferred<ReturnType<typeof response>>();
    const second = deferred<ReturnType<typeof response>>();
    catalogApiMock
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { result, unmount } = renderHook(() => useWalletRunCatalog(), {
      wrapper: StrictMode,
    });
    await waitFor(() => expect(catalogApiMock).toHaveBeenCalledTimes(2));
    const firstSignal = catalogApiMock.mock.calls[0][1] as AbortSignal;
    const secondSignal = catalogApiMock.mock.calls[1][1] as AbortSignal;
    expect(firstSignal.aborted).toBe(true);

    second.resolve(response("26"));
    await waitFor(() => expect(result.current.runs[0]?.run_id).toBe("26"));
    expect(secondSignal.aborted).toBe(false);

    unmount();
    expect(secondSignal.aborted).toBe(true);
  });
});
