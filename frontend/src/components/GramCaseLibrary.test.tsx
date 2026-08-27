// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../walletCaseApi";
import { emptyWalletCaseFixture, walletCaseFixture } from "../test/walletCaseFixtures";
import GramCaseLibrary from "./GramCaseLibrary";

vi.mock("../walletCaseApi", () => ({ listWalletCases: vi.fn() }));

const listMock = vi.mocked(api.listWalletCases);
const SECOND_CASE_ID = "550e8400-e29b-41d4-a716-446655440099";

beforeEach(() => {
  listMock.mockReset();
});

afterEach(cleanup);

describe("GramCaseLibrary", () => {
  it("renders bounded Case summaries and opens the selected canonical Case", async () => {
    const first = walletCaseFixture({
      overrides: { label: "Treasury", note: "Monitor settlement flows." },
    });
    const second = emptyWalletCaseFixture({
      public_id: SECOND_CASE_ID,
      canonical_wallet_key: `0:${"b".repeat(64)}`,
      display_address: "EQC-second-wallet",
      updated_at: "2026-08-08T10:00:00Z",
    });
    listMock.mockResolvedValue({
      cases: [first, second], limit: 12, state: "active", truncated: false, next_cursor: null,
    });
    const onOpenCase = vi.fn();

    render(<GramCaseLibrary onOpenCase={onOpenCase} onCreateCase={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Treasury" })).toBeTruthy();
    expect(screen.getByText("Monitor settlement flows.")).toBeTruthy();
    expect(screen.getByText("8 rows")).toBeTruthy();
    expect(screen.getByText("Not synchronized")).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "Open Case Treasury" }));
    expect(onOpenCase).toHaveBeenCalledWith(first.public_id);
    expect(listMock).toHaveBeenCalledWith(12, "active", null, expect.any(AbortSignal));
  });

  it("offers Case creation from a truthful empty state", async () => {
    listMock.mockResolvedValue({
      cases: [], limit: 12, state: "active", truncated: false, next_cursor: null,
    });
    const onCreateCase = vi.fn();
    render(<GramCaseLibrary onOpenCase={vi.fn()} onCreateCase={onCreateCase} />);

    expect(await screen.findByRole("heading", { name: "No Wallet Cases yet" })).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "Create your first Case" }));
    expect(onCreateCase).toHaveBeenCalledTimes(1);
  });

  it("retries an initial catalog failure without reloading the route", async () => {
    listMock
      .mockRejectedValueOnce(new Error("Local storage is starting."))
      .mockResolvedValueOnce({
        cases: [], limit: 12, state: "active", truncated: false, next_cursor: null,
      });
    render(<GramCaseLibrary onOpenCase={vi.fn()} onCreateCase={vi.fn()} />);

    expect((await screen.findByRole("alert")).textContent).toContain("Local storage is starting.");
    await userEvent.setup().click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "No Wallet Cases yet" })).toBeTruthy();
    expect(listMock).toHaveBeenCalledTimes(2);
  });

  it("appends a signed continuation and aborts the active request on unmount", async () => {
    const walletCase = walletCaseFixture({ overrides: { label: "Treasury" } });
    const second = emptyWalletCaseFixture({
      public_id: SECOND_CASE_ID,
      canonical_wallet_key: `0:${"b".repeat(64)}`,
      display_address: "EQC-second-wallet",
      label: "Operations",
    });
    let expansionSignal: AbortSignal | undefined;
    listMock
      .mockResolvedValueOnce({
        cases: [walletCase], limit: 12, state: "active", truncated: true, next_cursor: "page.two",
      })
      .mockImplementationOnce(async (_limit, _state, _cursor, signal) => {
        expansionSignal = signal;
        return {
          cases: [second], limit: 12, state: "active", truncated: false, next_cursor: null,
        };
      });
    const view = render(<GramCaseLibrary onOpenCase={vi.fn()} onCreateCase={vi.fn()} />);

    await screen.findByRole("heading", { name: "Treasury" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Load more Cases" }));
    expect(await screen.findByRole("heading", { name: "Operations" })).toBeTruthy();
    expect(screen.getByText("2 Cases")).toBeTruthy();
    expect(screen.getByText("End of this Case catalog snapshot.")).toBeTruthy();
    expect(listMock.mock.calls[1]?.[0]).toBe(12);
    expect(listMock.mock.calls[1]?.[1]).toBe("active");
    expect(listMock.mock.calls[1]?.[2]).toBe("page.two");
    view.unmount();
    await waitFor(() => expect(expansionSignal?.aborted).toBe(true));
  });

  it("keeps loaded Cases when a continuation overlaps the current catalog", async () => {
    const walletCase = walletCaseFixture({ overrides: { label: "Treasury" } });
    listMock
      .mockResolvedValueOnce({
        cases: [walletCase], limit: 12, state: "active", truncated: true, next_cursor: "page.two",
      })
      .mockResolvedValueOnce({
        cases: [walletCase], limit: 12, state: "active", truncated: false, next_cursor: null,
      });
    render(<GramCaseLibrary onOpenCase={vi.fn()} onCreateCase={vi.fn()} />);

    await screen.findByRole("heading", { name: "Treasury" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Load more Cases" }));

    expect((await screen.findByRole("alert")).textContent).toContain("overlaps");
    expect(screen.getByRole("heading", { name: "Treasury" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry loading more" })).toBeTruthy();
  });
});
