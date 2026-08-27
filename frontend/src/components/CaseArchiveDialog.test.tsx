// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID, emptyWalletCaseFixture } from "../test/walletCaseFixtures";

const apiMocks = vi.hoisted(() => ({ archiveWalletCase: vi.fn() }));
vi.mock("../walletCaseApi", () => apiMocks);

import CaseArchiveDialog from "./CaseArchiveDialog";

const ARCHIVED = emptyWalletCaseFixture({
  archived_at: "2026-08-27T12:00:00Z",
  updated_at: "2026-08-27T12:00:00Z",
});

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.archiveWalletCase.mockResolvedValue(ARCHIVED);
});
afterEach(cleanup);

describe("CaseArchiveDialog", () => {
  it("explains the reversible boundary and archives the Case", async () => {
    const onArchived = vi.fn();
    render(
      <CaseArchiveDialog
        caseId={CASE_ID}
        caseName="Treasury"
        open
        onClose={vi.fn()}
        onArchived={onArchived}
      />,
    );

    const dialog = screen.getByRole("dialog", { name: "Archive Wallet Case?" });
    expect(dialog.textContent).toContain("stay intact");
    expect(dialog.textContent).toContain("restore");
    const submit = screen.getByRole("button", { name: "Archive Wallet Case" });
    expect(document.activeElement).toBe(submit);
    await userEvent.setup().click(submit);

    await waitFor(() => expect(onArchived).toHaveBeenCalledWith(ARCHIVED));
    expect(apiMocks.archiveWalletCase).toHaveBeenCalledWith(
      CASE_ID,
      expect.any(AbortSignal),
    );
  });

  it("keeps the dialog open when active work blocks archival", async () => {
    apiMocks.archiveWalletCase.mockRejectedValueOnce(
      new Error("Cancel or wait for active Wallet Case jobs before archiving this case."),
    );
    render(
      <CaseArchiveDialog
        caseId={CASE_ID}
        caseName="Treasury"
        open
        onClose={vi.fn()}
        onArchived={vi.fn()}
      />,
    );

    await userEvent.setup().click(
      screen.getByRole("button", { name: "Archive Wallet Case" }),
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Cancel or wait for active Wallet Case jobs",
    );
    expect(screen.getByRole("dialog", { name: "Archive Wallet Case?" })).toBeTruthy();
  });
});
