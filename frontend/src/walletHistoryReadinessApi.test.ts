import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, inspectWalletHistoryReadiness } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("inspectWalletHistoryReadiness", () => {
  it("posts the exact target and selected runs with abort and no-store controls", async () => {
    const payload = { analysis_version: "wallet_history_readiness_v0.22.7" };
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(payload), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(inspectWalletHistoryReadiness(
      { target_run_id: 7, run_ids: [7, 4] },
      controller.signal,
    )).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/wallets/history/readiness`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ target_run_id: 7, run_ids: [7, 4] }),
      signal: controller.signal,
    });
  });

  it("surfaces canonical identity mismatches", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: "All history-readiness runs must resolve to the same canonical wallet identity." }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    )));
    await expect(inspectWalletHistoryReadiness({ target_run_id: 3, run_ids: [3, 2] })).rejects.toThrow("same canonical wallet identity");
  });
});
