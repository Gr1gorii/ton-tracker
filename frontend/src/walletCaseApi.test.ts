import { afterEach, describe, expect, it, vi } from "vitest";

import { getProvidersStatus } from "./api";
import { API_BASE } from "./apiBase";
import {
  WalletCaseApiError,
  cancelWalletCaseSync,
  createWalletCase,
  createWalletCaseSync,
  deleteWalletCase,
  getWalletCase,
  getWalletCaseActivity,
  getWalletCaseActivityDetail,
  getWalletCaseSync,
  listWalletCases,
  updateWalletCaseMetadata,
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
import {
  ACTIVITY_ID,
  activityDetailFixture,
  activityFiltersFixture,
  activityResponseFixture,
} from "./test/walletCaseActivityFixtures";

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
    expect(fetchMock.mock.calls[1]).toEqual([
      `${API_BASE}/api/v1/cases?limit=7`,
      { cache: "no-store", signal: controller.signal },
    ]);
  });

  it.each([0, 51, 1.5, Number.NaN])(
    "rejects an unsafe Wallet Case catalog limit before fetching: %s",
    async (limit) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);

      await expect(listWalletCases(limit)).rejects.toThrow(/from 1 through 50/);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("deletes a case only from a strictly bound lifecycle receipt", async () => {
    const receipt = {
      deleted: true as const,
      case_public_id: CASE_ID,
      audit_event_public_id: OTHER_CASE_ID,
      deleted_at: "2026-08-26T12:00:00Z",
      removed: {
        syncs: 1,
        ingestion_runs: 1,
        evidence_verifications: 0,
        report_revisions: 2,
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(receipt));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(deleteWalletCase(CASE_ID, controller.signal)).resolves.toEqual(receipt);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}`,
      { method: "DELETE", cache: "no-store", signal: controller.signal },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      ...receipt,
      case_public_id: OTHER_CASE_ID,
    }));
    await expect(deleteWalletCase(CASE_ID)).rejects.toThrow(/does not match/);
  });

  it("updates Case metadata only from a versioned scope-bound response", async () => {
    const current = walletCaseFixture({
      overrides: { label: "Treasury", note: "Old note", metadata_version: 3 },
    });
    const updated = walletCaseFixture({
      overrides: {
        label: "Investigation",
        note: null,
        metadata_version: 4,
        updated_at: "2026-08-26T18:30:00Z",
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(updated));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const request = {
      expected_metadata_version: 3,
      label: "Investigation",
      note: null,
    };

    await expect(updateWalletCaseMetadata(current, request, controller.signal))
      .resolves.toEqual(updated);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}`,
      {
        method: "PATCH",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        signal: controller.signal,
      },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      ...updated,
      metadata_version: 5,
    }));
    await expect(updateWalletCaseMetadata(current, request)).rejects.toThrow(
      /does not match/,
    );
  });

  it("rejects invalid metadata updates before fetch and preserves stale version detail", async () => {
    const current = walletCaseFixture({ overrides: { metadata_version: 2 } });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      detail: {
        code: "case_metadata_changed",
        message_safe: "Wallet Case metadata changed.",
        retryable: true,
        current_metadata_version: 3,
      },
    }, 409));
    vi.stubGlobal("fetch", fetchMock);

    await expect(updateWalletCaseMetadata(current, {
      expected_metadata_version: 1,
      label: "Stale",
    })).rejects.toThrow(/version is invalid/);
    expect(fetchMock).not.toHaveBeenCalled();

    const conflict = await updateWalletCaseMetadata(current, {
      expected_metadata_version: 2,
      label: "Current draft",
    }).catch((error: unknown) => error);
    expect(conflict).toMatchObject({
      status: 409,
      code: "case_metadata_changed",
      retryable: true,
      currentMetadataVersion: 3,
    });
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

  it("reads pinned Activity pages with exact repeatable server filters and no cache", async () => {
    const payload = activityResponseFixture({
      filters: {
        ...activityFiltersFixture(),
        kinds: ["transaction", "swap"],
        directions: ["in"],
        outcomes: ["success"],
        data_origins: ["demo_fixture"],
        sort: "oldest",
      },
      aggregate: {
        total_items: 0,
        transactions: 0,
        transfers: 0,
        swaps: 0,
        failed_transactions: 0,
        source_sync_count: 1,
        suppressed_duplicate_observations: 0,
        conflicted_identity_count: 0,
      },
      observed_period: null,
      items: [],
    });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseActivity(CASE_ID, {
      snapshot: SYNC_ID,
      limit: 25,
      cursor: null,
      ...payload.filters,
    }, controller.signal)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/activity?snapshot=${SYNC_ID}&limit=25&kind=transaction&kind=swap&direction=in&outcome=success&data_origin=demo_fixture&sort=oldest`,
      { cache: "no-store", signal: controller.signal },
    );
  });

  it("canonicalizes reordered repeatable filters before fetch and response binding", async () => {
    const payload = activityResponseFixture({
      filters: {
        ...activityFiltersFixture(),
        kinds: ["transaction", "swap"],
        directions: ["in", "unknown"],
        outcomes: ["success", "unknown"],
        data_origins: ["demo_fixture", "provider_observed"],
      },
      aggregate: {
        total_items: 0,
        transactions: 0,
        transfers: 0,
        swaps: 0,
        failed_transactions: 0,
        source_sync_count: 1,
        suppressed_duplicate_observations: 0,
        conflicted_identity_count: 0,
      },
      observed_period: null,
      items: [],
    });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCaseActivity(CASE_ID, {
      snapshot: SYNC_ID,
      limit: 50,
      cursor: null,
      ...payload.filters,
      kinds: ["swap", "transaction"],
      directions: ["unknown", "in"],
      outcomes: ["unknown", "success"],
      data_origins: ["provider_observed", "demo_fixture"],
    })).resolves.toEqual(payload);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `${API_BASE}/api/v1/cases/${CASE_ID}/activity?snapshot=${SYNC_ID}&limit=50&kind=transaction&kind=swap&direction=in&direction=unknown&outcome=success&outcome=unknown&data_origin=demo_fixture&data_origin=provider_observed&sort=newest`,
    );
  });

  it("reads sanitized Activity detail bound to case, snapshot and public Activity id", async () => {
    const payload = activityDetailFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCaseActivityDetail(CASE_ID, SYNC_ID, ACTIVITY_ID)).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/activity/${ACTIVITY_ID}?snapshot=${SYNC_ID}`,
      { cache: "no-store", signal: undefined },
    );
  });

  it("rejects missing detail snapshot and malformed list scope before issuing a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCaseActivityDetail(CASE_ID, null as unknown as string, ACTIVITY_ID))
      .rejects.toThrow(/snapshot id must be a canonical UUIDv4/);
    await expect(getWalletCaseActivity(CASE_ID, {
      snapshot: null,
      limit: 50,
      cursor: "opaque-next",
      ...activityFiltersFixture(),
    })).rejects.toThrow(/pagination requires a pinned snapshot/);
    await expect(getWalletCaseActivity(CASE_ID, {
      snapshot: SYNC_ID,
      limit: 50,
      cursor: null,
      ...activityFiltersFixture(),
      protocol_id: "invented-dex",
    })).rejects.toThrow(/protocol id is not recognized/);
    for (const counterparty of [
      `-0:${"a".repeat(64)}`,
      `2147483648:${"a".repeat(64)}`,
      `-2147483649:${"a".repeat(64)}`,
    ]) {
      await expect(getWalletCaseActivity(CASE_ID, {
        snapshot: SYNC_ID,
        limit: 50,
        cursor: null,
        ...activityFiltersFixture(),
        counterparty,
      })).rejects.toThrow(/counterparty is not canonical/);
    }
    for (const fromAt of [
      "2026-02-30T00:00:00Z",
      "2026-08-01T24:00:00Z",
      "0000-01-01T00:00:00Z",
      "2026-08-01T00:00:00.0000001Z",
    ]) {
      await expect(getWalletCaseActivity(CASE_ID, {
        snapshot: SYNC_ID,
        limit: 50,
        cursor: null,
        ...activityFiltersFixture(),
        from_at: fromAt,
        to_at: "2026-08-02T00:00:00Z",
      })).rejects.toThrow(/period is invalid/);
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("preserves typed Activity errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: "invalid_activity_cursor", message_safe: "Cursor is invalid.", retryable: false },
    }, 422)));
    const caught = await getWalletCaseActivity(CASE_ID, {
      snapshot: SYNC_ID,
      limit: 50,
      cursor: "tampered",
      ...activityFiltersFixture(),
    }).catch((error: unknown) => error);
    expect(caught).toMatchObject({ status: 422, code: "invalid_activity_cursor", retryable: false });
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
