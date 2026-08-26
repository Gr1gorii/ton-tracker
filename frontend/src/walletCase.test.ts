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
  retryWaitSyncFixture,
  succeededSyncFixture,
  walletCaseFixture,
  zeroSummaryFixture,
} from "./test/walletCaseFixtures";

describe("wallet case contracts", () => {
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
      parseWalletCaseListResponse({ cases: [walletCaseFixture()], limit: 20, truncated: false }).cases,
    ).toHaveLength(1);
    expect(parseWalletCase(walletCaseFixture()).public_id).toBe(CASE_ID);
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
