import { afterEach, describe, expect, it, vi } from "vitest";

import { getWalletIngestionRunCatalog } from "./api";

describe("getWalletIngestionRunCatalog", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the bounded collection GET with no-store and an abort signal", async () => {
    const payload = { runs: [], limit: 8, truncated: false };
    const fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => payload,
    });
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      getWalletIngestionRunCatalog(8, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://localhost:8000/api/wallets/ingest?limit=8",
      {
        cache: "no-store",
        signal: controller.signal,
      },
    );
  });
});
