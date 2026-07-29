import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, compareWalletRuns } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("compareWalletRuns", () => {
  it("posts the exact selected run IDs with no-store and abort support", async () => {
    const payload = { is_cluster_proof: false };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(compareWalletRuns([4, 7], controller.signal)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/wallets/cluster/compare`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_ids: [4, 7] }),
      signal: controller.signal,
    });
  });

  it("surfaces a mixed-mode comparison error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Cannot compare across mixed data modes" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      }),
    ));
    await expect(compareWalletRuns([1, 2])).rejects.toThrow("Cannot compare across mixed data modes");
  });
});
