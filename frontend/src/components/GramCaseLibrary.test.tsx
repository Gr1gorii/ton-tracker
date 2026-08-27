// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "../walletCaseApi";
import { DEFAULT_CASE_LIBRARY_QUERY } from "../caseRouting";
import { emptyWalletCaseFixture, walletCaseFixture } from "../test/walletCaseFixtures";
import GramCaseLibrary from "./GramCaseLibrary";

vi.mock("../walletCaseApi", () => ({
  listWalletCases: vi.fn(),
  restoreWalletCase: vi.fn(),
}));

const listMock = vi.mocked(api.listWalletCases);
const restoreMock = vi.mocked(api.restoreWalletCase);
const SECOND_CASE_ID = "550e8400-e29b-41d4-a716-446655440099";
const EMPTY_FILTERS = {
  query: null,
  network: null,
  data_environment: null,
} as const;

function renderLibrary(
  onOpenCase = vi.fn(),
  onCreateCase = vi.fn(),
) {
  function Harness() {
    const [catalogQuery, setCatalogQuery] = useState(DEFAULT_CASE_LIBRARY_QUERY);
    return (
      <GramCaseLibrary
        catalogQuery={catalogQuery}
        onCatalogQueryChange={setCatalogQuery}
        onOpenCase={onOpenCase}
        onCreateCase={onCreateCase}
      />
    );
  }
  return render(<Harness />);
}

beforeEach(() => {
  listMock.mockReset();
  restoreMock.mockReset();
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
      ...EMPTY_FILTERS,
      cases: [first, second], limit: 12, state: "active", truncated: false, next_cursor: null,
    });
    const onOpenCase = vi.fn();

    renderLibrary(onOpenCase);

    expect(await screen.findByRole("heading", { name: "Treasury" })).toBeTruthy();
    expect(screen.getByText("Monitor settlement flows.")).toBeTruthy();
    expect(screen.getByText("8 rows")).toBeTruthy();
    expect(screen.getByText("Not synchronized")).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "Open Case Treasury" }));
    expect(onOpenCase).toHaveBeenCalledWith(first.public_id);
    expect(listMock).toHaveBeenCalledWith({
      limit: 12,
      state: "active",
      query: null,
      network: null,
      dataEnvironment: null,
      cursor: null,
      signal: expect.any(AbortSignal),
    });
  });

  it("offers Case creation from a truthful empty state", async () => {
    listMock.mockResolvedValue({
      ...EMPTY_FILTERS,
      cases: [], limit: 12, state: "active", truncated: false, next_cursor: null,
    });
    const onCreateCase = vi.fn();
    renderLibrary(vi.fn(), onCreateCase);

    expect(await screen.findByRole("heading", { name: "No Wallet Cases yet" })).toBeTruthy();
    await userEvent.setup().click(screen.getByRole("button", { name: "Create your first Case" }));
    expect(onCreateCase).toHaveBeenCalledTimes(1);
  });

  it("retries an initial catalog failure without reloading the route", async () => {
    listMock
      .mockRejectedValueOnce(new Error("Local storage is starting."))
      .mockResolvedValueOnce({
        ...EMPTY_FILTERS,
        cases: [], limit: 12, state: "active", truncated: false, next_cursor: null,
      });
    renderLibrary();

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
        ...EMPTY_FILTERS,
        cases: [walletCase], limit: 12, state: "active", truncated: true, next_cursor: "page.two",
      })
      .mockImplementationOnce(async (request = {}) => {
        expansionSignal = request.signal;
        return {
          ...EMPTY_FILTERS,
          cases: [second], limit: 12, state: "active", truncated: false, next_cursor: null,
        };
      });
    const view = renderLibrary();

    await screen.findByRole("heading", { name: "Treasury" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Load more Cases" }));
    expect(await screen.findByRole("heading", { name: "Operations" })).toBeTruthy();
    expect(screen.getByText("2 Cases")).toBeTruthy();
    expect(screen.getByText("End of this Case catalog snapshot.")).toBeTruthy();
    expect(listMock.mock.calls[1]?.[0]).toMatchObject({
      limit: 12,
      state: "active",
      cursor: "page.two",
    });
    view.unmount();
    await waitFor(() => expect(expansionSignal?.aborted).toBe(true));
  });

  it("keeps loaded Cases when a continuation overlaps the current catalog", async () => {
    const walletCase = walletCaseFixture({ overrides: { label: "Treasury" } });
    listMock
      .mockResolvedValueOnce({
        ...EMPTY_FILTERS,
        cases: [walletCase], limit: 12, state: "active", truncated: true, next_cursor: "page.two",
      })
      .mockResolvedValueOnce({
        ...EMPTY_FILTERS,
        cases: [walletCase], limit: 12, state: "active", truncated: false, next_cursor: null,
      });
    renderLibrary();

    await screen.findByRole("heading", { name: "Treasury" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Load more Cases" }));

    expect((await screen.findByRole("alert")).textContent).toContain("overlaps");
    expect(screen.getByRole("heading", { name: "Treasury" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry loading more" })).toBeTruthy();
  });

  it("switches to the archived catalog and restores a retained Case", async () => {
    const active = walletCaseFixture({ overrides: { label: "Treasury" } });
    const archived = emptyWalletCaseFixture({
      public_id: SECOND_CASE_ID,
      canonical_wallet_key: `0:${"b".repeat(64)}`,
      display_address: "EQC-archived-wallet",
      label: "Cold storage",
      archived_at: "2026-08-27T12:00:00Z",
      updated_at: "2026-08-27T12:00:00Z",
    });
    listMock
      .mockResolvedValueOnce({
        ...EMPTY_FILTERS,
        cases: [active], limit: 12, state: "active", truncated: false, next_cursor: null,
      })
      .mockResolvedValueOnce({
        ...EMPTY_FILTERS,
        cases: [archived], limit: 12, state: "archived", truncated: false, next_cursor: null,
      })
      .mockResolvedValueOnce({
        ...EMPTY_FILTERS,
        cases: [], limit: 12, state: "archived", truncated: false, next_cursor: null,
      });
    restoreMock.mockResolvedValueOnce({ ...archived, archived_at: null });
    renderLibrary();

    await screen.findByRole("heading", { name: "Treasury" });
    await userEvent.setup().click(
      screen.getByRole("tab", { name: "Archived Cases" }),
    );
    expect(await screen.findByRole("heading", { name: "Cold storage" })).toBeTruthy();
    expect(screen.getByText(/Newest archives first/)).toBeTruthy();
    await userEvent.setup().click(
      screen.getByRole("button", { name: "Restore Case Cold storage" }),
    );

    expect(await screen.findByRole("heading", { name: "No archived Cases" })).toBeTruthy();
    expect(restoreMock).toHaveBeenCalledWith(
      archived.public_id,
      expect.any(AbortSignal),
    );
    expect(listMock.mock.calls.map((call) => call[0]?.state)).toEqual([
      "active",
      "archived",
      "archived",
    ]);
  });
});
