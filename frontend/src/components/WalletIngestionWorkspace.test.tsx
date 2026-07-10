// @vitest-environment jsdom

import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletIngestionPreviewResponse,
  WalletIngestionRunResponse,
} from "../types";

const apiMocks = vi.hoisted(() => ({
  getWalletIngestionRun: vi.fn(),
  getWalletIngestionRunCatalog: vi.fn(),
  previewWalletIngestion: vi.fn(),
  runWalletIngestion: vi.fn(),
  inspectWalletHistoryReadiness: vi.fn(),
  inspectWalletNativePnlReadiness: vi.fn(),
  getWalletRunSignals: vi.fn(),
  getWalletRunPnlPreview: vi.fn(),
  compareWalletRuns: vi.fn(),
}));

vi.mock("../api", () => ({
  ...apiMocks,
  walletClusterCompareCsvExportUrl: () => "#cluster.csv",
  walletClusterCompareExportUrl: () => "#cluster.json",
  walletRunExportCsvUrl: () => "#run.csv",
  walletRunExportUrl: () => "#run.json",
  walletRunPnlPreviewCsvExportUrl: () => "#pnl.csv",
  walletRunPnlPreviewExportUrl: () => "#pnl.json",
  walletRunSignalsCsvExportUrl: () => "#signals.csv",
  walletRunSignalsExportUrl: () => "#signals.json",
}));

import WalletIngestionWorkspace from "./WalletIngestionWorkspace";

function runResponse(runId: number): WalletIngestionRunResponse {
  return {
    run_id: runId,
    wallet_address: `EQstored${runId}`,
    wallet_identity: {
      status: "unavailable",
      version: "unavailable",
      network: "ton-unknown",
      canonical_address: null,
      workchain_id: null,
      account_id_hex: null,
      submitted_format: "unrecognized",
      bounceable: null,
      testnet_only: null,
      is_account_existence_proof: false,
      is_ownership_proof: false,
    },
    time_window: "custom",
    custom_start: "2026-06-01T00:00:00Z",
    custom_end: "2026-06-02T00:00:00Z",
    created_at: "2026-07-10T00:00:00Z",
    status: "success",
    data_mode: "real",
    requested_surfaces: ["transactions", "swaps"],
    provider_evidence: [],
    unavailable_surfaces: [],
    incomplete_surfaces: [],
    acquisition_streams: [],
    transfers: [],
    transactions: [],
    swaps: [],
    balances: [],
    warnings: [],
    message: `Stored run ${runId}`,
  };
}

function previewResponse(walletAddress: string): WalletIngestionPreviewResponse {
  return {
    success: true,
    wallet_address: walletAddress,
    time_window: "custom",
    requested_surfaces: ["transactions", "swaps"],
    provider_coverage: [],
    unavailable_surfaces: [],
    incomplete_surfaces: [],
    acquisition_streams: [],
    warnings: [],
    message: "Preview only",
  };
}

function catalogResponse(runIds: string[], truncated = false) {
  return {
    runs: runIds.map((runId) => ({
      run_id: runId,
      wallet_hint: "EQstor…ored",
      time_window: "custom" as const,
      created_at: "2026-07-10T00:00:00Z",
      status: "success" as const,
      data_mode: "real" as const,
    })),
    limit: 8,
    truncated,
  };
}

function Harness() {
  const [accountAddress, setAccountAddress] = useState("");
  return (
    <WalletIngestionWorkspace
      accountAddress={accountAddress}
      runRequestId={0}
      onAccountAddressChange={setAccountAddress}
    />
  );
}

