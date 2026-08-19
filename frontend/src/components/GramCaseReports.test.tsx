// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID, SYNC_ID, walletCaseFixture } from "../test/walletCaseFixtures";
import { walletCaseReportFixture } from "../test/walletCaseReportFixtures";
import {
  walletCaseReportRevisionCatalogFixture,
  walletCaseReportRevisionDetailFixture,
} from "../test/walletCaseReportRevisionFixtures";

const hook = vi.hoisted(() => ({ useWalletCaseReports: vi.fn() }));
vi.mock("../useWalletCaseReports", () => hook);

import GramCaseReports from "./GramCaseReports";

const capture = vi.fn();
const reloadCurrent = vi.fn();
const reloadCatalog = vi.fn();
const reloadDetail = vi.fn();
const loadMore = vi.fn();

function reportWalletCase() {
  return walletCaseFixture({
    overrides: {
      data_environment: "live",
      canonical_wallet_key: `0:${"1".repeat(64)}`,
    },
  });
}

function controller(selected: string | null) {
  return {
    current: walletCaseReportFixture(),
    currentLoading: false,
    currentError: null,
    reloadCurrent,
    catalog: walletCaseReportRevisionCatalogFixture(),
    catalogLoading: false,
    catalogError: null,
    reloadCatalog,
    loadMore,
    detail: selected ? walletCaseReportRevisionDetailFixture() : null,
    detailLoading: false,
    detailError: null,
    reloadDetail,
    capture,
    capturing: false,
    captureError: null,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", `/cases/${CASE_ID}/reports?snapshot=${SYNC_ID}`);
  hook.useWalletCaseReports.mockImplementation(({ urlState }: any) => controller(urlState.revision));
});
afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
});

describe("GramCaseReports", () => {
  it("shows the current truth boundary, saves explicitly, and deep-links a stored revision", async () => {
    const user = userEvent.setup();
    render(<GramCaseReports walletCase={reportWalletCase()} />);

    expect(screen.getByRole("heading", { name: "Report at the pinned snapshot" })).toBeTruthy();
    expect(screen.getByText(/does not establish complete wallet history/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /Export current JSON/ }).getAttribute("href")).toContain(`/report/export.json?snapshot=${SYNC_ID}`);
    await user.click(screen.getByRole("button", { name: /Save this revision/ }));
    expect(capture).toHaveBeenCalledTimes(1);

    const revision = walletCaseReportRevisionCatalogFixture().items[0];
    const link = screen.getByRole("link", { name: /Activity rows/ });
    await user.click(link);
    await waitFor(() => expect(window.location.search).toBe(`?snapshot=${SYNC_ID}&revision=${revision.public_id}`));
    const detailHeading = await screen.findByRole("heading", { name: "Exact stored public report" });
    await waitFor(() => expect(document.activeElement).toBe(detailHeading));
    expect(screen.getByRole("link", { name: /Export saved JSON/ }).getAttribute("href")).toContain(`/reports/${revision.public_id}/export.json`);

    await user.click(screen.getByRole("button", { name: "Close saved revision" }));
    await waitFor(() => expect(window.location.search).toBe(`?snapshot=${SYNC_ID}`));
    await waitFor(() => expect(document.activeElement).toBe(link));
  });

  it("fails an invalid URL closed without enabling requests and resets it", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/reports?revision=rpt_${"ab".repeat(32)}`);
    const user = userEvent.setup();
    render(<GramCaseReports walletCase={reportWalletCase()} />);
    expect(screen.getByRole("alert").textContent).toContain("requires its pinned snapshot");
    expect(hook.useWalletCaseReports).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
    await user.click(screen.getByRole("button", { name: /Reset Reports view/ }));
    expect(window.location.pathname).toBe(`/cases/${CASE_ID}/reports`);
    expect(window.location.search).toBe("");
  });

  it("renders honest empty states without inventing saved history", () => {
    hook.useWalletCaseReports.mockReturnValue({
      ...controller(null),
      current: { case_public_id: CASE_ID, snapshot_public_id: null, report: null, limitations: [{ code: "not_synchronized", message: "Synchronize first." }] },
      catalog: {
        ...walletCaseReportRevisionCatalogFixture(),
        revision_cutoff_public_id: null,
        items: [],
        aggregate: { total_revisions: 0, returned_count: 0 },
      },
    });
    render(<GramCaseReports walletCase={reportWalletCase()} />);
    expect(screen.getByText("No report is ready")).toBeTruthy();
    expect(screen.getByText("No saved revisions yet")).toBeTruthy();
    expect(screen.queryByRole("link", { name: /Export saved JSON/ })).toBeNull();
  });

  it("fails current report identity drift closed", () => {
    const drift = structuredClone(walletCaseReportFixture());
    drift.report!.subject.wallet_account_canonical = `0:${"b".repeat(64)}`;
    hook.useWalletCaseReports.mockReturnValue({ ...controller(null), current: drift });
    render(<GramCaseReports walletCase={reportWalletCase()} />);
    expect(screen.getByRole("alert").textContent).toContain("does not match the open Wallet Case");
    expect(screen.queryByRole("button", { name: /Save this revision/ })).toBeNull();
  });
});
