import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE,
  getPersistedWalletTransactionTraceEvidence,
  getWalletTransactionTraceBocVerification,
  getWalletTransactionTraceEvidence,
  persistWalletTransactionTraceEvidence,
  verifyWalletTransactionTraceBocs,
} from "./api";

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

describe("persisted transaction trace evidence API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the exact persisted endpoint without cache or provider-side method", async () => {
    const payload = { contract_version: "tonapi_low_level_trace_evidence_v1" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      getPersistedWalletTransactionTraceEvidence(25, HASH, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/25/transactions/${HASH}/trace-evidence/persisted`,
      { cache: "no-store", signal: controller.signal },
    );
  });

  it("maps only the exact absent-record 404 contract to null", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({ detail: "Persisted trace evidence not found" }),
          {
            status: 404,
            headers: { "Content-Type": "application/json" },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: "Wallet transaction not found" }), {
          status: 404,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      getPersistedWalletTransactionTraceEvidence(25, HASH),
    ).resolves.toBeNull();
    await expect(
      getPersistedWalletTransactionTraceEvidence(25, HASH),
    ).rejects.toThrow("Wallet transaction not found");
  });

  it("captures through an explicit no-store POST with the supplied signal", async () => {
    const payload = { contract_version: "tonapi_low_level_trace_evidence_v1" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      persistWalletTransactionTraceEvidence(25, HASH, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/25/transactions/${HASH}/trace-evidence/persisted`,
      {
        method: "POST",
        cache: "no-store",
        signal: controller.signal,
      },
    );
  });
});

describe("local transaction BOC verification API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads provider-free and maps only the exact absence detail to null", async () => {
    const payload = { contract_version: "ton_boc_trace_verification_v1" };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(JSON.stringify(payload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            detail: "Locally verified transaction BOC evidence not found",
          }),
          { status: 404, headers: { "Content-Type": "application/json" } },
        ),
      );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      getWalletTransactionTraceBocVerification(25, HASH, controller.signal),
    ).resolves.toEqual(payload);
    await expect(
      getWalletTransactionTraceBocVerification(25, HASH),
    ).resolves.toBeNull();
    expect(fetchMock.mock.calls[0]).toEqual([
      `${API_BASE}/api/wallets/ingest/25/transactions/${HASH}/trace-evidence/boc-verification`,
      { cache: "no-store", signal: controller.signal },
    ]);
  });

  it("uses an explicit no-store POST for local verification", async () => {
    const payload = { contract_version: "ton_boc_trace_verification_v1" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      verifyWalletTransactionTraceBocs(25, HASH, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/25/transactions/${HASH}/trace-evidence/boc-verification`,
      { method: "POST", cache: "no-store", signal: controller.signal },
    );
  });
});
