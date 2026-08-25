import { describe, expect, it } from "vitest";

import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";
import { walletCaseReportFixture } from "./test/walletCaseReportFixtures";
import { walletCaseReportRevisionComparisonFixture } from "./test/walletCaseReportRevisionFixtures";
import {
  parseWalletCaseReportRevisionCaptureResponse,
  parseWalletCaseReportRevisionCatalog,
  parseWalletCaseReportRevisionComparison,
  parseWalletCaseReportRevisionDetailResponse,
} from "./walletCaseReportRevisions";

const CAPTURED_AT = "2026-08-19T10:00:00.123456Z";

function summary() {
  const report = walletCaseReportFixture().report!;
  return {
    public_id: report.public_id,
    content_hash_sha256: report.content_hash_sha256,
    case_public_id: CASE_ID,
    snapshot_public_id: SYNC_ID,
    assurance_level: report.assurance_level,
    captured_at: CAPTURED_AT,
    activity_digest_sha256: report.activity_revision.digest_sha256,
    evidence_digest_sha256: report.evidence_revision.digest_sha256,
    activity_count: report.activity_revision.aggregate.total_items,
    evidence_attempt_count: report.evidence_revision.total_attempts,
    canonical_eligible: false,
    limitation_count: report.limitations.length,
    unverified_claim_count: report.unverified_claims.length,
  };
}

function catalog() {
  return {
    contract_version: "wallet_case_report_revision_catalog_v1",
    public_id: `rcat_${"ab".repeat(32)}`,
    case_public_id: CASE_ID,
    revision_cutoff_public_id: summary().public_id,
    items: [summary()],
    aggregate: { total_revisions: 1, returned_count: 1 },
    page: { limit: 10, has_more: false, next_cursor: null },
    limitations: [{ code: "report_revisions_are_explicit_captures", message: "Only explicit captures are retained." }],
  };
}

describe("Wallet Case report revision parser", () => {
  it("accepts a bound catalog, capture and exact detail", () => {
    expect(parseWalletCaseReportRevisionCatalog(catalog()).items[0]).toEqual(summary());
    expect(parseWalletCaseReportRevisionCaptureResponse({ case_public_id: CASE_ID, created: true, revision: summary() }).revision).toEqual(summary());
    expect(parseWalletCaseReportRevisionDetailResponse({ case_public_id: CASE_ID, revision: summary(), report: walletCaseReportFixture() }).report).toEqual(walletCaseReportFixture());
  });

  it("accepts an honest empty catalog", () => {
    const value = catalog();
    value.revision_cutoff_public_id = null as unknown as string;
    value.items = [];
    value.aggregate = { total_revisions: 0, returned_count: 0 };
    expect(parseWalletCaseReportRevisionCatalog(value).items).toEqual([]);
  });

  it.each([
    ["extra field", (value: any) => { value.run_id = 1; }],
    ["content address", (value: any) => { value.items[0].content_hash_sha256 = "cd".repeat(32); }],
    ["scope drift", (value: any) => { value.items[0].case_public_id = "550e8400-e29b-41d4-a716-446655440099"; }],
    ["impossible date", (value: any) => { value.items[0].captured_at = "2026-02-30T00:00:00Z"; }],
    ["cursor mismatch", (value: any) => { value.page.has_more = true; }],
    ["missing capture limitation", (value: any) => { value.limitations = []; }],
    ["unexpected cursor limitation", (value: any) => { value.limitations.push({ code: "report_revision_cursor_local_process_scope", message: "Local cursor." }); }],
    ["returned total overflow", (value: any) => { value.aggregate.total_revisions = 0; }],
  ])("rejects %s", (_label, mutate) => {
    const value: any = structuredClone(catalog());
    mutate(value);
    expect(() => parseWalletCaseReportRevisionCatalog(value)).toThrow();
  });

  it.each([
    ["Activity digest", (value: any) => { value.revision.activity_digest_sha256 = "ef".repeat(32); }],
    ["snapshot", (value: any) => { value.revision.snapshot_public_id = "550e8400-e29b-41d4-a716-446655440099"; }],
    ["Activity count", (value: any) => { value.revision.activity_count += 1; }],
    ["Evidence attempt count", (value: any) => { value.revision.evidence_attempt_count += 1; }],
    ["canonical gate", (value: any) => { value.revision.canonical_eligible = true; value.revision.assurance_level = "canonical"; }],
    ["limitation count", (value: any) => { value.revision.limitation_count += 1; }],
    ["unverified claim count", (value: any) => { value.revision.unverified_claim_count += 1; }],
  ])("rejects detail %s drift", (_label, mutate) => {
    const value: any = { case_public_id: CASE_ID, revision: summary(), report: walletCaseReportFixture() };
    mutate(value);
    expect(() => parseWalletCaseReportRevisionDetailResponse(value)).toThrow(/inconsistent/);
  });

  it("accepts a strict comparison of the same stored revision", () => {
    const value = walletCaseReportRevisionComparisonFixture();
    expect(parseWalletCaseReportRevisionComparison(value)).toEqual(value);
  });

  it.each([
    ["extra field", (value: any) => { value.run_id = 1; }],
    ["case scope", (value: any) => { value.target.case_public_id = "550e8400-e29b-41d4-a716-446655440099"; }],
    ["content state", (value: any) => { value.content_changed = true; }],
    ["Activity delta", (value: any) => { value.activity.total_items.delta = 1; }],
    ["Evidence summary", (value: any) => { value.evidence.total_attempts.target += 1; value.evidence.total_attempts.delta += 1; }],
    ["gate overlap", (value: any) => { value.canonical_gate.newly_unmet = ["activity_required"]; value.canonical_gate.resolved = ["activity_required"]; }],
    ["limitation order", (value: any) => { value.comparison_limitations.reverse(); }],
    ["truth boundary", (value: any) => { value.truth_boundaries_changed = true; }],
  ])("rejects comparison %s drift", (_label, mutate) => {
    const value: any = structuredClone(walletCaseReportRevisionComparisonFixture());
    mutate(value);
    expect(() => parseWalletCaseReportRevisionComparison(value)).toThrow();
  });
});
