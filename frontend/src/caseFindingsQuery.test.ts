import { describe, expect, it } from "vitest";

import { caseFindingsSearch, readCaseFindingsUrlState } from "./caseFindingsQuery";
import { SYNC_ID } from "./test/walletCaseFixtures";

describe("Case Findings URL state", () => {
  it("round-trips the pinned snapshot", () => {
    const search = caseFindingsSearch({ snapshot: SYNC_ID });
    expect(search).toBe(`?snapshot=${SYNC_ID}`);
    expect(readCaseFindingsUrlState(search)).toEqual({ state: { snapshot: SYNC_ID }, error: null });
  });

  it("keeps an unpinned latest request canonical", () => {
    expect(caseFindingsSearch({ snapshot: null })).toBe("");
    expect(readCaseFindingsUrlState("")).toEqual({ state: { snapshot: null }, error: null });
  });

  it("rejects duplicates, unknown keys and malformed UUIDs", () => {
    expect(readCaseFindingsUrlState(`?snapshot=${SYNC_ID}&snapshot=${SYNC_ID}`).error).toMatch(/once/);
    expect(readCaseFindingsUrlState("?run_id=1").error).toMatch(/only/);
    expect(readCaseFindingsUrlState("?snapshot=bad").error).toMatch(/UUIDv4/);
  });
});
