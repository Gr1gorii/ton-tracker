import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, getWalletRunSignals } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("getWalletRunSignals", () => {
  it("reads the selected run through a no-store abortable request", async () => {
    const payload = { run_id: 25, is_risk_score: false };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletRunSignals(25, controller.signal)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/25/signals`,
      { cache: "no-store", signal: controller.signal },
    );
  });

  it("surfaces the sanitized backend detail", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Wallet ingestion run not found" }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    await expect(getWalletRunSignals(25)).rejects.toThrow("Wallet ingestion run not found");
  });
});
