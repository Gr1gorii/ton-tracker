import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, getWalletTransactionTraceEvidence } from "./api";

const HASH = "a".repeat(64);

describe("getWalletTransactionTraceEvidence", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the exact transaction endpoint, no-store, and the supplied signal", async () => {
    const payload = { contract_version: "tonapi_transaction_trace_preview_v1" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      getWalletTransactionTraceEvidence(25, HASH, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/25/transactions/${HASH}/trace-evidence`,
      {
        cache: "no-store",
        signal: controller.signal,
      },
    );
  });

  it("encodes the hash path and surfaces a sanitized backend detail", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Stored transaction is ineligible." }), {
        status: 409,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getWalletTransactionTraceEvidence(25, "hash/with space"),
    ).rejects.toThrow("Stored transaction is ineligible.");
    expect(fetchMock.mock.calls[0][0]).toBe(
      `${API_BASE}/api/wallets/ingest/25/transactions/hash%2Fwith%20space/trace-evidence`,
    );
  });
});
