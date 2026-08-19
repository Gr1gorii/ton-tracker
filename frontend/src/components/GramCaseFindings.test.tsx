// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID, SYNC_ID, walletCaseFixture } from "../test/walletCaseFixtures";
import {
  unsynchronizedWalletCaseFindingsFixture,
  walletCaseFindingsFixture,
} from "../test/walletCaseFindingsFixtures";
import { ACTIVITY_ID } from "../test/walletCaseActivityFixtures";

const findingsHook = vi.hoisted(() => ({ useWalletCaseFindings: vi.fn() }));
vi.mock("../useWalletCaseFindings", () => findingsHook);

import GramCaseFindings from "./GramCaseFindings";

const reload = vi.fn();

function controller(response: ReturnType<typeof walletCaseFindingsFixture> | ReturnType<typeof unsynchronizedWalletCaseFindingsFixture>) {
  return { response, loading: false, error: null, reload };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", `/cases/${CASE_ID}/findings?snapshot=${SYNC_ID}`);
  findingsHook.useWalletCaseFindings.mockReturnValue(controller(walletCaseFindingsFixture()));
});

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

describe("GramCaseFindings", () => {
  it("renders explainable flows and opens an exact supporting Activity row", async () => {
    const onOpenActivity = vi.fn();
    const user = userEvent.setup();
    render(<GramCaseFindings walletCase={walletCaseFixture({ overrides: { data_environment: "live" } })} onOpenActivity={onOpenActivity} />);

    expect(screen.getByRole("heading", { name: "Quantities stay inside one canonical asset identity" })).toBeTruthy();
    expect(screen.getByText("12.5")).toBeTruthy();
    expect(screen.getByText("Failed transaction observations")).toBeTruthy();
    expect(screen.getByText(/do not establish ownership, illicit activity, safety/i)).toBeTruthy();
    expect(screen.queryByText(/risk score:/i)).toBeNull();

    const support = screen.getAllByRole("link").find((link) => link.getAttribute("href")?.includes(ACTIVITY_ID));
    expect(support).toBeTruthy();
    expect(support?.getAttribute("href")).toContain(`/cases/${CASE_ID}/activity?snapshot=${SYNC_ID}`);
    await user.click(support!);
    expect(onOpenActivity).toHaveBeenCalledWith(SYNC_ID, ACTIVITY_ID);
  });

  it("keeps an honest unsynchronized state and refreshes without inventing findings", async () => {
    findingsHook.useWalletCaseFindings.mockReturnValue(controller(unsynchronizedWalletCaseFindingsFixture()));
    const user = userEvent.setup();
    render(<GramCaseFindings walletCase={walletCaseFixture()} onOpenActivity={vi.fn()} />);

    expect(screen.getByRole("heading", { name: "No usable snapshot yet" })).toBeTruthy();
    expect(screen.queryByText("Failed transaction observations")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Refresh/ }));
    expect(reload).toHaveBeenCalledTimes(1);
  });

  it("fails case identity or evidence-environment drift closed", () => {
    const drift = structuredClone(walletCaseFindingsFixture());
    drift.findings!.subject.wallet_account_canonical = `0:${"b".repeat(64)}`;
    findingsHook.useWalletCaseFindings.mockReturnValue(controller(drift));
    render(<GramCaseFindings walletCase={walletCaseFixture({ overrides: { data_environment: "live" } })} onOpenActivity={vi.fn()} />);

    expect(screen.getByRole("alert").textContent).toContain("does not match the open case");
    expect(screen.queryByText("Failed transaction observations")).toBeNull();
  });

  it("fails a duplicated snapshot query closed and resets to the canonical Findings route", async () => {
    const invalid = `/cases/${CASE_ID}/findings?snapshot=${SYNC_ID}&snapshot=${SYNC_ID}`;
    window.history.replaceState({}, "", invalid);
    const user = userEvent.setup();
    render(<GramCaseFindings walletCase={walletCaseFixture()} onOpenActivity={vi.fn()} />);

    expect(screen.getByRole("alert").textContent).toContain("provided once");
    expect(findingsHook.useWalletCaseFindings).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    await user.click(screen.getByRole("button", { name: /Reset Findings view/ }));
    await waitFor(() => expect(`${window.location.pathname}${window.location.search}`).toBe(`/cases/${CASE_ID}/findings`));
  });
});
