import { describe, expect, it } from "vitest";
import { caseActivityPath, caseEvidencePath, caseFindingsPath, caseSummaryPath, parseAppRoute } from "./caseRouting";

const CASE_ID = "550e8400-e29b-41d4-a716-446655440000";

describe("case routing", () => {
  it("round-trips a canonical case summary route", () => {
    const path = caseSummaryPath(CASE_ID);
    expect(path).toBe(`/cases/${CASE_ID}/summary`);
    expect(parseAppRoute(path)).toEqual({ kind: "case-summary", caseId: CASE_ID });
    expect(parseAppRoute(`${path}/`)).toEqual({ kind: "case-summary", caseId: CASE_ID });
  });

  it("round-trips a canonical case Activity route", () => {
    const path = caseActivityPath(CASE_ID);
    expect(path).toBe(`/cases/${CASE_ID}/activity`);
    expect(parseAppRoute(path)).toEqual({ kind: "case-activity", caseId: CASE_ID });
    expect(parseAppRoute(`${path}/`)).toEqual({ kind: "case-activity", caseId: CASE_ID });
  });

  it("round-trips a canonical case Evidence route", () => {
    const path = caseEvidencePath(CASE_ID);
    expect(path).toBe(`/cases/${CASE_ID}/evidence`);
    expect(parseAppRoute(path)).toEqual({ kind: "case-evidence", caseId: CASE_ID });
    expect(parseAppRoute(`${path}/`)).toEqual({ kind: "case-evidence", caseId: CASE_ID });
  });

  it("round-trips a canonical case Findings route", () => {
    const path = caseFindingsPath(CASE_ID);
    expect(path).toBe(`/cases/${CASE_ID}/findings`);
    expect(parseAppRoute(path)).toEqual({ kind: "case-findings", caseId: CASE_ID });
    expect(parseAppRoute(`${path}/`)).toEqual({ kind: "case-findings", caseId: CASE_ID });
  });

  it.each([
    "/cases/1/summary",
    "/cases/550e8400-e29b-11d4-a716-446655440000/summary",
    "/cases/550E8400-E29B-41D4-A716-446655440000/summary",
    "/cases/550e8400-e29b-41d4-a716-446655440000/activities",
    "/other",
  ])("fails closed for unsupported paths: %s", (path) => {
    expect(parseAppRoute(path)).toEqual({ kind: "not-found" });
  });

  it("rejects a non-canonical id when building a path", () => {
    expect(() => caseSummaryPath("1")).toThrow(/canonical UUIDv4/);
    expect(() => caseActivityPath("1")).toThrow(/canonical UUIDv4/);
    expect(() => caseEvidencePath("1")).toThrow(/canonical UUIDv4/);
    expect(() => caseFindingsPath("1")).toThrow(/canonical UUIDv4/);
  });
});
