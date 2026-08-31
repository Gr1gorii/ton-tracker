// @vitest-environment jsdom

import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WalletCase, WalletCaseSync } from "../walletCase";
import type { WalletCaseSyncJobController } from "../useWalletCaseSyncJob";
import {
  activeSyncFixture,
  emptyWalletCaseFixture,
  resumeSyncFixture,
  succeededSyncFixture,
  walletCaseFixture,
  zeroSummaryFixture,
} from "../test/walletCaseFixtures";
import { manifestResponseFixture } from "../test/walletCaseSyncManifestFixtures";
import {
  checkpointContinuationReceiptFixture,
  checkpointContinuationPlanFixture,
  streamCheckpointCatalogFixture,
  streamCheckpointChainFixture,
  streamCheckpointDetailFixture,
  streamCheckpointHistoryFixture,
} from "../test/walletCaseStreamCheckpointFixtures";
import { API_BASE } from "../apiBase";

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
    resume: vi.fn().mockResolvedValue(undefined),
    resumePlanned: vi.fn().mockResolvedValue(undefined),
    retryPending: vi.fn().mockResolvedValue(undefined),
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

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

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
      mode: "bounded",
      time_window: "24h",
      surfaces: ["transfers", "transactions", "swaps", "balances", "jettons"],
    });
  });

  it("refreshes a usable snapshot incrementally with its exact surfaces", async () => {
    const controller = controllerFixture({ sync: succeededSyncFixture() });
    mocks.useWalletCaseSyncJob.mockReturnValue(controller);
    const user = userEvent.setup();
    const snapshot = succeededSyncFixture({
      requested_scope: {
        ...succeededSyncFixture().requested_scope,
        surfaces: ["transactions", "balances"],
      },
    });
    renderSummary(walletCaseFixture({
      latestAttempt: snapshot,
      currentSnapshot: snapshot,
    }));

    await user.click(screen.getByRole("button", { name: "Refresh incrementally" }));

    expect(controller.start).toHaveBeenCalledWith({
      mode: "incremental",
      time_window: "24h",
      surfaces: ["transactions", "balances"],
    });
    expect(screen.getByText(/next refresh starts 15 minutes before/i)).toBeTruthy();
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

  it("shows and explicitly loads the content-addressed acquisition manifest", async () => {
    const payload = manifestResponseFixture();
    const checkpoints = streamCheckpointCatalogFixture();
    const historyFixture = streamCheckpointHistoryFixture();
    const history = {
      ...historyFixture,
      page: { ...historyFixture.page, limit: 10 },
    };
    const checkpointDetail = streamCheckpointDetailFixture();
    const checkpointChain = streamCheckpointChainFixture();
    const continuationPlan = checkpointContinuationPlanFixture();
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(
        JSON.stringify(payload),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify(checkpoints),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify(history),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify(continuationPlan),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify(checkpointDetail),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ))
      .mockResolvedValueOnce(new Response(
        JSON.stringify(checkpointChain),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ));
    vi.stubGlobal("fetch", fetchMock);
    const controller = controllerFixture();
    mocks.useWalletCaseSyncJob.mockReturnValue(controller);
    const user = userEvent.setup();
    renderSummary(walletCaseFixture());

    expect(screen.getByRole("heading", { name: "Content-addressed manifest" })).toBeTruthy();
    expect(screen.getByText(payload.manifest.public_id)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Inspect manifest" }));

    expect(await screen.findByText("Verified by the server integrity gate")).toBeTruthy();
    expect(screen.getByText(/0 streams · 0 pages · 0 response digests/)).toBeTruthy();
    expect(screen.getByText("Durable stream checkpoints")).toBeTruthy();
    expect(screen.getByText(/1 ready · 0 complete · 0 blocked/)).toBeTruthy();
    expect(screen.getByText(/continuation verified; the next request starts at page 2/i)).toBeTruthy();
    expect(screen.getByText(/Verify the current plan before resuming/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Resume planned .* stream/ })).toBeNull();
    expect(screen.getByText("Checkpoint revision history")).toBeTruthy();
    expect(screen.getByText((_content, element) => (
      element?.textContent === "1 of 2 loaded"
    ))).toBeTruthy();
    expect(screen.getByRole("button", { name: "Load older revisions" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Verify continuation plan" }));
    expect(await screen.findByText("Verified continuation plan")).toBeTruthy();
    expect(screen.getByText(continuationPlan.plan.public_id)).toBeTruthy();
    expect(screen.getByText(/2 revisions · 2\/2 pages · ready · next page 3/)).toBeTruthy();
    await user.click(screen.getByRole("button", {
      name: "Resume planned transactions stream",
    }));
    expect(controller.resumePlanned).toHaveBeenCalledWith(
      continuationPlan.plan.public_id,
      continuationPlan.document.streams[0].tip_checkpoint.public_id,
    );
    expect(controller.resume).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", {
      name: `Inspect checkpoint revision ${checkpoints.checkpoints[0].checkpoint.public_id}`,
    }));
    expect(await screen.findByText("Verified revision")).toBeTruthy();
    expect(screen.getByText("Root revision")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Verify checkpoint chain" }));
    expect(await screen.findByText("Content-addressed chain")).toBeTruthy();
    expect(screen.getAllByText(checkpointChain.chain.public_id)).toHaveLength(2);
    expect(screen.getByText("#1 · bounded")).toBeTruthy();
    expect(screen.getByText("#2 · resume")).toBeTruthy();
    const createObjectUrl = vi.fn()
      .mockReturnValueOnce("blob:continuation-plan")
      .mockReturnValueOnce("blob:checkpoint-chain");
    const revokeObjectUrl = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: createObjectUrl,
      revokeObjectURL: revokeObjectUrl,
    });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    await user.click(screen.getByRole("button", { name: "Export verified continuation plan JSON" }));
    await user.click(screen.getByRole("button", { name: "Export verified chain JSON" }));
    expect(createObjectUrl).toHaveBeenCalledTimes(2);
    expect(anchorClick).toHaveBeenCalledTimes(2);
    expect(revokeObjectUrl.mock.calls).toEqual([
      ["blob:continuation-plan"],
      ["blob:checkpoint-chain"],
    ]);
    anchorClick.mockRestore();
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${payload.document.case_public_id}/syncs/${payload.document.sync_public_id}/manifest`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${payload.document.case_public_id}/stream-checkpoints`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${payload.document.case_public_id}/stream-checkpoints/history?limit=10`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${payload.document.case_public_id}/stream-checkpoints/continuation-plan`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${payload.document.case_public_id}/stream-checkpoints/${checkpoints.checkpoints[0].checkpoint.public_id}`,
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${payload.document.case_public_id}/stream-checkpoints/${checkpoints.checkpoints[0].checkpoint.public_id}/chain`,
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("verifies and exports the immutable result of a plan-bound resume", async () => {
    const receipt = checkpointContinuationReceiptFixture();
    const base = resumeSyncFixture();
    const snapshot = resumeSyncFixture({
      requested_scope: {
        ...base.requested_scope,
        source_checkpoint_public_id: receipt.receipt.input_checkpoint_public_id,
        continuation_plan_public_id: receipt.receipt.input_plan_public_id,
      },
    });
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify(receipt),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderSummary(walletCaseFixture({
      latestAttempt: snapshot,
      currentSnapshot: snapshot,
    }));

    await user.click(screen.getByRole("button", {
      name: "Verify continuation receipt",
    }));

    expect(await screen.findByText("Verified checkpoint transition")).toBeTruthy();
    expect(screen.getByText(receipt.receipt.public_id)).toBeTruthy();
    expect(screen.getByText((_content, element) => (
      element?.textContent === `ready · next page ${receipt.document.output.next_page_index}`
    ))).toBeTruthy();
    expect(screen.getByText("Provider pages").closest("div")?.textContent).toContain(
      `+${receipt.receipt.page_count_delta}`,
    );
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${snapshot.case_public_id}/syncs/${snapshot.public_id}/continuation-receipt`,
      expect.objectContaining({ cache: "no-store" }),
    );

    const createObjectUrl = vi.fn().mockReturnValue("blob:continuation-receipt");
    const revokeObjectUrl = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: createObjectUrl,
      revokeObjectURL: revokeObjectUrl,
    });
    const anchorClick = vi.spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);
    await user.click(screen.getByRole("button", {
      name: "Export verified continuation receipt JSON",
    }));
    expect(createObjectUrl).toHaveBeenCalledOnce();
    expect(revokeObjectUrl).toHaveBeenCalledWith("blob:continuation-receipt");
    anchorClick.mockRestore();
  });

  it.each(["blocked", "complete"] as const)(
    "never offers resume for a %s checkpoint",
    async (resumeState) => {
      const payload = manifestResponseFixture();
      const original = streamCheckpointCatalogFixture();
      const checkpoint = original.checkpoints[0];
      const catalog = {
        ...original,
        ready_count: 0,
        complete_count: resumeState === "complete" ? 1 : 0,
        blocked_count: resumeState === "blocked" ? 1 : 0,
        checkpoints: [{
          checkpoint: { ...checkpoint.checkpoint, resume_state: resumeState },
          document: {
            ...checkpoint.document,
            completion_state: resumeState === "complete" ? "complete" : "incomplete",
            termination_reason: resumeState === "complete"
              ? "requested_start_reached"
              : "protocol_error",
            resume_state: resumeState,
            resume_blocker: resumeState === "blocked"
              ? "provider_protocol_error"
              : null,
            continuation_cursor: null,
            continuation_page_index: null,
          },
        }],
      };
      const history = streamCheckpointHistoryFixture({ hasMore: false });
      vi.stubGlobal("fetch", vi.fn()
        .mockResolvedValueOnce(new Response(JSON.stringify(payload), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify(catalog), { status: 200 }))
        .mockResolvedValueOnce(new Response(JSON.stringify({
          ...history,
          page: { ...history.page, limit: 10 },
        }), { status: 200 })));
      const user = userEvent.setup();
      renderSummary(walletCaseFixture());

      await user.click(screen.getByRole("button", { name: "Inspect manifest" }));

      expect(await screen.findByText("Durable stream checkpoints")).toBeTruthy();
      expect(screen.queryByRole("button", { name: /Resume .* stream/ })).toBeNull();
    },
  );

  it("labels a legacy snapshot without a manifest instead of inventing provenance", () => {
    const snapshot = succeededSyncFixture();
    const limitations = [
      ...snapshot.limitations,
      {
        code: "acquisition_manifest_unavailable",
        message: "This legacy snapshot predates immutable acquisition manifests.",
      },
    ];
    const legacy = succeededSyncFixture({
      acquisition_manifest: null,
      limitations,
      result: { ...snapshot.result!, limitations },
    });

    renderSummary(walletCaseFixture({
      latestAttempt: legacy,
      currentSnapshot: legacy,
    }));

    expect(screen.getByRole("heading", { name: "Manifest unavailable" })).toBeTruthy();
    expect(screen.getByText(/legacy snapshot has no immutable/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Inspect manifest" })).toBeNull();
  });
});
