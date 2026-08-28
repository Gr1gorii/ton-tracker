import { describe, expect, it } from "vitest";

import {
  parseWalletCase,
  parseWalletCaseDeletionResponse,
  parseWalletCaseListResponse,
  parseWalletCaseSync,
  parseWalletCaseUpsertResponse,
} from "./walletCase";
import {
  activeSyncFixture,
  CASE_ID,
  emptyWalletCaseFixture,
  failedSyncFixture,
  incrementalSyncFixture,
  resumeSyncFixture,
  retryWaitSyncFixture,
  succeededSyncFixture,
  walletCaseFixture,
  zeroSummaryFixture,
} from "./test/walletCaseFixtures";

const EMPTY_CATALOG_FILTERS = {
  query: null,
  network: null,
  data_environment: null,
} as const;

describe("wallet case contracts", () => {
  it("accepts a bounded unique Wallet Case catalog", () => {
    const first = walletCaseFixture();
    const second = emptyWalletCaseFixture({
      public_id: "550e8400-e29b-41d4-a716-446655440099",
      canonical_wallet_key: `0:${"b".repeat(64)}`,
    });
    expect(parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [first, second],
      limit: 2,
      state: "active",
      truncated: true,
      next_cursor: "opaque.cursor",
    }).cases).toHaveLength(2);
  });

  it("rejects unbounded, duplicate, and contradictory Wallet Case catalogs", () => {
    const walletCase = walletCaseFixture();
    expect(() => parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [walletCase], limit: 0, state: "active", truncated: false, next_cursor: null,
    })).toThrow(/limit/);
    expect(() => parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [walletCase], limit: 51, state: "active", truncated: false, next_cursor: null,
    })).toThrow(/bounded limit/);
    expect(() => parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [walletCase, walletCase], limit: 2, state: "active", truncated: false, next_cursor: null,
    })).toThrow(/duplicate/);
    expect(() => parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [walletCase], limit: 2, state: "active", truncated: true, next_cursor: "opaque.cursor",
    })).toThrow(/does not fill/);
    expect(() => parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [walletCase], limit: 1, state: "active", truncated: true, next_cursor: null,
    })).toThrow(/cursor contradicts/);
    expect(() => parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [walletCase], limit: 1, state: "active", truncated: false, next_cursor: "opaque.cursor",
    })).toThrow(/cursor contradicts/);
  });

  it("requires canonical discovery filters in Wallet Case catalog envelopes", () => {
    expect(parseWalletCaseListResponse({
      cases: [],
      limit: 20,
      state: "archived",
      query: "Treasury",
      network: "ton-mainnet",
      data_environment: "live",
      truncated: false,
      next_cursor: null,
    })).toMatchObject({
      query: "Treasury",
      network: "ton-mainnet",
      data_environment: "live",
    });
    for (const filters of [
      { query: " padded ", network: null, data_environment: null },
      { query: null, network: "ethereum", data_environment: null },
      { query: null, network: null, data_environment: "staging" },
    ]) {
      expect(() => parseWalletCaseListResponse({
        cases: [],
        limit: 20,
        state: "active",
        ...filters,
        truncated: false,
        next_cursor: null,
      })).toThrow(/query|network|environment/);
    }
  });

  it("accepts a terminal snapshot with explicit published-result provenance", () => {
    const parsed = parseWalletCase(walletCaseFixture());
    expect(parsed.current_snapshot?.result?.summary.activity_counts.transactions).toBe(3);
    expect(parsed.current_snapshot?.coverage.full_history_proven).toBe(false);
    expect(parsed.latest_sync).toEqual(parsed.latest_sync_attempt);
  });

  it("keeps an older usable snapshot while the latest attempt is running", () => {
    const active = activeSyncFixture("running");
    const snapshot = succeededSyncFixture({
      public_id: "550e8400-e29b-41d4-b716-446655440002",
      status_version: 7,
    });
    const parsed = parseWalletCase(walletCaseFixture({
      latestAttempt: active,
      currentSnapshot: snapshot,
    }));

    expect(parsed.active_sync?.public_id).toBe(active.public_id);
    expect(parsed.current_snapshot?.public_id).toBe(snapshot.public_id);
    expect(parsed.summary).toEqual(snapshot.result?.summary);
  });

  it("allows response-time polling hints to differ across equivalent case views", () => {
    const active = retryWaitSyncFixture({ poll_after_ms: 900 });
    expect(() => parseWalletCase({
      ...walletCaseFixture({ latestAttempt: active, currentSnapshot: null }),
      latest_sync: { ...active, poll_after_ms: 850 },
      active_sync: { ...active, poll_after_ms: 800 },
    })).not.toThrow();
  });

  it("accepts an unsynchronized case only with unavailable compatibility data", () => {
    const parsed = parseWalletCase(emptyWalletCaseFixture());
    expect(parsed.current_snapshot).toBeNull();
    expect(parsed.summary).toEqual(zeroSummaryFixture());
  });

  it("accepts retry_wait only as a queued job with bounded retry metadata", () => {
    expect(parseWalletCaseSync(retryWaitSyncFixture()).retry?.attempt).toBe(2);
    expect(() => parseWalletCaseSync(retryWaitSyncFixture({ state: "running" }))).toThrow(
      /retry metadata contradicts/,
    );
    expect(() => parseWalletCaseSync(activeSyncFixture("queued", { stage: "retry_wait" }))).toThrow(
      /retry metadata contradicts/,
    );
  });

  it("accepts explicit incremental acquisition lineage and fails closed on contradictions", () => {
    const incremental = incrementalSyncFixture();
    expect(parseWalletCaseSync(incremental).requested_scope).toMatchObject({
      mode: "incremental",
      time_window: "custom",
      overlap_seconds: 900,
      base_snapshot_public_id: "550e8400-e29b-41d4-b716-446655440003",
    });
    expect(() => parseWalletCaseSync({
      ...incremental,
      requested_scope: {
        ...incremental.requested_scope,
        acquisition_start_at: "2026-08-08T11:59:59Z",
      },
    })).toThrow(/acquisition scope/);
    expect(() => parseWalletCaseSync({
      ...incremental,
      requested_scope: {
        ...incremental.requested_scope,
        base_snapshot_public_id: null,
      },
    })).toThrow(/acquisition mode/);
    expect(() => parseWalletCaseSync({
      ...incremental,
      limitations: incremental.limitations.filter(
        (item) => item.code !== "incremental_composite_not_full_history",
      ),
      result: {
        ...incremental.result!,
        limitations: incremental.result!.limitations.filter(
          (item) => item.code !== "incremental_composite_not_full_history",
        ),
      },
    })).toThrow(/composite-history limitation/);
  });

  it("accepts checkpoint resume lineage and requires its limitation", () => {
    const resumed = resumeSyncFixture();
    expect(parseWalletCaseSync(resumed).requested_scope).toMatchObject({
      mode: "resume",
      time_window: "custom",
      overlap_seconds: 0,
      source_checkpoint_public_id: resumed.requested_scope.source_checkpoint_public_id,
    });
    expect(() => parseWalletCaseSync({
      ...resumed,
      requested_scope: {
        ...resumed.requested_scope,
        source_checkpoint_public_id: null,
      },
    })).toThrow(/acquisition mode/);
    expect(() => parseWalletCaseSync({
      ...resumed,
      limitations: resumed.limitations.filter(
        (item) => item.code !== "checkpoint_resume_composite_not_full_history",
      ),
      result: {
        ...resumed.result!,
        limitations: resumed.result!.limitations.filter(
          (item) => item.code !== "checkpoint_resume_composite_not_full_history",
        ),
      },
    })).toThrow(/composite-history limitation/);
  });

  it("binds acquisition manifest identity to honest sync lifecycle boundaries", () => {
    const succeeded = succeededSyncFixture();
    expect(parseWalletCaseSync(succeeded).acquisition_manifest?.public_id).toBe(
      succeeded.acquisition_manifest?.public_id,
    );
    expect(() => parseWalletCaseSync({
      ...succeeded,
      acquisition_manifest: {
        ...succeeded.acquisition_manifest!,
        content_hash_sha256: "0".repeat(64),
      },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseSync({
      ...succeeded,
      acquisition_manifest: null,
    })).toThrow(/manifest boundary/);
    expect(() => parseWalletCaseSync({
      ...activeSyncFixture("running"),
      acquisition_manifest: succeeded.acquisition_manifest,
    })).toThrow(/contradicts its lifecycle/);

    const legacyLimitations = [
      ...succeeded.limitations,
      { code: "acquisition_manifest_unavailable", message: "Legacy boundary." },
    ];
    expect(() => parseWalletCaseSync({
      ...succeeded,
      acquisition_manifest: null,
      limitations: legacyLimitations,
      result: { ...succeeded.result!, limitations: legacyLimitations },
    })).not.toThrow();
  });

  it("fails closed on invalid version, polling, progress, and timestamps", () => {
    expect(() => parseWalletCaseSync(activeSyncFixture("queued", { status_version: 0 }))).toThrow(
      /status version/,
    );
    expect(() => parseWalletCaseSync(activeSyncFixture("queued", { poll_after_ms: -1 }))).toThrow(
      /poll interval/,
    );
    expect(() => parseWalletCaseSync(activeSyncFixture("running", {
      progress: { current: 6, total: 5 },
    }))).toThrow(/exceeds its total/);
    expect(() => parseWalletCaseSync(activeSyncFixture("running", { started_at: null }))).toThrow(
      /timestamps contradict/,
    );
  });

  it("fails closed when nested result and flattened compatibility fields disagree", () => {
    const sync = succeededSyncFixture();
    expect(() => parseWalletCaseSync({
      ...sync,
      summary: {
        ...sync.summary,
        activity_counts: { ...sync.summary.activity_counts, transactions: 99 },
      },
    })).toThrow(/result does not match/);
    expect(() => parseWalletCaseSync(activeSyncFixture("running", {
      result: succeededSyncFixture().result,
    }))).toThrow(/result contradicts/);
  });

  it("fails closed when error metadata is missing or attached outside failed state", () => {
    expect(() => parseWalletCaseSync(failedSyncFixture({ error: null }))).toThrow(
      /error metadata contradicts/,
    );
    expect(() => parseWalletCaseSync(activeSyncFixture("running", {
      error: failedSyncFixture().error,
    }))).toThrow(/error metadata contradicts/);
  });

  it("binds every sync to the case identity and evidence environment", () => {
    const wrongCase = activeSyncFixture("running", {
      case_public_id: "550e8400-e29b-41d4-a716-446655440099",
    });
    expect(() => parseWalletCase(walletCaseFixture({ latestAttempt: wrongCase }))).toThrow(
      /identity does not match/,
    );
    expect(() => parseWalletCase(walletCaseFixture({
      overrides: { data_environment: "live" },
    }))).toThrow(/environment or identity/);
  });

  it("requires latest compatibility, active job, and snapshot lifecycle views to agree", () => {
    const active = activeSyncFixture("running");
    expect(() => parseWalletCase({
      ...walletCaseFixture({ latestAttempt: active, currentSnapshot: null }),
      latest_sync: activeSyncFixture("queued"),
    })).toThrow(/compatibility view/);
    expect(() => parseWalletCase({
      ...walletCaseFixture({ latestAttempt: active, currentSnapshot: null }),
      active_sync: null,
    })).toThrow(/omits its active sync/);
    expect(() => parseWalletCase({
      ...walletCaseFixture(),
      current_snapshot: failedSyncFixture(),
    })).toThrow(/current snapshot is not publishable/);
  });

  it("rejects a snapshot without its latest attempt or behind a usable latest attempt", () => {
    const olderSnapshot = succeededSyncFixture({
      public_id: "550e8400-e29b-41d4-b716-446655440002",
      status_version: 7,
    });
    expect(() => parseWalletCase(walletCaseFixture({
      latestAttempt: null,
      currentSnapshot: olderSnapshot,
    }))).toThrow(/snapshot provenance/);
    expect(() => parseWalletCase(walletCaseFixture({
      latestAttempt: succeededSyncFixture(),
      currentSnapshot: olderSnapshot,
    }))).toThrow(/snapshot provenance/);
  });

  it("uses current_snapshot, never the latest active attempt, as summary provenance", () => {
    const value = walletCaseFixture();
    expect(() => parseWalletCase({
      ...value,
      summary: {
        ...value.summary,
        activity_counts: { ...value.summary.activity_counts, transactions: 99 },
      },
    })).toThrow(/current snapshot/);
    expect(() => parseWalletCase({
      ...emptyWalletCaseFixture(),
      summary: { ...zeroSummaryFixture(), warning_count: 1 },
    })).toThrow(/without a snapshot/);
  });

  it("rejects bounded coverage that claims full wallet history", () => {
    const sync = succeededSyncFixture();
    expect(() => parseWalletCaseSync({
      ...sync,
      coverage: { ...sync.coverage, full_history_proven: true },
      result: sync.result && {
        ...sync.result,
        coverage: { ...sync.result.coverage, full_history_proven: true },
      },
    })).toThrow(/cannot claim full wallet history/);
  });

  it("validates upsert and list envelopes", () => {
    expect(parseWalletCaseUpsertResponse({ created: true, case: walletCaseFixture() }).created).toBe(true);
    expect(
      parseWalletCaseListResponse({
        ...EMPTY_CATALOG_FILTERS,
        cases: [walletCaseFixture()], limit: 20, state: "active", truncated: false, next_cursor: null,
      }).cases,
    ).toHaveLength(1);
    expect(parseWalletCase(walletCaseFixture()).public_id).toBe(CASE_ID);
  });

  it("requires bounded, positive Wallet Case metadata revisions", () => {
    expect(parseWalletCase(walletCaseFixture()).metadata_version).toBe(1);
    expect(() => parseWalletCase({
      ...walletCaseFixture(),
      metadata_version: 0,
    })).toThrow(/metadata version/);
    expect(() => parseWalletCase({
      ...walletCaseFixture(),
      label: "x".repeat(121),
    })).toThrow(/label is too long/);
    expect(() => parseWalletCase({
      ...walletCaseFixture(),
      note: "x".repeat(4_001),
    })).toThrow(/note is too long/);
  });

  it("requires explicit Case lifecycle timestamps and catalog state", () => {
    const archivedAt = "2026-08-27T12:00:00Z";
    expect(parseWalletCase(walletCaseFixture({
      overrides: { archived_at: archivedAt },
    })).archived_at).toBe(archivedAt);
    expect(() => parseWalletCase({
      ...walletCaseFixture(),
      archived_at: "not-a-time",
    })).toThrow(/archived time/);
    expect(() => parseWalletCaseListResponse({
      ...EMPTY_CATALOG_FILTERS,
      cases: [], limit: 20, state: "deleted", truncated: false, next_cursor: null,
    })).toThrow(/lifecycle state/);
  });

  it("validates a bounded deletion receipt and rejects identity/count drift", () => {
    const receipt = {
      deleted: true,
      case_public_id: CASE_ID,
      audit_event_public_id: "550e8400-e29b-41d4-a716-446655440099",
      deleted_at: "2026-08-26T12:00:00Z",
      removed: {
        syncs: 2,
        ingestion_runs: 2,
        evidence_verifications: 1,
        report_revisions: 3,
      },
    };
    expect(parseWalletCaseDeletionResponse(receipt)).toEqual(receipt);
    expect(() => parseWalletCaseDeletionResponse({
      ...receipt,
      audit_event_public_id: "not-a-uuid",
    })).toThrow(/identity/);
    expect(() => parseWalletCaseDeletionResponse({
      ...receipt,
      removed: { ...receipt.removed, syncs: -1 },
    })).toThrow(/sync count/);
  });
});
