import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE,
  createWalletCase,
  createWalletCaseSync,
  getProvidersStatus,
  getWalletCase,
  getWalletCaseSync,
  listWalletCases,
} from "./api";
import type { WalletCase } from "./walletCase";

const CASE_ID = "550e8400-e29b-41d4-a716-446655440000";
const SYNC_ID = "550e8400-e29b-41d4-b716-446655440001";
const OTHER_CASE_ID = "550e8400-e29b-41d4-a716-446655440099";
const OTHER_SYNC_ID = "550e8400-e29b-41d4-b716-446655440099";

function walletCaseFixture(overrides: Partial<WalletCase> = {}): WalletCase {
  return {
    public_id: CASE_ID,
    network: "ton-mainnet",
    data_environment: "demo",
    canonical_wallet_key: `0:${"a".repeat(64)}`,
    identity_version: "ton_std_address_v1",
    display_address: "EQC-demo-wallet",
    label: null,
    note: null,
    created_at: "2026-08-09T12:00:00Z",
    updated_at: "2026-08-09T12:01:00Z",
    latest_sync: {
      public_id: SYNC_ID,
      state: "succeeded",
      stage: "completed",
      progress: { current: 1, total: 1 },
      provider: "mock_wallet_activity",
      data_mode: "mock",
      requested_scope: {
        time_window: "24h",
        start_at: "2026-08-08T12:00:00Z",
        end_at: "2026-08-09T12:00:00Z",
        surfaces: ["transactions", "balances"],
      },
      coverage: {
        state: "unknown",
        requested_start_at: "2026-08-08T12:00:00Z",
        requested_end_at: "2026-08-09T12:00:00Z",
        requested_surfaces: ["transactions", "balances"],
        unavailable_surfaces: [],
        incomplete_surfaces: [],
        streams: [],
        full_history_proven: false,
      },
      summary: {
        activity_counts: { transfers: 2, transactions: 3, swaps: 1, balances: 2 },
        failed_transaction_count: 1,
        warning_count: 2,
        portfolio_snapshot: {
          total_balance_usd: "950.42",
          priced_assets: 2,
          unpriced_assets: 1,
        },
      },
      limitations: [
        {
          code: "bounded_interval_not_full_history",
          message: "The selected interval is not full wallet history.",
        },
      ],
      message: "Demo sync completed.",
      created_at: "2026-08-09T12:00:00Z",
      started_at: "2026-08-09T12:00:00Z",
      completed_at: "2026-08-09T12:01:00Z",
    },
    summary: {
      activity_counts: { transfers: 2, transactions: 3, swaps: 1, balances: 2 },
      failed_transaction_count: 1,
      warning_count: 2,
      portfolio_snapshot: {
        total_balance_usd: "950.42",
        priced_assets: 2,
        unpriced_assets: 1,
      },
    },
    limitations: [
      {
        code: "bounded_interval_not_full_history",
        message: "The selected interval is not full wallet history.",
      },
    ],
    ...overrides,
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("Wallet Case API", () => {
  it("reads request-context provider capability state without browser caching", async () => {
    const payload = { marker: "provider-status" };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getProvidersStatus(controller.signal)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/providers/status`, {
      cache: "no-store",
      signal: controller.signal,
    });
  });

  it("creates or opens a case with an abortable no-store request", async () => {
    const walletCase = walletCaseFixture({
      latest_sync: null,
      summary: {
        activity_counts: { transfers: 0, transactions: 0, swaps: 0, balances: 0 },
        failed_transaction_count: 0,
        warning_count: 0,
        portfolio_snapshot: { total_balance_usd: null, priced_assets: 0, unpriced_assets: 0 },
      },
      limitations: [{ code: "not_synchronized", message: "This case has not been synchronized yet." }],
    });
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ created: false, case: walletCase }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const request = {
      wallet_address: " EQC-demo-wallet ",
      network: "ton-mainnet" as const,
      data_environment: "demo" as const,
      label: "Treasury",
    };

    await expect(createWalletCase(request, controller.signal)).resolves.toEqual({
      created: false,
      case: walletCase,
    });
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/v1/cases`, {
      method: "POST",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
      signal: controller.signal,
    });
  });

  it("lists and reads cases without caching server state", async () => {
    const walletCase = walletCaseFixture();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({ cases: [walletCase], limit: 7, truncated: false }),
      )
      .mockResolvedValueOnce(jsonResponse(walletCase));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(listWalletCases(7, controller.signal)).resolves.toEqual({
      cases: [walletCase],
      limit: 7,
      truncated: false,
    });
    await expect(getWalletCase(CASE_ID, controller.signal)).resolves.toEqual(walletCase);

    expect(fetchMock.mock.calls).toEqual([
      [
        `${API_BASE}/api/v1/cases?limit=7`,
        { cache: "no-store", signal: controller.signal },
      ],
      [
        `${API_BASE}/api/v1/cases/${CASE_ID}`,
        { cache: "no-store", signal: controller.signal },
      ],
    ]);
  });

  it("creates and reads the explicit bounded sync contract", async () => {
    const sync = walletCaseFixture().latest_sync;
    if (!sync) throw new Error("fixture must include a sync");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(sync, 201))
      .mockResolvedValueOnce(jsonResponse(sync));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const request = {
      time_window: "24h" as const,
      surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"] as const,
    };

    await expect(
      createWalletCaseSync(
        CASE_ID,
        { ...request, surfaces: [...request.surfaces] },
        controller.signal,
      ),
    ).resolves.toEqual(sync);
    await expect(getWalletCaseSync(CASE_ID, SYNC_ID, controller.signal)).resolves.toEqual(sync);

    expect(fetchMock.mock.calls[0]).toEqual([
      `${API_BASE}/api/v1/cases/${CASE_ID}/syncs`,
      {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...request, surfaces: [...request.surfaces] }),
        signal: controller.signal,
      },
    ]);
    expect(fetchMock.mock.calls[1]).toEqual([
      `${API_BASE}/api/v1/cases/${CASE_ID}/syncs/${SYNC_ID}`,
      { cache: "no-store", signal: controller.signal },
    ]);
  });

  it("preserves backend errors and fails closed on mixed case evidence", async () => {
    const unsafe = walletCaseFixture({ data_environment: "live" });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(unsafe))
      .mockResolvedValueOnce(
        jsonResponse({ detail: "The requested live case cannot use demo evidence." }, 409),
      );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCase(CASE_ID)).rejects.toThrow(
      "wallet case environment does not match its latest sync evidence",
    );
    await expect(
      createWalletCase({
        wallet_address: "EQC-demo-wallet",
        network: "ton-mainnet",
        data_environment: "live",
      }),
    ).rejects.toThrow("The requested live case cannot use demo evidence.");
  });

  it("binds read responses to the case and sync ids in the requested URL", async () => {
    const mismatchedCase = walletCaseFixture({ public_id: OTHER_CASE_ID });
    const sync = walletCaseFixture().latest_sync;
    if (!sync) throw new Error("fixture must include a sync");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(mismatchedCase))
      .mockResolvedValueOnce(jsonResponse({ ...sync, public_id: OTHER_SYNC_ID }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCase(CASE_ID)).rejects.toThrow(/requested case id/);
    await expect(getWalletCaseSync(CASE_ID, SYNC_ID)).rejects.toThrow(
      /requested sync id/,
    );
  });
});
