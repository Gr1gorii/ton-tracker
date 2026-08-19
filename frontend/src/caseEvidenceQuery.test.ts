import { describe, expect, it } from "vitest";

import {
  caseEvidenceSearch,
  EMPTY_CASE_EVIDENCE_URL_STATE,
  parseCaseEvidenceSearch,
} from "./caseEvidenceQuery";

const SNAPSHOT = "550e8400-e29b-41d4-a716-446655440000";
const ACTIVITY = `act_${"a".repeat(64)}`;
const VERIFICATION = "f47ac10b-58cc-4372-a567-0e02b2c3d479";

describe("case Evidence URL state", () => {
  it("round-trips the pinned snapshot, Activity and verification in canonical order", () => {
    const state = { snapshot: SNAPSHOT, activity: ACTIVITY, verification: VERIFICATION };
    expect(caseEvidenceSearch(state)).toBe(
      `?snapshot=${SNAPSHOT}&activity=${ACTIVITY}&verification=${VERIFICATION}`,
    );
    expect(parseCaseEvidenceSearch(caseEvidenceSearch(state))).toEqual(state);
  });

  it("accepts the empty Evidence route", () => {
    expect(parseCaseEvidenceSearch("")).toEqual(EMPTY_CASE_EVIDENCE_URL_STATE);
  });

  it.each([
    "?unexpected=1",
    `?snapshot=${SNAPSHOT}&snapshot=${SNAPSHOT}`,
    "?snapshot=%20bad%20",
    `?activity=${ACTIVITY}`,
    `?snapshot=${SNAPSHOT}&activity=act_bad`,
    `?snapshot=${SNAPSHOT}&verification=${VERIFICATION}`,
  ])("fails closed for invalid Evidence URL state: %s", (search) => {
    expect(() => parseCaseEvidenceSearch(search)).toThrow();
  });

  it("refuses to serialize invalid public identifiers", () => {
    expect(() => caseEvidenceSearch({ snapshot: "1", activity: null, verification: null })).toThrow(/snapshot/);
    expect(() => caseEvidenceSearch({ snapshot: SNAPSHOT, activity: "act_1", verification: null })).toThrow(/Activity ID/);
    expect(() => caseEvidenceSearch({ snapshot: SNAPSHOT, activity: ACTIVITY, verification: "1" })).toThrow(/verification ID/);
  });
});