function ExternalPreviewHarness() {
  const [accountAddress, setAccountAddress] = useState("EQexternal");
  const [runRequestId, setRunRequestId] = useState(0);
  return (
    <>
      <button type="button" onClick={() => setRunRequestId((value) => value + 1)}>
        Trigger external preview
      </button>
      <WalletIngestionWorkspace
        accountAddress={accountAddress}
        runRequestId={runRequestId}
        onAccountAddressChange={setAccountAddress}
      />
    </>
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("persisted run loader", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getWalletIngestionRunCatalog.mockResolvedValue({
      runs: [],
      limit: 8,
      truncated: false,
    });
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0);
      return 1;
    });
    apiMocks.getWalletRunSignals.mockImplementation(
      () => new Promise(() => undefined),
    );
    apiMocks.getWalletRunPnlPreview.mockImplementation(
      () => new Promise(() => undefined),
    );
  });

  it("loads read-only, restores controls, and remounts run-scoped state", async () => {
    const user = userEvent.setup();
    apiMocks.getWalletIngestionRun
      .mockResolvedValueOnce(runResponse(25))
      .mockResolvedValueOnce(runResponse(26));
    render(<Harness />);

    const loaderInput = screen.getByLabelText("Stored run ID");
    await user.type(loaderInput, "25");
    await user.click(screen.getByRole("button", { name: "Load stored run" }));

    expect(await screen.findByText("LOADED READ-ONLY")).toBeTruthy();
    expect(apiMocks.getWalletIngestionRun).toHaveBeenLastCalledWith(25);
    expect((screen.getByLabelText("Wallet address") as HTMLInputElement).value).toBe(
      "EQstored25",
    );
    expect((screen.getByLabelText("Window") as HTMLSelectElement).value).toBe(
      "custom",
    );
    expect(screen.queryByText("RESULT STALE")).toBeNull();

    const intervalInput = screen.getByLabelText("Other run IDs for interval check");
    await user.type(intervalInput, "24");
    expect((intervalInput as HTMLInputElement).value).toBe("24");

    await user.clear(loaderInput);
    await user.type(loaderInput, "26");
    await user.click(screen.getByRole("button", { name: "Load stored run" }));

    await waitFor(() => {
      expect(apiMocks.getWalletIngestionRun).toHaveBeenLastCalledWith(26);
      expect(screen.getByText("Run #26 is open read-only.")).toBeTruthy();
    });
    expect(
      (screen.getByLabelText("Other run IDs for interval check") as HTMLInputElement)
        .value,
    ).toBe("");
    expect(screen.queryByText("Run #25 is open read-only.")).toBeNull();
  });

  it("discovers a recent run and opens it only through the full stored-run GET", async () => {
    const user = userEvent.setup();
    apiMocks.getWalletIngestionRunCatalog.mockResolvedValueOnce(
      catalogResponse(["25"]),
    );
    apiMocks.getWalletIngestionRun.mockResolvedValueOnce(runResponse(25));
    render(<Harness />);

    const open = await screen.findByRole("button", {
      name: "Open stored run #25, wallet EQstor…ored",
    });
    expect(apiMocks.getWalletIngestionRunCatalog).toHaveBeenCalledWith(
      8,
      expect.any(AbortSignal),
    );
    expect(apiMocks.getWalletIngestionRun).not.toHaveBeenCalled();

    await user.click(open);

    expect(await screen.findByText("Run #25 is open read-only.")).toBeTruthy();
    expect(apiMocks.getWalletIngestionRun).toHaveBeenCalledWith(25);
    expect(open.getAttribute("aria-current")).toBe("true");
    expect((screen.getByLabelText("Stored run ID") as HTMLInputElement).value).toBe(
      "25",
    );
  });

  it("keeps the prior catalog selection current when another row fails to open", async () => {
    const user = userEvent.setup();
    apiMocks.getWalletIngestionRunCatalog.mockResolvedValueOnce(
      catalogResponse(["26", "25"]),
    );
    apiMocks.getWalletIngestionRun
      .mockResolvedValueOnce(runResponse(25))
      .mockRejectedValueOnce(new Error("Wallet ingestion run not found"));
    render(<Harness />);

    const open25 = await screen.findByRole("button", {
      name: "Open stored run #25, wallet EQstor…ored",
    });
    await user.click(open25);
    expect(await screen.findByText("Run #25 is open read-only.")).toBeTruthy();

    await user.click(
      screen.getByRole("button", {
        name: "Open stored run #26, wallet EQstor…ored",
      }),
    );

    expect(await screen.findByText("Stored run could not be loaded.")).toBeTruthy();
    expect(open25.getAttribute("aria-current")).toBe("true");
    expect(screen.getByText("Run #25 is open read-only.")).toBeTruthy();
  });

  it("releases a stale opening row when an external preview supersedes its load", async () => {
    const user = userEvent.setup();
    const pendingLoad = deferred<WalletIngestionRunResponse>();
    apiMocks.getWalletIngestionRunCatalog.mockResolvedValueOnce(
      catalogResponse(["25"]),
    );
    apiMocks.getWalletIngestionRun.mockReturnValueOnce(pendingLoad.promise);
    apiMocks.previewWalletIngestion.mockImplementation(async (request) =>
      previewResponse(request.wallet_address),
    );
    render(<ExternalPreviewHarness />);

    const open = await screen.findByRole("button", {
      name: "Open stored run #25, wallet EQstor…ored",
    });
    await user.click(open);
    expect(await screen.findByText("Opening")).toBeTruthy();

    await user.click(
      screen.getByRole("button", { name: "Trigger external preview" }),
    );
    expect(await screen.findByText("COVERAGE")).toBeTruthy();
    expect((open as HTMLButtonElement).disabled).toBe(false);

    pendingLoad.resolve(runResponse(25));
    await act(async () => Promise.resolve());
    expect((open as HTMLButtonElement).disabled).toBe(false);
    expect(screen.queryByText("Run #25 is open read-only.")).toBeNull();
  });

  it("does not refresh the catalog when a deferred ingestion settles after unmount", async () => {
    const user = userEvent.setup();
    const pendingRun = deferred<WalletIngestionRunResponse>();
    apiMocks.runWalletIngestion.mockReturnValueOnce(pendingRun.promise);
    const rendered = render(<Harness />);
    await waitFor(() =>
      expect(apiMocks.getWalletIngestionRunCatalog).toHaveBeenCalledTimes(1),
    );

    await user.type(screen.getByLabelText("Wallet address"), "EQpending");
    await user.click(screen.getByRole("button", { name: "Run ingestion" }));
    await waitFor(() => expect(apiMocks.runWalletIngestion).toHaveBeenCalledTimes(1));
    rendered.unmount();

    pendingRun.resolve(runResponse(33));
    await act(async () => Promise.resolve());
    expect(apiMocks.getWalletIngestionRunCatalog).toHaveBeenCalledTimes(1);
  });

  it("refreshes recent runs after a successful ingestion commit", async () => {
    const user = userEvent.setup();
    apiMocks.getWalletIngestionRunCatalog
      .mockResolvedValueOnce(catalogResponse([]))
      .mockResolvedValueOnce(catalogResponse(["33"]));
    apiMocks.runWalletIngestion.mockResolvedValueOnce({
      ...runResponse(33),
      wallet_address: "EQnewrun",
      time_window: "24h",
      custom_start: null,
      custom_end: null,
      requested_surfaces: [
        "transfers",
        "transactions",
        "swaps",
        "balances",
        "jettons",
      ],
    });
    render(<Harness />);
    await waitFor(() =>
      expect(apiMocks.getWalletIngestionRunCatalog).toHaveBeenCalledTimes(1),
    );

    await user.type(screen.getByLabelText("Wallet address"), "EQnewrun");
    await user.click(screen.getByRole("button", { name: "Run ingestion" }));

    await waitFor(() =>
      expect(apiMocks.getWalletIngestionRunCatalog).toHaveBeenCalledTimes(2),
    );
    expect(
      await screen.findByRole("button", {
        name: "Open stored run #33, wallet EQstor…ored",
      }),
    ).toBeTruthy();
  });

  it("preserves the prior run after a failed load", async () => {
    const user = userEvent.setup();
    apiMocks.getWalletIngestionRun
      .mockResolvedValueOnce(runResponse(25))
      .mockRejectedValueOnce(new Error("Wallet ingestion run not found"));
    apiMocks.previewWalletIngestion.mockImplementation(async (request) =>
      previewResponse(request.wallet_address),
    );
    render(<Harness />);

    const loaderInput = screen.getByLabelText("Stored run ID");
    await user.type(loaderInput, "25");
    await user.click(screen.getByRole("button", { name: "Load stored run" }));
    expect(await screen.findByText("Run #25 is open read-only.")).toBeTruthy();

    await user.clear(loaderInput);
    await user.type(loaderInput, "404");
    await user.click(screen.getByRole("button", { name: "Load stored run" }));

    expect(
      await screen.findByText("Stored run could not be loaded."),
    ).toBeTruthy();
    expect(screen.getByText("Run #25 is open read-only.")).toBeTruthy();
    expect(screen.getAllByText("RUN #25").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Preview coverage" }));
    expect(await screen.findByText("COVERAGE")).toBeTruthy();
    expect(screen.queryByText("Stored run could not be loaded.")).toBeNull();
  });

  it("makes a later preview visible instead of leaving the loaded run shadowing it", async () => {
    const user = userEvent.setup();
    apiMocks.getWalletIngestionRun.mockResolvedValueOnce(runResponse(25));
    apiMocks.previewWalletIngestion.mockImplementation(async (request) =>
      previewResponse(request.wallet_address),
    );
    render(<Harness />);

    const loaderInput = screen.getByLabelText("Stored run ID");
    await user.type(loaderInput, "25");
    await user.click(screen.getByRole("button", { name: "Load stored run" }));
    expect(await screen.findByText("LOADED READ-ONLY")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Preview coverage" }));

    expect(await screen.findByText("COVERAGE")).toBeTruthy();
    expect(screen.queryByText("LOADED READ-ONLY")).toBeNull();
    expect(screen.queryByText("RUN #25")).toBeNull();
  });

  it("reuses exact canonical bounds through a DST fold and sub-millisecond precision", async () => {
    const user = userEvent.setup();
    const exactRun = {
      ...runResponse(25),
      custom_start: "2026-10-25T01:30:00.123456Z",
      custom_end: "2026-10-25T02:30:00.654321Z",
    };
    apiMocks.getWalletIngestionRun.mockResolvedValueOnce(exactRun);
    apiMocks.runWalletIngestion.mockImplementation(async (request) => ({
      ...exactRun,
      run_id: 26,
      custom_start: request.custom_start ?? null,
      custom_end: request.custom_end ?? null,
    }));
    render(<Harness />);

    await user.type(screen.getByLabelText("Stored run ID"), "25");
    await user.click(screen.getByRole("button", { name: "Load stored run" }));
    expect(await screen.findByText("LOADED READ-ONLY")).toBeTruthy();
    expect(screen.queryByText("RESULT STALE")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Run ingestion" }));

    await waitFor(() => {
      expect(apiMocks.runWalletIngestion).toHaveBeenCalledWith(
        expect.objectContaining({
          custom_start: "2026-10-25T01:30:00.123456Z",
          custom_end: "2026-10-25T02:30:00.654321Z",
        }),
      );
    });

    const startInput = screen.getByLabelText("Start") as HTMLInputElement;
    const originalVisibleValue = startInput.value;
    fireEvent.change(startInput, {
      target: { value: "2026-10-25T03:30:00.123" },
    });
    fireEvent.change(startInput, { target: { value: originalVisibleValue } });
    await user.click(screen.getByRole("button", { name: "Run ingestion" }));

    await waitFor(() => expect(apiMocks.runWalletIngestion).toHaveBeenCalledTimes(2));
    const secondRequest = apiMocks.runWalletIngestion.mock.calls[1][0];
    expect(secondRequest.custom_start).toBe(
      new Date(originalVisibleValue).toISOString(),
    );
    expect(secondRequest.custom_start).not.toBe(
      "2026-10-25T01:30:00.123456Z",
    );
  });

  it("clears a refresh error when the same stored run is loaded successfully", async () => {
    const user = userEvent.setup();
    apiMocks.getWalletIngestionRun
      .mockResolvedValueOnce(runResponse(25))
      .mockRejectedValueOnce(new Error("Refresh failed"))
      .mockResolvedValueOnce(runResponse(25));
    render(<Harness />);

    await user.type(screen.getByLabelText("Stored run ID"), "25");
    await user.click(screen.getByRole("button", { name: "Load stored run" }));
    expect(await screen.findByText("LOADED READ-ONLY")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Refresh run" }));
    expect((await screen.findAllByText("Refresh failed")).length).toBeGreaterThan(0);

    await user.click(screen.getByRole("button", { name: "Load stored run" }));
    expect(await screen.findByText("LOADED READ-ONLY")).toBeTruthy();
    expect(screen.queryByText("Refresh failed")).toBeNull();
  });
});
