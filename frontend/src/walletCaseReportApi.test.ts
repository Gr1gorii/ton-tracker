import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "./apiBase";
import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";
import { walletCaseReportFixture } from "./test/walletCaseReportFixtures";
import { walletCaseReportRevisionComparisonFixture } from "./test/walletCaseReportRevisionFixtures";
import {
  captureWalletCaseReportRevision,
  compareWalletCaseReportRevisions,
  getWalletCaseReport,
  getWalletCaseReportRevision,
  listWalletCaseReportRevisions,
  walletCaseReportExportUrl,
  walletCaseReportRevisionExportUrl,
  WalletCaseReportApiError,
} from "./walletCaseReportApi";

afterEach(() => vi.unstubAllGlobals());

describe("Wallet Case report API", () => {
  it("loads a pinned no-store report and binds the response scope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(walletCaseReportFixture()));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseReport(CASE_ID, SYNC_ID, controller.signal)).resolves.toEqual(walletCaseReportFixture());
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/report?snapshot=${SYNC_ID}`,
      { cache: "no-store", signal: controller.signal },
    );
    expect(walletCaseReportExportUrl(CASE_ID, SYNC_ID)).toBe(
      `${API_BASE}/api/v1/cases/${CASE_ID}/report/export.json?snapshot=${SYNC_ID}`,
    );
  });

  it("rejects invalid IDs before fetch and scope drift after parsing", async () => {
    const drift = structuredClone(walletCaseReportFixture());
    drift.case_public_id = "550e8400-e29b-41d4-a716-446655440099";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(drift));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCaseReport("bad", SYNC_ID)).rejects.toThrow(/UUIDv4/);
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(getWalletCaseReport(CASE_ID, SYNC_ID)).rejects.toThrow(/scope/);
  });

  it("preserves safe typed API errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: "case_report_conflict", message_safe: "Report scope changed.", retryable: false },
    }, 409)));
    await expect(getWalletCaseReport(CASE_ID, SYNC_ID)).rejects.toEqual(expect.objectContaining<Partial<WalletCaseReportApiError>>({
      status: 409,
      code: "case_report_conflict",
      retryable: false,
      message: "Report scope changed.",
    }));
  });

  it("lists, captures and reads stored report revisions with exact request binding", async () => {
    const report = walletCaseReportFixture().report!;
    const revision = {
      public_id: report.public_id,
      content_hash_sha256: report.content_hash_sha256,
      case_public_id: CASE_ID,
      snapshot_public_id: SYNC_ID,
      assurance_level: report.assurance_level,
      captured_at: "2026-08-19T10:00:00Z",
      activity_digest_sha256: report.activity_revision.digest_sha256,
      evidence_digest_sha256: report.evidence_revision.digest_sha256,
      activity_count: report.activity_revision.aggregate.total_items,
      evidence_attempt_count: report.evidence_revision.total_attempts,
      canonical_eligible: false,
      limitation_count: report.limitations.length,
      unverified_claim_count: report.unverified_claims.length,
    };
    const catalog = {
      contract_version: "wallet_case_report_revision_catalog_v1",
      public_id: `rcat_${"ab".repeat(32)}`,
      case_public_id: CASE_ID,
      revision_cutoff_public_id: revision.public_id,
      items: [revision],
      aggregate: { total_revisions: 1, returned_count: 1 },
      page: { limit: 10, has_more: false, next_cursor: null },
      limitations: [{ code: "report_revisions_are_explicit_captures", message: "Only explicit captures are retained." }],
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse(catalog))
      .mockResolvedValueOnce(jsonResponse({ case_public_id: CASE_ID, created: true, revision }, 201))
      .mockResolvedValueOnce(jsonResponse({ case_public_id: CASE_ID, revision, report: walletCaseReportFixture() }))
      .mockResolvedValueOnce(jsonResponse(walletCaseReportRevisionComparisonFixture()));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(listWalletCaseReportRevisions(CASE_ID, 10, null, controller.signal)).resolves.toEqual(catalog);
    await expect(captureWalletCaseReportRevision(CASE_ID, SYNC_ID, controller.signal)).resolves.toEqual({ case_public_id: CASE_ID, created: true, revision });
    await expect(getWalletCaseReportRevision(CASE_ID, revision.public_id, controller.signal)).resolves.toEqual({ case_public_id: CASE_ID, revision, report: walletCaseReportFixture() });
    await expect(compareWalletCaseReportRevisions(CASE_ID, revision.public_id, revision.public_id, controller.signal)).resolves.toEqual(walletCaseReportRevisionComparisonFixture());
    expect(fetchMock.mock.calls[0]).toEqual([
      `${API_BASE}/api/v1/cases/${CASE_ID}/reports?limit=10`,
      { cache: "no-store", signal: controller.signal },
    ]);
    expect(fetchMock.mock.calls[1]).toEqual([
      `${API_BASE}/api/v1/cases/${CASE_ID}/reports`,
      expect.objectContaining({
        method: "POST",
        cache: "no-store",
        body: JSON.stringify({ snapshot_public_id: SYNC_ID }),
        signal: controller.signal,
      }),
    ]);
    expect(walletCaseReportRevisionExportUrl(CASE_ID, revision.public_id)).toBe(
      `${API_BASE}/api/v1/cases/${CASE_ID}/reports/${revision.public_id}/export.json`,
    );
    expect(fetchMock.mock.calls[3]).toEqual([
      `${API_BASE}/api/v1/cases/${CASE_ID}/reports/${revision.public_id}/compare/${revision.public_id}`,
      { cache: "no-store", signal: controller.signal },
    ]);
  });

  it("rejects invalid revision requests before fetch and status/body drift", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(listWalletCaseReportRevisions(CASE_ID, 0)).rejects.toThrow(/limit/);
    await expect(listWalletCaseReportRevisions(CASE_ID, 10, " cursor ")).rejects.toThrow(/cursor/);
    await expect(getWalletCaseReportRevision(CASE_ID, "rpt_bad")).rejects.toThrow(/revision ID/);
    await expect(compareWalletCaseReportRevisions(CASE_ID, "rpt_bad", `rpt_${"ab".repeat(32)}`)).rejects.toThrow(/revision ID/);
    expect(fetchMock).not.toHaveBeenCalled();

    const report = walletCaseReportFixture().report!;
    const revision = {
      public_id: report.public_id,
      content_hash_sha256: report.content_hash_sha256,
      case_public_id: CASE_ID,
      snapshot_public_id: SYNC_ID,
      assurance_level: report.assurance_level,
      captured_at: "2026-08-19T10:00:00Z",
      activity_digest_sha256: report.activity_revision.digest_sha256,
      evidence_digest_sha256: report.evidence_revision.digest_sha256,
      activity_count: report.activity_revision.aggregate.total_items,
      evidence_attempt_count: report.evidence_revision.total_attempts,
      canonical_eligible: false,
      limitation_count: report.limitations.length,
      unverified_claim_count: report.unverified_claims.length,
    };
    fetchMock.mockResolvedValue(jsonResponse({ case_public_id: CASE_ID, created: false, revision }, 201));
    await expect(captureWalletCaseReportRevision(CASE_ID, SYNC_ID)).rejects.toThrow(/does not match/);
  });
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}
