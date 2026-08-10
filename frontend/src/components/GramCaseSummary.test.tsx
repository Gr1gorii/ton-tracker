// @vitest-environment jsdom

import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WalletCase, WalletCaseSync } from "../walletCase";
import type { WalletCaseSyncJobController } from "../useWalletCaseSyncJob";
import {
  activeSyncFixture,
  emptyWalletCaseFixture,
  succeededSyncFixture,
  walletCaseFixture,
  zeroSummaryFixture,
} from "../test/walletCaseFixtures";

const mocks = vi.hoisted(() => ({ useWalletCaseSyncJob: vi.fn() }));

vi.mock("../useWalletCaseSyncJob", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../useWalletCaseSyncJob")>();
  return { ...actual, useWalletCaseSyncJob: mocks.useWalletCaseSyncJob };
});

import GramCaseSummary from "./GramCaseSummary";

function controllerFixture(overrides: Partial<WalletCaseSyncJobController> = {}): WalletCaseSyncJobController {
  return {
    sync: null,
    transportState: "idle",
    transportError: null,
    start: vi.fn().mockResolvedValue(undefined),
    retry: vi.fn().mockResolvedValue(undefined),
    cancel: vi.fn().mockResolvedValue(undefined),
    checkNow: vi.fn(),
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.useWalletCaseSyncJob.mockReturnValue(controllerFixture());
});

afterEach(cleanup);

function renderSummary(walletCase: WalletCase, onRefresh = vi.fn().mockResolvedValue(undefined)) {
  return {
    onRefresh,
    ...render(<GramCaseSummary walletCase={walletCase} refreshError={null} onRefresh={onRefresh} />),
  };
}

describe("GramCaseSummary", () => {
  it("shows honest unavailable metrics until a usable snapshot exists", async () => {
    renderSummary(emptyWalletCaseFixture());

    expect(screen.getByText("Not proven")).toBeTruthy();
    expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText(/No usable snapshot exists yet/)).toBeTruthy();
    expect(screen.queryByText("Compatibility view")).toBeNull();
    expect(screen.queryByRole("button", { name: /Open advanced activity/ })).toBeNull();
  });

  it("starts only the explicit bounded 24-hour scope through the durable controller", async () => {
    const controller = controllerFixture();
    mocks.useWalletCaseSyncJob.mockReturnValue(controller);
    const user = userEvent.setup();

    renderSummary(emptyWalletCaseFixture());
    await user.click(screen.getByRole("button", { name: "Sync last 24 hours" }));

    expect(controller.start).toHaveBeenCalledWith({
      time_window: "24h",
      surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"],
    });
  });

  it("keeps the previous usable snapshot visible while a newer job runs", async () => {
    const running = activeSyncFixture("running");
    const snapshot = succeededSyncFixture({
      public_id: "550e8400-e29b-41d4-b716-446655440002",
    });
    mocks.useWalletCaseSyncJob.mockReturnValue(controllerFixture({
      sync: running,
      transportState: "polling",
    }));
    renderSummary(walletCaseFixture({
      latestAttempt: running,
      currentSnapshot: snapshot,
    }));

    expect(screen.getByRole("heading", { name: "Acquiring bounded evidence" })).toBeTruthy();
    expect(screen.getByText(/previous usable snapshot stays visible/i)).toBeTruthy();
    const metric = screen.getByText("Returned activity rows").closest("article");
    expect(metric?.textContent).toContain("6");
    expect(screen.getByText(snapshot.public_id)).toBeTruthy();
  });

  it("background-refetches the case when the durable controller reports terminal", async () => {
    const running = activeSyncFixture("running");
    const onRefresh = vi.fn().mockResolvedValue(undefined);
    let terminalCallback: ((sync: WalletCaseSync) => void | Promise<void>) | undefined;
    mocks.useWalletCaseSyncJob.mockImplementation((options) => {
      terminalCallback = options.onTerminal;
      return controllerFixture({ sync: running, transportState: "polling" });
    });

    renderSummary(walletCaseFixture({ latestAttempt: running, currentSnapshot: null }), onRefresh);
    screen.getByRole("heading", { name: "Acquiring bounded evidence" });
    await act(async () => {
      await terminalCallback?.(succeededSyncFixture());
    });

    expect(onRefresh).toHaveBeenCalledWith(true);
  });

  it("shows migrated compact-summary gaps as unavailable rather than zero", async () => {
    const snapshot = succeededSyncFixture();
    const limitations = [
      ...snapshot.limitations,
      { code: "summary_unavailable", message: "Zero placeholders are not evidence of no activity." },
    ];
    const result = {
      ...snapshot.result!,
      summary: zeroSummaryFixture(),
      limitations,
      message: "Compact summary is unavailable for this synchronization.",
    };
    const migrated = succeededSyncFixture({
      summary: result.summary,
      limitations,
      message: result.message,
      result,
    });
    renderSummary(walletCaseFixture({
      latestAttempt: migrated,
      currentSnapshot: migrated,
    }));

    expect(screen.getByRole("heading", { name: "Available" })).toBeTruthy();
    expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText(/Zero placeholders are not evidence/)).toBeTruthy();
  });
});
