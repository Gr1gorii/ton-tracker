// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WalletCaseSyncJobController } from "../useWalletCaseSyncJob";
import {
  activeSyncFixture,
  failedSyncFixture,
  retryWaitSyncFixture,
  succeededSyncFixture,
} from "../test/walletCaseFixtures";
import CaseSyncPanel from "./CaseSyncPanel";

const DEFAULT_REQUEST = {
  time_window: "24h" as const,
  surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"] as const,
};

function controllerFixture(
  overrides: Partial<WalletCaseSyncJobController> = {},
): WalletCaseSyncJobController {
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

afterEach(cleanup);

describe("CaseSyncPanel", () => {
  it("exposes real determinate progress and a polite persisted-job status", () => {
    render(<CaseSyncPanel
      controller={controllerFixture({
        sync: activeSyncFixture("running"),
        transportState: "polling",
      })}
      hasSnapshot
      defaultRequest={{ ...DEFAULT_REQUEST, surfaces: [...DEFAULT_REQUEST.surfaces] }}
    />);

    const progress = screen.getByRole("progressbar", { name: "Synchronization progress" });
    expect(progress.getAttribute("max")).toBe("5");
    expect(progress.getAttribute("value")).toBe("2");
    expect(screen.getAllByRole("status").some(
      (status) => status.textContent?.includes("Acquiring bounded evidence"),
    )).toBe(true);
    expect(screen.getByText(/previous usable snapshot stays visible/i)).toBeTruthy();
  });

  it("uses an indeterminate progressbar when the server has no total", () => {
    render(<CaseSyncPanel
      controller={controllerFixture({
        sync: activeSyncFixture("running", { progress: { current: 1, total: null } }),
        transportState: "polling",
      })}
      hasSnapshot={false}
      defaultRequest={{ ...DEFAULT_REQUEST, surfaces: [...DEFAULT_REQUEST.surfaces] }}
    />);

    expect(screen.getByRole("progressbar").getAttribute("value")).toBeNull();
    expect(screen.getByText("1 completed")).toBeTruthy();
  });

  it("renders queued retry_wait attempt, safe message, and retry time", () => {
    render(<CaseSyncPanel
      controller={controllerFixture({ sync: retryWaitSyncFixture(), transportState: "polling" })}
      hasSnapshot={false}
      defaultRequest={{ ...DEFAULT_REQUEST, surfaces: [...DEFAULT_REQUEST.surfaces] }}
    />);

    expect(screen.getByRole("heading", { name: "Waiting to retry" })).toBeTruthy();
    expect(screen.getByText(/Attempt 2 of 4 did not complete/)).toBeTruthy();
    expect(screen.getByText(/temporarily unavailable/)).toBeTruthy();
  });

  it("requires a two-step confirmation before cancellation", async () => {
    const controller = controllerFixture({
      sync: activeSyncFixture("running"),
      transportState: "polling",
    });
    const user = userEvent.setup();
    render(<CaseSyncPanel
      controller={controller}
      hasSnapshot={false}
      defaultRequest={{ ...DEFAULT_REQUEST, surfaces: [...DEFAULT_REQUEST.surfaces] }}
    />);

    await user.click(screen.getByRole("button", { name: "Cancel sync" }));
    expect(controller.cancel).not.toHaveBeenCalled();
    expect(screen.getByRole("group", { name: "Confirm sync cancellation" })).toBeTruthy();
    const keepSyncing = screen.getByRole("button", { name: "Keep syncing" });
    expect(document.activeElement).toBe(keepSyncing);
    await user.click(keepSyncing);
    expect(screen.queryByRole("group", { name: "Confirm sync cancellation" })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Cancel sync" }));
    await user.click(screen.getByRole("button", { name: "Cancel sync" }));
    await user.click(screen.getByRole("button", { name: "Confirm cancellation" }));
    expect(controller.cancel).toHaveBeenCalledTimes(1);
  });

  it("does not offer duplicate cancellation after the server accepts the request", () => {
    render(<CaseSyncPanel
      controller={controllerFixture({
        sync: activeSyncFixture("running", { cancel_requested: true, status_version: 3 }),
        transportState: "polling",
      })}
      hasSnapshot={false}
      defaultRequest={{ ...DEFAULT_REQUEST, surfaces: [...DEFAULT_REQUEST.surfaces] }}
    />);

    expect(screen.queryByRole("button", { name: "Cancel sync" })).toBeNull();
    expect(screen.getByText(/bounded provider crawl returns/)).toBeTruthy();
  });

  it("announces safe terminal errors and retries only the same scope", async () => {
    const controller = controllerFixture({ sync: failedSyncFixture() });
    const user = userEvent.setup();
    render(<CaseSyncPanel
      controller={controller}
      hasSnapshot
      defaultRequest={{ ...DEFAULT_REQUEST, surfaces: [...DEFAULT_REQUEST.surfaces] }}
    />);

    expect(screen.getByRole("alert").textContent).toContain("provider did not respond");
    await user.click(screen.getByRole("button", { name: "Retry same scope" }));
    expect(controller.retry).toHaveBeenCalledTimes(1);
  });

  it("keeps POST transport errors visible beside an older terminal snapshot", async () => {
    const controller = controllerFixture({
      sync: succeededSyncFixture(),
      transportError: "The request outcome is not known yet.",
    });
    const user = userEvent.setup();
    render(<CaseSyncPanel
      controller={controller}
      hasSnapshot
      defaultRequest={{ ...DEFAULT_REQUEST, surfaces: [...DEFAULT_REQUEST.surfaces] }}
    />);

    expect(screen.getByRole("alert").textContent).toContain("outcome is not known");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(controller.start).toHaveBeenCalledTimes(1);
  });
});
