import { describe, expect, it } from "vitest";

import { parseWalletCaseReportResponse } from "./walletCaseReport";
import {
  unsynchronizedWalletCaseReportFixture,
  walletCaseReportFixture,
} from "./test/walletCaseReportFixtures";

describe("Wallet Case report parser", () => {
  it("accepts one exact content-addressed normalized report", () => {
    const parsed = parseWalletCaseReportResponse(walletCaseReportFixture());
    expect(parsed.report).toMatchObject({
      assurance_level: "normalized",
      activity_revision: { aggregate: { transactions: 1 } },
      evidence_revision: { selected_activity_count: 0 },
      truth_boundaries: { establishes_complete_wallet_history: false, used_by_pnl: false },
    });
    expect(parsed.report?.public_id).toBe(`rpt_${parsed.report?.content_hash_sha256}`);
  });

  it("accepts the honest unsynchronized envelope", () => {
    expect(parseWalletCaseReportResponse(unsynchronizedWalletCaseReportFixture()).report).toBeNull();
  });

  it.each([
    ["unknown field", (value: any) => { value.report.run_id = 7; }],
    ["case drift", (value: any) => { value.report.case_public_id = "550e8400-e29b-41d4-a716-446655440099"; }],
    ["snapshot drift", (value: any) => { value.report.snapshot.public_id = "550e8400-e29b-41d4-b716-446655440099"; }],
    ["coverage drift", (value: any) => { value.report.coverage = { ...value.report.coverage, state: "bounded_partial" }; }],
    ["content address", (value: any) => { value.report.content_hash_sha256 = "e".repeat(64); }],
    ["canonical bypass", (value: any) => { value.report.assurance_level = "canonical"; }],
    ["evidence prefix", (value: any) => { value.report.evidence_revision.locally_verified_activity_count = 1; }],
    ["truth inflation", (value: any) => { value.report.truth_boundaries.used_by_pnl = true; }],
    ["impossible date", (value: any) => { value.report.snapshot.completed_at = "2026-02-30T12:00:00Z"; }],
  ])("rejects %s", (_label, mutate) => {
    const value: any = structuredClone(walletCaseReportFixture());
    mutate(value);
    expect(() => parseWalletCaseReportResponse(value)).toThrow();
  });

  it("requires exactly one not_synchronized limitation when no report exists", () => {
    const value = structuredClone(unsynchronizedWalletCaseReportFixture());
    value.limitations = [];
    expect(() => parseWalletCaseReportResponse(value)).toThrow(/not_synchronized/);
  });
});
