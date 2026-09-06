// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { completeHistoryGateFixture } from "../test/walletCaseStreamCheckpointFixtures";
import CompleteHistoryGatePanel from "./CompleteHistoryGatePanel";

afterEach(cleanup);

describe("CompleteHistoryGatePanel", () => {
  it("shows the locked verdict, every prerequisite, and provenance", () => {
    const gate = completeHistoryGateFixture();
    render(<CompleteHistoryGatePanel gate={gate} onExport={() => undefined} />);

    expect(screen.getByRole("region", { name: "Complete-history gate" })).toBeTruthy();
    expect(screen.getByText("Locked")).toBeTruthy();
    expect(screen.getByText("Complete wallet history is not established.")).toBeTruthy();
    expect(screen.getByText("1/6")).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(6);
    expect(screen.getByText("earliest activity anchor verified")).toBeTruthy();
    expect(screen.getByText(gate.gate.input_progress_public_id)).toBeTruthy();
  });

  it("delegates export of the verified gate", () => {
    const onExport = vi.fn();
    render(
      <CompleteHistoryGatePanel
        gate={completeHistoryGateFixture()}
        onExport={onExport}
      />,
    );

    fireEvent.click(screen.getByRole("button", {
      name: "Export complete-history gate JSON",
    }));
    expect(onExport).toHaveBeenCalledOnce();
  });
});
