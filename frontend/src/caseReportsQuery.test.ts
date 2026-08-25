import { describe, expect, it } from "vitest";

import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";
import { walletCaseReportFixture } from "./test/walletCaseReportFixtures";
import { caseReportsSearch, EMPTY_CASE_REPORTS_URL_STATE, readCaseReportsUrlState } from "./caseReportsQuery";

describe("Case Reports URL state", () => {
  it("round-trips canonical snapshot and report revision in stable order", () => {
    const revision = walletCaseReportFixture().report!.public_id;
    const search = caseReportsSearch({ snapshot: SYNC_ID, revision, baseline: revision });
    expect(search).toBe(`?snapshot=${SYNC_ID}&revision=${revision}&baseline=${revision}`);
    expect(readCaseReportsUrlState(search)).toEqual({ state: { snapshot: SYNC_ID, revision, baseline: revision }, error: null });
  });

  it("accepts empty and snapshot-only state", () => {
    expect(readCaseReportsUrlState("")).toEqual({ state: EMPTY_CASE_REPORTS_URL_STATE, error: null });
    expect(readCaseReportsUrlState(`?snapshot=${SYNC_ID}`).state).toEqual({ snapshot: SYNC_ID, revision: null, baseline: null });
  });

  it.each([
    `?case=${CASE_ID}`,
    `?snapshot=${SYNC_ID}&snapshot=${SYNC_ID}`,
    `?revision=rpt_${"ab".repeat(32)}`,
    `?snapshot=bad`,
    `?snapshot=${SYNC_ID}&revision=rpt_bad`,
    `?baseline=rpt_${"ab".repeat(32)}`,
    `?snapshot=${SYNC_ID}&revision=rpt_${"ab".repeat(32)}&baseline=rpt_bad`,
  ])("fails closed for %s", (search) => {
    expect(readCaseReportsUrlState(search).error).not.toBeNull();
  });

  it("rejects invalid state when serializing", () => {
    expect(() => caseReportsSearch({ snapshot: null, revision: `rpt_${"ab".repeat(32)}`, baseline: null })).toThrow(/requires/);
    expect(() => caseReportsSearch({ snapshot: "bad", revision: null, baseline: null })).toThrow(/UUIDv4/);
    expect(() => caseReportsSearch({ snapshot: SYNC_ID, revision: null, baseline: `rpt_${"ab".repeat(32)}` })).toThrow(/selected revision/);
  });
});
