import { afterEach, describe, expect, it, vi } from "vitest";

import { getProvidersStatus } from "./api";
import { API_BASE } from "./apiBase";
import {
  WalletCaseApiError,
  archiveWalletCase,
  cancelWalletCaseSync,
  createWalletCase,
  createWalletCaseSync,
  deleteWalletCase,
  getWalletCase,
  getWalletCaseCheckpointContinuationReceipt,
  getWalletCaseCheckpointContinuationPlan,
  getWalletCaseActivity,
  getWalletCaseActivityDetail,
  getWalletCaseSync,
  getWalletCaseSyncManifest,
  getWalletCaseStreamCheckpoint,
  getWalletCaseStreamCheckpointChain,
  getWalletCaseStreamCheckpointHistory,
  getWalletCaseStreamCheckpoints,
  listWalletCases,
  restoreWalletCase,
  resumeWalletCaseContinuationPlan,
  resumeWalletCaseStreamCheckpoint,
  updateWalletCaseMetadata,
} from "./walletCaseApi";
import {
  activeResumeSyncFixture,
  activeSyncFixture,
  CASE_ID,
  CHECKPOINT_ID,
  CONTINUATION_PLAN_ID,
  emptyWalletCaseFixture,
  IDEMPOTENCY_KEY,
  incrementalSyncFixture,
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
import { manifestResponseFixture } from "./test/walletCaseSyncManifestFixtures";
import {
  checkpointContinuationReceiptFixture,
  checkpointContinuationPlanFixture,
  streamCheckpointCatalogFixture,
  streamCheckpointChainFixture,
  streamCheckpointDetailFixture,
  streamCheckpointHistoryFixture,
} from "./test/walletCaseStreamCheckpointFixtures";

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
      .mockResolvedValueOnce(jsonResponse({
        cases: [populated], limit: 7, state: "active", query: null,
        network: null, data_environment: null, truncated: false, next_cursor: null,
      }))
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
    await expect(listWalletCases({ limit: 7, signal: controller.signal })).resolves.toEqual({
      cases: [populated], limit: 7, state: "active", query: null,
      network: null, data_environment: null, truncated: false, next_cursor: null,
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
      `${API_BASE}/api/v1/cases?limit=7&state=active`,
      { cache: "no-store", signal: controller.signal },
    ]);
  });

  it.each([0, 51, 1.5, Number.NaN])(
    "rejects an unsafe Wallet Case catalog limit before fetching: %s",
    async (limit) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);

      await expect(listWalletCases({ limit })).rejects.toThrow(/from 1 through 50/);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("binds a Wallet Case catalog response to the requested page size", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      cases: [walletCaseFixture()],
      limit: 8,
      state: "active",
      query: null,
      network: null,
      data_environment: null,
      truncated: false,
      next_cursor: null,
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listWalletCases({ limit: 7 })).rejects.toThrow(/requested limit/);
  });

  it("requests an opaque Case catalog continuation without rewriting it", async () => {
    const cursor = "opaque-signed.cursor";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      cases: [walletCaseFixture()],
      limit: 1,
      state: "archived",
      query: null,
      network: null,
      data_environment: null,
      truncated: false,
      next_cursor: null,
    }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(listWalletCases({
      limit: 1,
      state: "archived",
      cursor,
      signal: controller.signal,
    })).resolves.toBeTruthy();
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases?limit=1&state=archived&cursor=opaque-signed.cursor`,
      { cache: "no-store", signal: controller.signal },
    );
  });

  it("canonicalizes and strictly binds Wallet Case discovery filters", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({
      cases: [],
      limit: 12,
      state: "archived",
      query: "Treasury 100%",
      network: "ton-testnet",
      data_environment: "demo",
      truncated: false,
      next_cursor: null,
    }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(listWalletCases({
      limit: 12,
      state: "archived",
      query: "  Treasury 100%  ",
      network: "ton-testnet",
      dataEnvironment: "demo",
    })).resolves.toMatchObject({
      query: "Treasury 100%",
      network: "ton-testnet",
      data_environment: "demo",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases?limit=12&state=archived&q=Treasury+100%25&network=ton-testnet&data_environment=demo`,
      { cache: "no-store", signal: undefined },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      cases: [],
      limit: 12,
      state: "archived",
      query: "different",
      network: "ton-testnet",
      data_environment: "demo",
      truncated: false,
      next_cursor: null,
    }));
    await expect(listWalletCases({
      limit: 12,
      state: "archived",
      query: "Treasury 100%",
      network: "ton-testnet",
      dataEnvironment: "demo",
    })).rejects.toThrow(/requested filters/);
  });

  it.each(["", "   ", "x".repeat(121)])(
    "rejects an invalid Case discovery query before fetching: %j",
    async (query) => {
      const fetchMock = vi.fn();
      vi.stubGlobal("fetch", fetchMock);
      await expect(listWalletCases({ query })).rejects.toThrow(/1 through 120/);
      expect(fetchMock).not.toHaveBeenCalled();
    },
  );

  it("archives and restores a Case only from state-bound responses", async () => {
    const archived = emptyWalletCaseFixture({
      archived_at: "2026-08-27T12:00:00Z",
      updated_at: "2026-08-27T12:00:00Z",
    });
    const restored = emptyWalletCaseFixture({
      updated_at: "2026-08-27T12:01:00Z",
    });
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(archived))
      .mockResolvedValueOnce(jsonResponse(restored));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(archiveWalletCase(CASE_ID, controller.signal)).resolves.toEqual(archived);
    await expect(restoreWalletCase(CASE_ID, controller.signal)).resolves.toEqual(restored);
    expect(fetchMock.mock.calls).toEqual([
      [
        `${API_BASE}/api/v1/cases/${CASE_ID}/archive`,
        { method: "POST", cache: "no-store", signal: controller.signal },
      ],
      [
        `${API_BASE}/api/v1/cases/${CASE_ID}/restore`,
        { method: "POST", cache: "no-store", signal: controller.signal },
      ],
    ]);

    fetchMock.mockResolvedValueOnce(jsonResponse(restored));
    await expect(archiveWalletCase(CASE_ID)).rejects.toThrow(/does not match/);
  });

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
      mode: "bounded" as const,
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

  it("binds an incremental request to a custom acquisition response", async () => {
    const incremental = incrementalSyncFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(incremental, 202));
    vi.stubGlobal("fetch", fetchMock);
    const request = {
      mode: "incremental" as const,
      time_window: "24h" as const,
      surfaces: [...incremental.requested_scope.surfaces],
    };

    await expect(
      createWalletCaseSync(CASE_ID, request, IDEMPOTENCY_KEY),
    ).resolves.toEqual(incremental);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual(request);

    fetchMock.mockResolvedValueOnce(jsonResponse(activeSyncFixture("queued"), 202));
    await expect(
      createWalletCaseSync(CASE_ID, request, IDEMPOTENCY_KEY),
    ).rejects.toThrow(/requested scope/);
  });

  it("rejects invalid incremental bounds before issuing a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(createWalletCaseSync(CASE_ID, {
      mode: "incremental",
      time_window: "3d",
      surfaces: ["transactions"],
    }, IDEMPOTENCY_KEY)).rejects.toThrow(/cannot define time bounds/);
    expect(fetchMock).not.toHaveBeenCalled();
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

  it("reads a no-store acquisition manifest bound to its case and sync", async () => {
    const payload = manifestResponseFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      getWalletCaseSyncManifest(CASE_ID, SYNC_ID, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/syncs/${SYNC_ID}/manifest`,
      { cache: "no-store", signal: controller.signal },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      ...payload,
      document: { ...payload.document, sync_public_id: OTHER_SYNC_ID },
    }));
    await expect(getWalletCaseSyncManifest(CASE_ID, SYNC_ID)).rejects.toThrow(
      /requested sync/,
    );
  });

  it("reads a verified latest checkpoint catalog bound to its case", async () => {
    const payload = streamCheckpointCatalogFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payload));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      getWalletCaseStreamCheckpoints(CASE_ID, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/stream-checkpoints`,
      { cache: "no-store", signal: controller.signal },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      ...payload,
      case_public_id: OTHER_CASE_ID,
      checkpoints: payload.checkpoints.map((item) => ({
        ...item,
        document: { ...item.document, case_public_id: OTHER_CASE_ID },
      })),
    }));
    await expect(getWalletCaseStreamCheckpoints(CASE_ID)).rejects.toThrow(
      /does not match/,
    );
  });

  it("reads exact checkpoint detail and opaque frozen history pages", async () => {
    const detail = streamCheckpointDetailFixture();
    const history = streamCheckpointHistoryFixture();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(detail))
      .mockResolvedValueOnce(jsonResponse(history));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseStreamCheckpoint(
      CASE_ID,
      CHECKPOINT_ID,
      controller.signal,
    )).resolves.toEqual(detail);
    await expect(getWalletCaseStreamCheckpointHistory({
      caseId: CASE_ID,
      limit: 1,
      cursor: "opaque-signed.cursor",
      signal: controller.signal,
    })).resolves.toEqual(history);
    expect(fetchMock.mock.calls).toEqual([
      [
        `${API_BASE}/api/v1/cases/${CASE_ID}/stream-checkpoints/${CHECKPOINT_ID}`,
        { cache: "no-store", signal: controller.signal },
      ],
      [
        `${API_BASE}/api/v1/cases/${CASE_ID}/stream-checkpoints/history?limit=1&cursor=opaque-signed.cursor`,
        { cache: "no-store", signal: controller.signal },
      ],
    ]);
  });

  it("reads a no-store content-addressed checkpoint chain bound to its tip", async () => {
    const chain = streamCheckpointChainFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(chain));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseStreamCheckpointChain(
      CASE_ID,
      CHECKPOINT_ID,
      controller.signal,
    )).resolves.toEqual(chain);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/stream-checkpoints/${CHECKPOINT_ID}/chain`,
      { cache: "no-store", signal: controller.signal },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      ...chain,
      document: { ...chain.document, case_public_id: OTHER_CASE_ID },
    }));
    await expect(getWalletCaseStreamCheckpointChain(
      CASE_ID,
      CHECKPOINT_ID,
    )).rejects.toThrow(/does not match/);
  });

  it("reads a no-store continuation plan bound to its Wallet Case", async () => {
    const plan = checkpointContinuationPlanFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(plan));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseCheckpointContinuationPlan(
      CASE_ID,
      controller.signal,
    )).resolves.toEqual(plan);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/stream-checkpoints/continuation-plan`,
      { cache: "no-store", signal: controller.signal },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse({
      ...plan,
      document: { ...plan.document, case_public_id: OTHER_CASE_ID },
    }));
    await expect(getWalletCaseCheckpointContinuationPlan(CASE_ID)).rejects.toThrow(
      /does not match/,
    );
  });

  it("reads a no-store continuation receipt bound to its Case and sync", async () => {
    const receipt = checkpointContinuationReceiptFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(receipt));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseCheckpointContinuationReceipt(
      CASE_ID,
      SYNC_ID,
      controller.signal,
    )).resolves.toEqual(receipt);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/syncs/${SYNC_ID}/continuation-receipt`,
      { cache: "no-store", signal: controller.signal },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse(receipt));
    await expect(getWalletCaseCheckpointContinuationReceipt(
      CASE_ID,
      OTHER_SYNC_ID,
    )).rejects.toThrow(/does not match/);
  });

  it("rejects unsafe checkpoint history inputs and response scope", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(getWalletCaseStreamCheckpointHistory({
      caseId: CASE_ID,
      limit: 51,
    })).rejects.toThrow(/1 through 50/);
    await expect(getWalletCaseStreamCheckpointHistory({
      caseId: CASE_ID,
      cursor: "",
    })).rejects.toThrow(/cursor is invalid/);
    expect(fetchMock).not.toHaveBeenCalled();

    fetchMock.mockResolvedValueOnce(jsonResponse({
      ...streamCheckpointHistoryFixture(),
      case_public_id: OTHER_CASE_ID,
    }));
    await expect(getWalletCaseStreamCheckpointHistory({
      caseId: CASE_ID,
      limit: 1,
    })).rejects.toThrow(/does not match/);
  });

  it("resumes one canonical checkpoint with a bound idempotent POST", async () => {
    const queued = activeResumeSyncFixture();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(queued, 202));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(resumeWalletCaseStreamCheckpoint(
      CASE_ID,
      CHECKPOINT_ID,
      IDEMPOTENCY_KEY,
      controller.signal,
    )).resolves.toEqual(queued);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/stream-checkpoints/${CHECKPOINT_ID}/resume`,
      {
        method: "POST",
        cache: "no-store",
        headers: { "Idempotency-Key": IDEMPOTENCY_KEY },
        signal: controller.signal,
      },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse(activeSyncFixture("queued"), 202));
    await expect(resumeWalletCaseStreamCheckpoint(
      CASE_ID,
      CHECKPOINT_ID,
      IDEMPOTENCY_KEY,
    )).rejects.toThrow(/does not match/);
  });

  it("resumes an exact continuation plan and rejects mismatched provenance", async () => {
    const queued = activeResumeSyncFixture();
    const planBound = {
      ...queued,
      requested_scope: {
        ...queued.requested_scope,
        continuation_plan_public_id: CONTINUATION_PLAN_ID,
        resume_page_budget: 3,
      },
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(planBound, 202));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(resumeWalletCaseContinuationPlan(
      CASE_ID,
      CONTINUATION_PLAN_ID,
      CHECKPOINT_ID,
      3,
      IDEMPOTENCY_KEY,
      controller.signal,
    )).resolves.toEqual(planBound);
    expect(fetchMock).toHaveBeenCalledWith(
      (
        `${API_BASE}/api/v1/cases/${CASE_ID}/stream-checkpoints/` +
        `continuation-plan/${CONTINUATION_PLAN_ID}/${CHECKPOINT_ID}/resume`
      ),
      {
        method: "POST",
        cache: "no-store",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": IDEMPOTENCY_KEY,
        },
        body: JSON.stringify({ page_budget: 3 }),
        signal: controller.signal,
      },
    );

    fetchMock.mockResolvedValueOnce(jsonResponse(queued, 202));
    await expect(resumeWalletCaseContinuationPlan(
      CASE_ID,
      CONTINUATION_PLAN_ID,
      CHECKPOINT_ID,
      3,
      IDEMPOTENCY_KEY,
    )).rejects.toThrow(/does not match/);
  });

  it("rejects malformed checkpoint resume identity before network I/O", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(resumeWalletCaseStreamCheckpoint(
      CASE_ID,
      "scp_not-a-checkpoint",
      IDEMPOTENCY_KEY,
    )).rejects.toThrow(/checkpoint id is invalid/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects malformed continuation plan identity before network I/O", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(resumeWalletCaseContinuationPlan(
      CASE_ID,
      "cpl_not-a-plan",
      CHECKPOINT_ID,
      3,
      IDEMPOTENCY_KEY,
    )).rejects.toThrow(/continuation plan id is invalid/);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejects a noncanonical continuation page budget before network I/O", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(resumeWalletCaseContinuationPlan(
      CASE_ID,
      CONTINUATION_PLAN_ID,
      CHECKPOINT_ID,
      0,
      IDEMPOTENCY_KEY,
    )).rejects.toThrow(/page budget must be from 1 through 10/);
    expect(fetchMock).not.toHaveBeenCalled();
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
      mode: "bounded", time_window: "24h", surfaces: ["transactions"],
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
