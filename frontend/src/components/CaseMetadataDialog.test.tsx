// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { walletCaseFixture } from "../test/walletCaseFixtures";

const apiMocks = vi.hoisted(() => {
  class WalletCaseApiError extends Error {
    code: string | null;

    constructor(message: string, code: string | null = null) {
      super(message);
      this.code = code;
    }
  }
  return {
    WalletCaseApiError,
    updateWalletCaseMetadata: vi.fn(),
  };
});
vi.mock("../walletCaseApi", () => apiMocks);

import CaseMetadataDialog from "./CaseMetadataDialog";

const CURRENT = walletCaseFixture({
  overrides: {
    label: "Treasury",
    note: "Initial note",
    metadata_version: 4,
  },
});
const UPDATED = walletCaseFixture({
  overrides: {
    label: "Investigation",
    note: "Evidence requested.",
    metadata_version: 5,
    updated_at: "2026-08-26T18:30:00Z",
  },
});

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.updateWalletCaseMetadata.mockResolvedValue(UPDATED);
});
afterEach(() => cleanup());

describe("CaseMetadataDialog", () => {
  it("saves a canonical versioned draft and returns the bound Case", async () => {
    const user = userEvent.setup();
    const onUpdated = vi.fn();
    render(
      <CaseMetadataDialog
        walletCase={CURRENT}
        open
        onClose={vi.fn()}
        onUpdated={onUpdated}
      />,
    );

    const label = screen.getByLabelText("Label");
    const note = screen.getByLabelText("Note");
    const save = screen.getByRole("button", { name: "Save details" });
    expect(document.activeElement).toBe(label);
    expect((save as HTMLButtonElement).disabled).toBe(true);
    await user.clear(label);
    await user.type(label, "  Investigation  ");
    await user.clear(note);
    await user.type(note, "  Evidence requested.  ");
    await user.click(save);

    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(UPDATED));
    expect(apiMocks.updateWalletCaseMetadata).toHaveBeenCalledWith(
      CURRENT,
      {
        expected_metadata_version: 4,
        label: "Investigation",
        note: "Evidence requested.",
      },
      expect.any(AbortSignal),
    );
  });

  it("preserves the draft and explains a stale editor conflict", async () => {
    apiMocks.updateWalletCaseMetadata.mockRejectedValueOnce(
      new apiMocks.WalletCaseApiError(
        "Wallet Case metadata changed.",
        "case_metadata_changed",
      ),
    );
    const user = userEvent.setup();
    render(
      <CaseMetadataDialog
        walletCase={CURRENT}
        open
        onClose={vi.fn()}
        onUpdated={vi.fn()}
      />,
    );

    const label = screen.getByLabelText("Label");
    await user.clear(label);
    await user.type(label, "Local draft");
    await user.click(screen.getByRole("button", { name: "Save details" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "changed in another tab",
    );
    expect((label as HTMLInputElement).value).toBe("Local draft");
    expect((screen.getByRole("button", {
      name: "Save details",
    }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("does not abort an in-flight save when parent callbacks change", async () => {
    let resolveUpdate!: (value: typeof UPDATED) => void;
    apiMocks.updateWalletCaseMetadata.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUpdate = resolve;
      }),
    );
    const user = userEvent.setup();
    const onUpdated = vi.fn();
    const rendered = render(
      <CaseMetadataDialog
        walletCase={CURRENT}
        open
        onClose={vi.fn()}
        onUpdated={onUpdated}
      />,
    );
    await user.clear(screen.getByLabelText("Label"));
    await user.type(screen.getByLabelText("Label"), "Investigation");
    await user.click(screen.getByRole("button", { name: "Save details" }));
    const signal = apiMocks.updateWalletCaseMetadata.mock.calls[0][2] as AbortSignal;

    rendered.rerender(
      <CaseMetadataDialog
        walletCase={CURRENT}
        open
        onClose={vi.fn()}
        onUpdated={onUpdated}
      />,
    );
    expect(signal.aborted).toBe(false);
    expect((screen.getByRole("button", {
      name: "Saving…",
    }) as HTMLButtonElement).disabled).toBe(true);

    resolveUpdate(UPDATED);
    await waitFor(() => expect(onUpdated).toHaveBeenCalledWith(UPDATED));
  });
});
