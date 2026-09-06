// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { observedHistoryFloorFixture } from "../test/walletCaseStreamCheckpointFixtures";
import ObservedHistoryFloorPanel from "./ObservedHistoryFloorPanel";

afterEach(cleanup);

describe("ObservedHistoryFloorPanel", () => {
  it("shows page evidence and preserves the first-activity boundary", () => {
    const floor = observedHistoryFloorFixture();
    const { container } = render(
      <ObservedHistoryFloorPanel floor={floor} onExport={() => undefined} />,
    );

    expect(screen.getByRole("region", { name: "Observed history floor" })).toBeTruthy();
    expect(screen.getByText("observed")).toBeTruthy();
    expect(screen.getByText("Floors observed").closest("div")?.textContent).toContain("1/1");
    expect(screen.getByText("tonapi / transactions")).toBeTruthy();
    expect(screen.getByText(/Oldest successful page 2/)).toBeTruthy();
    expect(screen.getByText(/not proof of the wallet's first activity/)).toBeTruthy();
    expect(screen.getByText(floor.floor.input_progress_public_id)).toBeTruthy();
    expect(container.querySelector("time")?.getAttribute("datetime")).toBe(
      floor.floor.earliest_observed_timestamp,
    );
  });

  it("delegates export of the verified observed floor", () => {
    const onExport = vi.fn();
    render(
      <ObservedHistoryFloorPanel
        floor={observedHistoryFloorFixture()}
        onExport={onExport}
      />,
    );

    fireEvent.click(screen.getByRole("button", {
      name: "Export observed history floor JSON",
    }));
    expect(onExport).toHaveBeenCalledOnce();
  });
});
