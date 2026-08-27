import { describe, expect, it } from "vitest";
import { caseActivityPath, caseEvidencePath, caseFindingsPath, caseListPath, caseReportsPath, caseSummaryPath, DEFAULT_CASE_LIBRARY_QUERY, parseAppRoute } from "./caseRouting";

const CASE_ID = "550e8400-e29b-41d4-a716-446655440000";

describe("case routing", () => {
  it("round-trips the Wallet Case library route", () => {
    expect(caseListPath()).toBe("/cases");
    expect(parseAppRoute("/cases")).toEqual({
      kind: "case-list",
      catalog: DEFAULT_CASE_LIBRARY_QUERY,
    });
    expect(parseAppRoute("/cases/")).toEqual({
      kind: "case-list",
      catalog: DEFAULT_CASE_LIBRARY_QUERY,
    });
  });

  it("round-trips canonical Case library discovery state", () => {
    const catalog = {
      state: "archived" as const,
      query: "Treasury 100%",
      network: "ton-testnet" as const,
      dataEnvironment: "live" as const,
    };
    const path = caseListPath(catalog);
    expect(path).toBe(
      "/cases?state=archived&q=Treasury+100%25&network=ton-testnet&data_environment=live",
    );
    const url = new URL(path, "https://gram.scope");
    expect(parseAppRoute(url.pathname, url.search)).toEqual({
      kind: "case-list",
      catalog,
    });
  });

  it.each([
    "?q=",
    "?q=%20padded",
    "?state=deleted",
    "?network=ethereum",
    "?data_environment=staging",
    "?q=one&q=two",
    "?extra=value",
  ])("fails closed for ambiguous Case library search: %s", (search) => {
    expect(parseAppRoute("/cases", search)).toEqual({ kind: "not-found" });
  });

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

  it("round-trips a canonical case Reports route", () => {
    const path = caseReportsPath(CASE_ID);
    expect(path).toBe(`/cases/${CASE_ID}/reports`);
    expect(parseAppRoute(path)).toEqual({ kind: "case-reports", caseId: CASE_ID });
    expect(parseAppRoute(`${path}/`)).toEqual({ kind: "case-reports", caseId: CASE_ID });
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
    expect(() => caseReportsPath("1")).toThrow(/canonical UUIDv4/);
  });
});
