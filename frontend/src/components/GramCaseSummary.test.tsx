// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WalletCase, WalletCaseSync } from "../walletCase";
import type { WalletCaseSyncJobController } from "../useWalletCaseSyncJob";
import {
  activeSyncFixture,
  CASE_ID,
  emptyWalletCaseFixture,
  succeededSyncFixture,
  walletCaseFixture,
  zeroSummaryFixture,
} from "../test/walletCaseFixtures";

const mocks = vi.hoisted(() => ({
  getWalletCase: vi.fn(),
  useWalletCaseSyncJob: vi.fn(),
}));

vi.mock("../walletCaseApi", () => ({ getWalletCase: mocks.getWalletCase }));
vi.mock("../useWalletCaseSyncJob", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../useWalletCaseSyncJob")>();
  return { ...actual, useWalletCaseSyncJob: mocks.useWalletCaseSyncJob };
});

import GramCaseSummary from "./GramCaseSummary";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

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

describe("GramCaseSummary", () => {
  it("shows honest unavailable metrics until a usable snapshot exists", async () => {
    mocks.getWalletCase.mockResolvedValue(emptyWalletCaseFixture());

    render(<GramCaseSummary caseId={CASE_ID} />);

    expect(await screen.findByRole("heading", { name: "EQC-demo-wallet" })).toBeTruthy();
    expect(screen.getAllByText("Demo data")).toHaveLength(2);
    expect(screen.getByText("TON mainnet")).toBeTruthy();
    expect(screen.getByText("Not proven")).toBeTruthy();
    expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(5);
    expect(screen.getByText(/No usable snapshot exists yet/)).toBeTruthy();
    expect(screen.queryByText("Compatibility view")).toBeNull();
    expect(screen.queryByRole("button", { name: /Open advanced activity/ })).toBeNull();
  });

  it("starts only the explicit bounded 24-hour scope through the durable controller", async () => {
    const controller = controllerFixture();
    mocks.useWalletCaseSyncJob.mockReturnValue(controller);
    mocks.getWalletCase.mockResolvedValue(emptyWalletCaseFixture());
    const user = userEvent.setup();

    render(<GramCaseSummary caseId={CASE_ID} />);
    await user.click(await screen.findByRole("button", { name: "Sync last 24 hours" }));

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
    mocks.getWalletCase.mockResolvedValue(walletCaseFixture({
      latestAttempt: running,
      currentSnapshot: snapshot,
    }));

    render(<GramCaseSummary caseId={CASE_ID} />);

    expect(await screen.findByRole("heading", { name: "Acquiring bounded evidence" })).toBeTruthy();
    expect(screen.getByText(/previous usable snapshot stays visible/i)).toBeTruthy();
    const metric = screen.getByText("Returned activity rows").closest("article");
    expect(metric?.textContent).toContain("6");
    expect(screen.getByText(snapshot.public_id)).toBeTruthy();
  });

  it("background-refetches the case when the durable controller reports terminal", async () => {
    const running = activeSyncFixture("running");
    const completed = walletCaseFixture();
    mocks.getWalletCase
      .mockResolvedValueOnce(walletCaseFixture({ latestAttempt: running, currentSnapshot: null }))
      .mockResolvedValueOnce(completed);
    let terminalCallback: ((sync: WalletCaseSync) => void | Promise<void>) | undefined;
    mocks.useWalletCaseSyncJob.mockImplementation((options) => {
      terminalCallback = options.onTerminal;
      return controllerFixture({ sync: running, transportState: "polling" });
    });

    render(<GramCaseSummary caseId={CASE_ID} />);
    await screen.findByRole("heading", { name: "Acquiring bounded evidence" });
    await act(async () => {
      await terminalCallback?.(succeededSyncFixture());
    });

    await waitFor(() => expect(mocks.getWalletCase).toHaveBeenCalledTimes(2));
    expect(await screen.findByRole("heading", { name: "Available" })).toBeTruthy();
  });

  it("cannot publish a late response from a previous case route", async () => {
    const oldRequest = deferred<WalletCase>();
    const nextRequest = deferred<WalletCase>();
    const otherCaseId = "550e8400-e29b-41d4-a716-446655440099";
    mocks.getWalletCase
      .mockReturnValueOnce(oldRequest.promise)
      .mockReturnValueOnce(nextRequest.promise);
    const { rerender } = render(<GramCaseSummary caseId={CASE_ID} />);

    rerender(<GramCaseSummary caseId={otherCaseId} />);
    await act(async () => {
      nextRequest.resolve(emptyWalletCaseFixture({
        public_id: otherCaseId,
        display_address: "EQC-other-wallet",
      }));
      await Promise.resolve();
    });
    expect(await screen.findByRole("heading", { name: "EQC-other-wallet" })).toBeTruthy();

    await act(async () => {
      oldRequest.resolve(walletCaseFixture());
      await Promise.resolve();
    });
    expect(screen.getByRole("heading", { name: "EQC-other-wallet" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "EQC-demo-wallet" })).toBeNull();
  });

  it("renders no summary metrics when case validation fails closed", async () => {
    mocks.getWalletCase.mockRejectedValue(
      new Error("wallet case environment or identity does not match its sync evidence"),
    );

    render(<GramCaseSummary caseId={CASE_ID} />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("environment or identity");
    expect(screen.queryByText("Returned activity rows")).toBeNull();
    expect(screen.queryByRole("button", { name: "Sync last 24 hours" })).toBeNull();
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
    mocks.getWalletCase.mockResolvedValue(walletCaseFixture({
      latestAttempt: migrated,
      currentSnapshot: migrated,
    }));

    render(<GramCaseSummary caseId={CASE_ID} />);

    expect(await screen.findByRole("heading", { name: "Available" })).toBeTruthy();
    expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText(/Zero placeholders are not evidence/)).toBeTruthy();
  });
});
