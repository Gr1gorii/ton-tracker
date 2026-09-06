// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  earliestActivityAnchorFixture,
  verifiedEarliestActivityAnchorFixture,
} from "../test/walletCaseStreamCheckpointFixtures";
import EarliestActivityAnchorPanel from "./EarliestActivityAnchorPanel";

afterEach(cleanup);

describe("EarliestActivityAnchorPanel", () => {
  it("shows the live canonical proof and zero predecessor", () => {
    const anchor = verifiedEarliestActivityAnchorFixture();
    render(<EarliestActivityAnchorPanel anchor={anchor} onExport={() => undefined} />);

    expect(screen.getByRole("region", { name: "Earliest activity anchor" })).toBeTruthy();
    expect(screen.getByText("Verified")).toBeTruthy();
    expect(screen.getByText(/anchored to canonical chain evidence/)).toBeTruthy();
    expect(screen.getByText("Canonical inclusion and zero predecessor verified")).toBeTruthy();
    expect(screen.getByText("Previous logical time: 0")).toBeTruthy();
    expect(screen.getByText(anchor.document.candidate!.activity_public_id)).toBeTruthy();
    expect(screen.getByText(anchor.document.proof!.evidence_public_id)).toBeTruthy();
    expect(screen.getByText(anchor.anchor.input_floor_public_id)).toBeTruthy();
  });

  it("keeps demo data ineligible and delegates export", () => {
    const onExport = vi.fn();
    render(
      <EarliestActivityAnchorPanel
        anchor={earliestActivityAnchorFixture()}
        onExport={onExport}
      />,
    );

    expect(screen.getByText("Ineligible")).toBeTruthy();
    expect(screen.getByText(/outside a live data environment/)).toBeTruthy();
    expect(screen.queryByText(/zero predecessor verified/)).toBeNull();
    fireEvent.click(screen.getByRole("button", {
      name: "Export earliest activity anchor JSON",
    }));
    expect(onExport).toHaveBeenCalledOnce();
  });
});
