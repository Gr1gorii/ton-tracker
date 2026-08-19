// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  ACTIVITY_ID,
  ASSET_ID,
  activityDetailFixture,
  activityItemFixture,
  activityResponseFixture,
} from "../test/walletCaseActivityFixtures";
import { CASE_ID, SYNC_ID, walletCaseFixture } from "../test/walletCaseFixtures";
import { liveEvidenceActivityDetailFixture } from "../test/walletCaseEvidenceFixtures";

const apiMocks = vi.hoisted(() => ({
  getWalletCaseActivity: vi.fn(),
  getWalletCaseActivityDetail: vi.fn(),
}));

vi.mock("../walletCaseApi", () => apiMocks);

import GramCaseActivity from "./GramCaseActivity";

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getWalletCaseActivity.mockResolvedValue(activityResponseFixture());
  apiMocks.getWalletCaseActivityDetail.mockResolvedValue(activityDetailFixture());
  window.history.replaceState({}, "", `/cases/${CASE_ID}/activity`);
});

afterEach(() => {
  cleanup();
  document.body.style.overflow = "";
  window.history.replaceState({}, "", "/");
});

describe("GramCaseActivity", () => {
  it("fails an invalid Activity URL closed without fetching or rewriting it", async () => {
    const invalidPath = `/cases/${CASE_ID}/activity?asset_id=TON`;
    window.history.replaceState({}, "", invalidPath);
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);

    expect((await screen.findByRole("alert")).textContent).toContain("Activity asset filter must use a server asset id");
    expect(apiMocks.getWalletCaseActivity).not.toHaveBeenCalled();
    expect(apiMocks.getWalletCaseActivityDetail).not.toHaveBeenCalled();
    expect(`${window.location.pathname}${window.location.search}`).toBe(invalidPath);
  });

  it("pins the latest usable snapshot in URL and React query state before refresh", async () => {
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "1 Activity rows" })).toBeTruthy();
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("snapshot")).toBe(SYNC_ID));
    await waitFor(() => expect(apiMocks.getWalletCaseActivity).toHaveBeenCalledTimes(2));
    expect(apiMocks.getWalletCaseActivity.mock.calls[0][1].snapshot).toBeNull();
    expect(apiMocks.getWalletCaseActivity.mock.calls[1][1].snapshot).toBe(SYNC_ID);
    expect(screen.getByText("Demo fixture · not evidence")).toBeTruthy();
    expect(screen.getByRole("note").textContent).toContain("Summary remains based on the latest usable sync only");

    await user.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => expect(apiMocks.getWalletCaseActivity).toHaveBeenCalledTimes(3));
    expect(apiMocks.getWalletCaseActivity.mock.calls[2][1].snapshot).toBe(SYNC_ID);
  });

  it("restores server-only asset filters in the URL and request without accepting a symbol", async () => {
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);
    await screen.findByRole("heading", { name: "1 Activity rows" });

    await user.click(screen.getByRole("button", { name: "Filters" }));
    const asset = screen.getByLabelText(/Server asset ID/);
    await user.type(asset, ASSET_ID);
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => expect(new URLSearchParams(window.location.search).get("asset_id")).toBe(ASSET_ID));
    await waitFor(() => {
      const calls = apiMocks.getWalletCaseActivity.mock.calls;
      expect(calls[calls.length - 1]?.[1]).toMatchObject({ snapshot: SYNC_ID, asset_id: ASSET_ID });
    });
    expect(window.location.search).not.toContain("symbol=");

    window.history.back();
    await waitFor(() => expect(new URLSearchParams(window.location.search).has("asset_id")).toBe(false));
    await waitFor(() => {
      const calls = apiMocks.getWalletCaseActivity.mock.calls;
      expect(calls[calls.length - 1]?.[1].asset_id).toBeNull();
    });
    window.history.forward();
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("asset_id")).toBe(ASSET_ID));
    await waitFor(() => {
      const calls = apiMocks.getWalletCaseActivity.mock.calls;
      expect(calls[calls.length - 1]?.[1].asset_id).toBe(ASSET_ID);
    });
  });

  it("qualifies an unavailable reported TON symbol and exposes its missing identity fields", async () => {
    const item = activityItemFixture({
      kind: "transfer",
      direction: "in",
      outcome: null,
      assets: [{
        role: "asset",
        asset_id: null,
        identity_status: "unavailable",
        network: "ton-mainnet",
        standard: "unknown",
        contract_address: null,
        symbol: "TON",
      }],
      details: { kind: "transfer", amount: "12" },
    });
    apiMocks.getWalletCaseActivity.mockResolvedValue(activityResponseFixture({
      aggregate: {
        total_items: 1,
        transactions: 0,
        transfers: 1,
        swaps: 0,
        failed_transactions: 0,
        source_sync_count: 1,
        suppressed_duplicate_observations: 0,
        conflicted_identity_count: 0,
      },
      items: [item],
    }));
    apiMocks.getWalletCaseActivityDetail.mockResolvedValue({
      ...activityDetailFixture(),
      item,
    });
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);

    expect(await screen.findByText("12 reported as TON · identity unavailable")).toBeTruthy();
    expect(screen.queryByText("12 TON")).toBeNull();
    await user.click(screen.getByRole("link", { name: "Open Transfer Activity detail" }));

    const identity = await screen.findByRole("region", { name: "Asset identity" });
    expect(identity.textContent).toContain("Reported as TON");
    expect(identity.textContent).toContain("Roleasset");
    expect(identity.textContent).toContain("Identity statusunavailable");
    expect(identity.textContent).toContain("Standardunknown");
    expect(identity.textContent).toContain("Server asset IDNot available");
    expect(identity.textContent).toContain("Canonical contractNot available");
  });

  it("canonicalizes checkbox filters after uncheck and recheck before the immediate request", async () => {
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);
    await screen.findByRole("heading", { name: "1 Activity rows" });
    await user.click(screen.getByRole("button", { name: "Filters" }));

    for (const [first, second] of [
      ["Transaction", "Transfer"],
      ["Incoming", "Outgoing"],
      ["success", "failed"],
      ["Demo fixture", "Provider observed"],
    ]) {
      const firstCheckbox = screen.getByLabelText(first, { exact: true });
      await user.click(firstCheckbox);
      await user.click(screen.getByLabelText(second, { exact: true }));
      await user.click(firstCheckbox);
      await user.click(firstCheckbox);
    }
    await user.click(screen.getByRole("button", { name: "Apply filters" }));

    await waitFor(() => {
      const params = new URLSearchParams(window.location.search);
      expect(params.getAll("kind")).toEqual(["transaction", "transfer"]);
      expect(params.getAll("direction")).toEqual(["in", "out"]);
      expect(params.getAll("outcome")).toEqual(["success", "failed"]);
      expect(params.getAll("data_origin")).toEqual(["demo_fixture", "provider_observed"]);
    });
    await waitFor(() => {
      const calls = apiMocks.getWalletCaseActivity.mock.calls;
      expect(calls[calls.length - 1]?.[1]).toMatchObject({
        kinds: ["transaction", "transfer"],
        directions: ["in", "out"],
        outcomes: ["success", "failed"],
        data_origins: ["demo_fixture", "provider_observed"],
      });
    });
  });

  it("contains keyboard focus in detail and returns it to the row after browser Back", async () => {
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);
    const row = await screen.findByRole("link", { name: "Open Transaction Activity detail" });
    row.focus();
    await user.click(row);

    const dialog = await screen.findByRole("dialog", { name: "Activity detail" });
    const close = screen.getByRole("button", { name: "Close Activity detail" });
    await waitFor(() => expect(document.activeElement).toBe(close));
    expect(dialog.contains(document.activeElement)).toBe(true);
    const background = row.closest("body > div");
    expect(background?.getAttribute("inert")).toBe("");
    expect(background?.getAttribute("aria-hidden")).toBe("true");
    await user.tab();
    expect(document.activeElement).toBe(close);
    await user.tab({ shift: true });
    expect(document.activeElement).toBe(close);

    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(row));
    expect(background?.hasAttribute("inert")).toBe(false);
  });

  it("closes a refreshed detail deep link in place and focuses the Activity heading", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/activity?snapshot=${SYNC_ID}&sort=newest&activity=${ACTIVITY_ID}`);
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);

    await screen.findByRole("dialog", { name: "Activity detail" });
    await user.click(screen.getByRole("button", { name: "Close Activity detail" }));

    const heading = screen.getByRole("heading", { name: "Observed rows, without evidence inflation" });
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(new URLSearchParams(window.location.search).has("activity")).toBe(false);
    expect(new URLSearchParams(window.location.search).get("snapshot")).toBe(SYNC_ID);
  });

  it("navigates an eligible live transaction to Evidence without running proof work in the dialog", async () => {
    const liveDetail = liveEvidenceActivityDetailFixture();
    apiMocks.getWalletCaseActivity.mockResolvedValue(activityResponseFixture({
      snapshot: {
        ...activityResponseFixture().snapshot!,
        data_mode: "real",
        provider: "tonapi_wallet_activity_live",
      },
      items: [liveDetail.item],
    }));
    apiMocks.getWalletCaseActivityDetail.mockResolvedValue(liveDetail);
    const onVerifyEvidence = vi.fn();
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={onVerifyEvidence} />);

    await user.click(await screen.findByRole("link", { name: "Open Transaction Activity detail" }));
    const action = await screen.findByRole("button", { name: "Check verification availability" });
    expect(screen.getByRole("heading", { name: "Eligible for evidence verification" })).toBeTruthy();
    expect(screen.getByText(/Availability is checked on the Evidence page/)).toBeTruthy();
    await user.click(action);

    expect(onVerifyEvidence).toHaveBeenCalledWith(SYNC_ID, ACTIVITY_ID);
    expect(apiMocks.getWalletCaseActivityDetail).toHaveBeenCalledTimes(1);
  });

  it("keeps demo detail explicitly ineligible and exposes no Verify link", async () => {
    const user = userEvent.setup();
    render(<GramCaseActivity walletCase={walletCaseFixture()} onVerifyEvidence={vi.fn()} />);

    await user.click(await screen.findByRole("link", { name: "Open Transaction Activity detail" }));

    expect(await screen.findByRole("heading", { name: "Evidence verification unavailable" })).toBeTruthy();
    expect(screen.getByText(/Demo fixtures cannot be promoted/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Check verification availability" })).toBeNull();
  });
});
