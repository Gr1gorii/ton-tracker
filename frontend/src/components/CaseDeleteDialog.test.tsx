// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID } from "../test/walletCaseFixtures";

const apiMocks = vi.hoisted(() => ({ deleteWalletCase: vi.fn() }));
vi.mock("../walletCaseApi", () => apiMocks);

import CaseDeleteDialog from "./CaseDeleteDialog";

const RECEIPT = {
  deleted: true as const,
  case_public_id: CASE_ID,
  audit_event_public_id: "550e8400-e29b-41d4-a716-446655440099",
  deleted_at: "2026-08-26T12:00:00Z",
  removed: {
    syncs: 2,
    ingestion_runs: 2,
    evidence_verifications: 1,
    report_revisions: 3,
  },
};

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.deleteWalletCase.mockResolvedValue(RECEIPT);
});
afterEach(() => cleanup());

describe("CaseDeleteDialog", () => {
  it("requires exact typed confirmation before permanent deletion", async () => {
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    render(
      <CaseDeleteDialog
        caseId={CASE_ID}
        caseName="Treasury"
        open
        onClose={vi.fn()}
        onDeleted={onDeleted}
      />,
    );

    expect(screen.getByRole("dialog").textContent).toContain("snapshots");
    expect(screen.getByRole("dialog").textContent).toContain("audit receipt");
    const input = screen.getByLabelText(/Type DELETE/);
    const submit = screen.getByRole("button", { name: "Delete Wallet Case" });
    expect(document.activeElement).toBe(input);
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.type(input, "delete");
    expect((submit as HTMLButtonElement).disabled).toBe(true);
    await user.clear(input);
    await user.type(input, "DELETE");
    expect((submit as HTMLButtonElement).disabled).toBe(false);
    await user.click(submit);

    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(RECEIPT));
    expect(apiMocks.deleteWalletCase).toHaveBeenCalledWith(
      CASE_ID,
      expect.any(AbortSignal),
    );
  });

  it("keeps the dialog open with a safe active-job conflict message", async () => {
    apiMocks.deleteWalletCase.mockRejectedValueOnce(
      new Error("Cancel or wait for active Wallet Case jobs before deleting this case."),
    );
    const user = userEvent.setup();
    render(
      <CaseDeleteDialog
        caseId={CASE_ID}
        caseName="Treasury"
        open
        onClose={vi.fn()}
        onDeleted={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText(/Type DELETE/), "DELETE");
    await user.click(screen.getByRole("button", { name: "Delete Wallet Case" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Cancel or wait for active Wallet Case jobs",
    );
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect((screen.getByRole("button", {
      name: "Delete Wallet Case",
    }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps an in-flight deletion stable across parent callback changes", async () => {
    let resolveDeletion!: (receipt: typeof RECEIPT) => void;
    apiMocks.deleteWalletCase.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveDeletion = resolve;
      }),
    );
    const user = userEvent.setup();
    const onDeleted = vi.fn();
    const rendered = render(
      <CaseDeleteDialog
        caseId={CASE_ID}
        caseName="Treasury"
        open
        onClose={vi.fn()}
        onDeleted={onDeleted}
      />,
    );

    await user.type(screen.getByLabelText(/Type DELETE/), "DELETE");
    await user.click(screen.getByRole("button", { name: "Delete Wallet Case" }));
    const signal = apiMocks.deleteWalletCase.mock.calls[0][1] as AbortSignal;

    rendered.rerender(
      <CaseDeleteDialog
        caseId={CASE_ID}
        caseName="Treasury"
        open
        onClose={vi.fn()}
        onDeleted={onDeleted}
      />,
    );

    expect(signal.aborted).toBe(false);
    expect((screen.getByLabelText(/Type DELETE/) as HTMLInputElement).value).toBe(
      "DELETE",
    );
    expect((screen.getByRole("button", {
      name: "Keep case",
    }) as HTMLButtonElement).disabled).toBe(true);

    resolveDeletion(RECEIPT);
    await waitFor(() => expect(onDeleted).toHaveBeenCalledWith(RECEIPT));
  });
});
