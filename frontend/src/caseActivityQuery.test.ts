import { describe, expect, it } from "vitest";

import {
  caseActivitySearch,
  DEFAULT_CASE_ACTIVITY_FILTERS,
  parseCaseActivitySearch,
  type CaseActivityUrlState,
} from "./caseActivityQuery";
import { ACTIVITY_ID, ASSET_ID } from "./test/walletCaseActivityFixtures";
import { SYNC_ID } from "./test/walletCaseFixtures";

describe("Case Activity URL state", () => {
  it("round-trips snapshot, repeated filters, sort and selected detail", () => {
    const state: CaseActivityUrlState = {
      snapshot: SYNC_ID,
      selectedActivityId: ACTIVITY_ID,
      filters: {
        ...DEFAULT_CASE_ACTIVITY_FILTERS,
        kinds: ["transaction", "swap"],
        directions: ["in"],
        outcomes: ["failed"],
        asset_id: ASSET_ID,
        protocol_id: "stonfi_v2",
        counterparty: `0:${"a".repeat(64)}`,
        data_origins: ["provider_observed"],
        sort: "oldest",
      },
    };
    expect(parseCaseActivitySearch(caseActivitySearch(state))).toEqual(state);
  });

  it("preserves a valid sub-millisecond filter interval", () => {
    const parsed = parseCaseActivitySearch(
      "?from_at=2026-08-01T00%3A00%3A00.000001Z&to_at=2026-08-01T00%3A00%3A00.000002Z",
    );
    expect(parsed.filters.from_at).toBe("2026-08-01T00:00:00.000001Z");
    expect(parsed.filters.to_at).toBe("2026-08-01T00:00:00.000002Z");
  });

  it.each([
    `-2147483648:${"a".repeat(64)}`,
    `2147483647:${"a".repeat(64)}`,
  ])("accepts canonical signed-int32 workchain boundary %s", (counterparty) => {
    const parsed = parseCaseActivitySearch(`?counterparty=${encodeURIComponent(counterparty)}`);
    expect(parsed.filters.counterparty).toBe(counterparty);
  });

  it("serializes repeatable filters in the backend canonical order", () => {
    const state: CaseActivityUrlState = {
      snapshot: SYNC_ID,
      selectedActivityId: null,
      filters: {
        ...DEFAULT_CASE_ACTIVITY_FILTERS,
        kinds: ["swap", "transaction"],
        directions: ["unknown", "in"],
        outcomes: ["unknown", "success"],
        data_origins: ["provider_observed", "demo_fixture"],
      },
    };
    const params = new URLSearchParams(caseActivitySearch(state));
    expect(params.getAll("kind")).toEqual(["transaction", "swap"]);
    expect(params.getAll("direction")).toEqual(["in", "unknown"]);
    expect(params.getAll("outcome")).toEqual(["success", "unknown"]);
    expect(params.getAll("data_origin")).toEqual(["demo_fixture", "provider_observed"]);
  });

  it.each([
    "?unknown=1",
    "?sort=newest&sort=oldest",
    "?activity=act_" + "1".repeat(64),
    "?snapshot=1",
    "?asset_id=TON",
    "?protocol_id=" + "x".repeat(33),
    "?protocol_id=made_up_dex",
    "?counterparty=short",
    `?counterparty=0:${"A".repeat(64)}`,
    `?counterparty=-0:${"a".repeat(64)}`,
    `?counterparty=2147483648:${"a".repeat(64)}`,
    `?counterparty=-2147483649:${"a".repeat(64)}`,
    "?from_at=2026-08-01T00%3A00%3A00Z",
    "?from_at=2026-08-01T00%3A00%3A00%2B01%3A00&to_at=2026-08-02T00%3A00%3A00%2B01%3A00",
    "?from_at=2026-02-30T00%3A00%3A00Z&to_at=2026-03-01T00%3A00%3A00Z",
    "?from_at=2026-08-01T24%3A00%3A00Z&to_at=2026-08-02T01%3A00%3A00Z",
    "?from_at=0000-01-01T00%3A00%3A00Z&to_at=0001-01-01T00%3A00%3A00Z",
    "?from_at=2026-08-01T00%3A00%3A00.0000001Z&to_at=2026-08-01T00%3A00%3A01Z",
    "?kind=transaction&kind=transaction",
  ])("rejects unsafe or ambiguous query %s", (search) => {
    expect(() => parseCaseActivitySearch(search)).toThrow();
  });
});
