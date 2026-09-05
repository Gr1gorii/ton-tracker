// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { backfillOutcomeHistoryFixture } from "../test/walletCaseStreamCheckpointFixtures";
import { buildWalletCaseBackfillCoverageTimeline } from "../walletCaseBackfillCoverageTimeline";
import BackfillCoverageTimeline from "./BackfillCoverageTimeline";

afterEach(cleanup);

function timeline(hasOlderOutcomes = false) {
  const history = backfillOutcomeHistoryFixture({
    hasMore: hasOlderOutcomes,
    totalOutcomes: hasOlderOutcomes ? 2 : 1,
  });
  return buildWalletCaseBackfillCoverageTimeline({
    casePublicId: history.case_public_id,
    syncCutoffPublicId: history.sync_cutoff_public_id,
    totalOutcomes: history.aggregate.total_outcomes,
    items: history.items,
    hasMore: history.page.has_more,
    limitations: history.limitations,
  });
}

describe("BackfillCoverageTimeline", () => {
  it("renders an accessible single-point coverage chart and exact metrics", () => {
    const { container } = render(<BackfillCoverageTimeline timeline={timeline()} />);

    expect(screen.getByRole("region", {
      name: "Backfill coverage timeline",
    })).toBeTruthy();
    expect(screen.getByRole("img", {
      name: /Continuation pages moved from 1 to 2 across 1 verified outcomes/,
    })).toBeTruthy();
    expect(screen.getByText("Complete frozen outcome set")).toBeTruthy();
    expect(screen.getByText("Verified page gain").nextElementSibling?.textContent).toBe("+1");
    expect(container.querySelector("polyline")?.getAttribute("points")).not.toContain("NaN");
    expect(container.querySelectorAll("circle")).toHaveLength(1);
  });

  it("labels an incomplete loaded window without claiming full history", () => {
    render(<BackfillCoverageTimeline timeline={timeline(true)} />);

    expect(screen.getByText("Loaded window · 1 of 2")).toBeTruthy();
    expect(screen.queryByText("Complete frozen outcome set")).toBeNull();
  });
});
