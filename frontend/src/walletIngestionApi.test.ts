import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE,
  getWalletIngestionRun,
  previewWalletIngestion,
  runWalletIngestion,
} from "./api";
import type { WalletIngestionRequest } from "./types";

const request: WalletIngestionRequest = {
  wallet_address: "UQwallet",
  time_window: "24h",
  surfaces: ["transactions", "balances"],
};

afterEach(() => vi.unstubAllGlobals());

describe("wallet ingestion API", () => {
  it("previews with an abortable no-store request", async () => {
    const payload = { success: true };
    const fetchMock = successfulFetch(payload);
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(previewWalletIngestion(request, controller.signal)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/wallets/ingest/preview`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
  });

  it("creates an evidence run with an abortable no-store request", async () => {
    const payload = { run_id: 25 };
    const fetchMock = successfulFetch(payload, 201);
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(runWalletIngestion(request, controller.signal)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/wallets/ingest`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
  });

  it("reads a saved run without cache and preserves backend errors", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ run_id: 25 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Stored run is unavailable." }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletIngestionRun(25, controller.signal)).resolves.toEqual({ run_id: 25 });
    await expect(getWalletIngestionRun(26)).rejects.toThrow("Stored run is unavailable.");
    expect(fetchMock.mock.calls[0]).toEqual([
      `${API_BASE}/api/wallets/ingest/25`,
      { cache: "no-store", signal: controller.signal },
    ]);
  });
});

function successfulFetch(payload: unknown, status = 200) {
  return vi.fn().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}
