import { afterEach, describe, expect, it, vi } from "vitest";

import { getProvidersStatus } from "./api";
import { API_BASE } from "./apiBase";
import {
  WalletCaseApiError,
  cancelWalletCaseSync,
  createWalletCase,
  createWalletCaseSync,
  getWalletCase,
  getWalletCaseSync,
  listWalletCases,
} from "./walletCaseApi";
import {
  activeSyncFixture,
  CASE_ID,
  emptyWalletCaseFixture,
  IDEMPOTENCY_KEY,
  succeededSyncFixture,
  SYNC_ID,
  walletCaseFixture,
} from "./test/walletCaseFixtures";

const OTHER_CASE_ID = "550e8400-e29b-41d4-a716-446655440099";
const OTHER_SYNC_ID = "550e8400-e29b-41d4-b716-446655440099";

function jsonResponse(
  payload: unknown,
  status = 200,
  headers: Record<string, string> = {},
): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
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

  it("creates, lists, and reads strictly bound no-store cases", async () => {
    const empty = emptyWalletCaseFixture();
    const populated = walletCaseFixture();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ created: false, case: empty }, 200))
      .mockResolvedValueOnce(jsonResponse({ cases: [populated], limit: 7, truncated: false }))
      .mockResolvedValueOnce(jsonResponse(populated));
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
      case: empty,
    });
    await expect(listWalletCases(7, controller.signal)).resolves.toEqual({
      cases: [populated], limit: 7, truncated: false,
    });
    await expect(getWalletCase(CASE_ID, controller.signal)).resolves.toEqual(populated);
    expect(fetchMock.mock.calls[0]).toEqual([
      `${API_BASE}/api/v1/cases`,
      {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: controller.signal,
      },
    ]);
  });

  it("starts a durable sync only from 202 with one explicit UUIDv4 idempotency key", async () => {
    const queued = activeSyncFixture("queued");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(queued, 202));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const request = {
      time_window: "24h" as const,
      surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"] as const,
    };

    await expect(createWalletCaseSync(
      CASE_ID,
      { ...request, surfaces: [...request.surfaces] },
      IDEMPOTENCY_KEY,
      controller.signal,
    )).resolves.toEqual(queued);
    expect(fetchMock).toHaveBeenCalledWith(`${API_BASE}/api/v1/cases/${CASE_ID}/syncs`, {
      method: "POST",
      cache: "no-store",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": IDEMPOTENCY_KEY,
      },
      body: JSON.stringify({ ...request, surfaces: [...request.surfaces] }),
      signal: controller.signal,
    });

    fetchMock.mockResolvedValueOnce(jsonResponse(queued, 201));
    await expect(createWalletCaseSync(CASE_ID, { ...request, surfaces: [...request.surfaces] }, IDEMPOTENCY_KEY))
      .rejects.toMatchObject({ status: 201 });
  });

  it("polls and cancels with strict URL identity binding", async () => {
    const running = activeSyncFixture("running");
    const cancelled = {
      ...running,
      state: "cancelled" as const,
      stage: "cancelled",
      status_version: 3,
      cancel_requested: true,
      message: "Sync cancelled safely.",
      updated_at: "2026-08-09T12:00:30Z",
      completed_at: "2026-08-09T12:00:30Z",
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(running))
      .mockResolvedValueOnce(jsonResponse(cancelled, 200));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseSync(CASE_ID, SYNC_ID, controller.signal)).resolves.toEqual(running);
    await expect(cancelWalletCaseSync(CASE_ID, SYNC_ID, controller.signal)).resolves.toEqual(cancelled);
    expect(fetchMock.mock.calls).toEqual([
      [
        `${API_BASE}/api/v1/cases/${CASE_ID}/syncs/${SYNC_ID}`,
        { cache: "no-store", signal: controller.signal },
      ],
      [
        `${API_BASE}/api/v1/cases/${CASE_ID}/syncs/${SYNC_ID}/cancel`,
        { method: "POST", cache: "no-store", signal: controller.signal },
      ],
    ]);
  });

  it("exposes structured conflict and retry metadata without leaking raw bodies", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({
        detail: {
          code: "active_sync_exists",
          message_safe: "This case already has an active synchronization.",
          retryable: true,
          active_sync_public_id: SYNC_ID,
        },
      }, 409))
      .mockResolvedValueOnce(jsonResponse({ detail: "Please wait." }, 429, { "Retry-After": "3" }));
    vi.stubGlobal("fetch", fetchMock);

    const conflict = await createWalletCaseSync(CASE_ID, {
      time_window: "24h", surfaces: ["transactions"],
    }, IDEMPOTENCY_KEY).catch((error: unknown) => error);
    expect(conflict).toBeInstanceOf(WalletCaseApiError);
    expect(conflict).toMatchObject({
      status: 409,
      code: "active_sync_exists",
      retryable: true,
      activeSyncPublicId: SYNC_ID,
    });

    const throttled = await getWalletCaseSync(CASE_ID, SYNC_ID).catch(
      (error: unknown) => error,
    );
    expect(throttled).toMatchObject({ status: 429, retryAfterMs: 3_000 });
  });

  it("fails closed before fetch for invalid ids and after fetch for mismatched ids", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(emptyWalletCaseFixture({ public_id: OTHER_CASE_ID })))
      .mockResolvedValueOnce(jsonResponse(succeededSyncFixture({ public_id: OTHER_SYNC_ID })));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCase("not-a-uuid")).rejects.toThrow(/canonical UUIDv4/);
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(getWalletCase(CASE_ID)).rejects.toThrow(/requested case id/);
    await expect(getWalletCaseSync(CASE_ID, SYNC_ID)).rejects.toThrow(/requested sync id/);
  });
});
