// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletIngestionPreviewResponse,
  WalletIngestionRunCatalogItem,
  WalletIngestionRunResponse,
  WalletIngestionSurface,
} from "../types";

const apiMocks = vi.hoisted(() => ({
  getWalletIngestionRun: vi.fn(),
  previewWalletIngestion: vi.fn(),
  runWalletIngestion: vi.fn(),
}));
const catalogMocks = vi.hoisted(() => ({
  runs: [] as WalletIngestionRunCatalogItem[],
  truncated: false,
  loading: false,
  error: null as string | null,
  refresh: vi.fn(),
}));

vi.mock("../api", () => apiMocks);
vi.mock("../useWalletRunCatalog", () => ({
  useWalletRunCatalog: () => catalogMocks,
}));

import GramActivityWorkspace from "./GramActivityWorkspace";

const WALLET = "UQwallet-under-test";
const ALL_SURFACES: WalletIngestionSurface[] = [
  "transfers",
  "transactions",
  "swaps",
  "balances",
  "jettons",
];

function preview(): WalletIngestionPreviewResponse {
  return {
    success: true,
    wallet_address: WALLET,
    time_window: "24h",
    requested_surfaces: ALL_SURFACES,
    provider_coverage: [{
      provider: "tonapi",
      data_mode: "real",
      source_status: "live",
      warnings: [],
      raw_count: 4,
      normalized_count: 4,
    }],
    unavailable_surfaces: [],
    warnings: [],
    message: "Live coverage ready.",
  };
}

function run(
  overrides: Partial<WalletIngestionRunResponse> = {},
): WalletIngestionRunResponse {
  return {
    run_id: 25,
    wallet_address: WALLET,
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
    time_window: "24h",
    custom_start: null,
    custom_end: null,
    created_at: "2026-07-29T12:00:00Z",
    status: "success",
    data_mode: "real",
    requested_surfaces: ALL_SURFACES,
    provider_evidence: [],
    unavailable_surfaces: [],
    incomplete_surfaces: [],
    acquisition_streams: [],
    transfers: [],
    transactions: [],
    swaps: [],
    balances: [],
    warnings: [],
    message: "Evidence run ready.",
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  catalogMocks.runs = [];
  catalogMocks.truncated = false;
  catalogMocks.loading = false;
  catalogMocks.error = null;
  catalogMocks.refresh.mockResolvedValue(undefined);
  apiMocks.previewWalletIngestion.mockResolvedValue(preview());
  apiMocks.runWalletIngestion.mockResolvedValue(run());
  apiMocks.getWalletIngestionRun.mockResolvedValue(run());
});

afterEach(cleanup);

describe("GramActivityWorkspace", () => {
  it("previews coverage and persists the exact selected scope", async () => {
    const user = userEvent.setup();
    const onRunResultChange = vi.fn();
    render(
      <GramActivityWorkspace
        accountAddress={WALLET}
        onAccountAddressChange={vi.fn()}
        activeRun={null}
        onRunResultChange={onRunResultChange}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Preview coverage" }));
    await waitFor(() => expect(apiMocks.previewWalletIngestion).toHaveBeenCalledWith(
      { wallet_address: WALLET, time_window: "24h", surfaces: ALL_SURFACES },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText("Providers can return this scope")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Persist this run" }));
    await waitFor(() => expect(apiMocks.runWalletIngestion).toHaveBeenCalledWith(
      { wallet_address: WALLET, time_window: "24h", surfaces: ALL_SURFACES },
      expect.any(AbortSignal),
    ));
    expect(onRunResultChange).toHaveBeenLastCalledWith(expect.objectContaining({ run_id: 25 }));
    expect(catalogMocks.refresh).toHaveBeenCalledOnce();
  });

  it("restores the exact time window and surfaces of a saved run", async () => {
    const user = userEvent.setup();
    const onAccountAddressChange = vi.fn();
    const onRunResultChange = vi.fn();
    catalogMocks.runs = [{
      run_id: "25",
      wallet_hint: "UQwall…llet",
      time_window: "custom",
      created_at: "2026-07-29T12:00:00Z",
      status: "success",
      data_mode: "real",
    }];
    const stored = run({
      wallet_address: "UQstored-wallet",
      time_window: "custom",
      custom_start: "2026-07-20T00:00:00Z",
      custom_end: "2026-07-21T00:00:00Z",
      requested_surfaces: ["transactions", "swaps"],
    });
    apiMocks.getWalletIngestionRun.mockResolvedValue(stored);

    render(
      <GramActivityWorkspace
        accountAddress={WALLET}
        onAccountAddressChange={onAccountAddressChange}
        activeRun={null}
        onRunResultChange={onRunResultChange}
      />,
    );
    await user.click(screen.getByRole("button", { name: /Run #25/ }));

    await waitFor(() => expect(apiMocks.getWalletIngestionRun).toHaveBeenCalledWith(25, expect.any(AbortSignal)));
    expect(onAccountAddressChange).toHaveBeenCalledWith("UQstored-wallet");
    expect(onRunResultChange).toHaveBeenCalledWith(stored);
    expect(screen.getByRole("button", { name: "Custom" }).className).toContain("is-active");
    expect((screen.getByRole("button", { name: /Transfers/ }) as HTMLButtonElement).getAttribute("aria-pressed")).toBe("false");
    expect((screen.getByRole("button", { name: /DEX swaps/ }) as HTMLButtonElement).getAttribute("aria-pressed")).toBe("true");
  });

  it("aborts and ignores a preview when the wallet scope changes", async () => {
    const pending = deferred<WalletIngestionPreviewResponse>();
    apiMocks.previewWalletIngestion.mockReturnValue(pending.promise);
    const onRunResultChange = vi.fn();
    const { rerender } = render(
      <GramActivityWorkspace
        accountAddress={WALLET}
        onAccountAddressChange={vi.fn()}
        activeRun={null}
        onRunResultChange={onRunResultChange}
      />,
    );
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Preview coverage" }));
    await waitFor(() => expect(apiMocks.previewWalletIngestion).toHaveBeenCalledOnce());
    const signal = apiMocks.previewWalletIngestion.mock.calls[0][1] as AbortSignal;

    rerender(
      <GramActivityWorkspace
        accountAddress="UQdifferent-wallet"
        onAccountAddressChange={vi.fn()}
        activeRun={null}
        onRunResultChange={onRunResultChange}
      />,
    );
    expect(signal.aborted).toBe(true);
    pending.resolve(preview());
    await waitFor(() => expect(screen.queryByText("Providers can return this scope")).toBeNull());
    expect(onRunResultChange).not.toHaveBeenCalled();
  });

  it("shows catalog failures without blocking a new run", () => {
    catalogMocks.error = "Database offline";
    render(
      <GramActivityWorkspace
        accountAddress={WALLET}
        onAccountAddressChange={vi.fn()}
        activeRun={null}
        onRunResultChange={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert").textContent).toContain("Saved runs unavailable: Database offline");
    expect((screen.getByRole("button", { name: "Create evidence run" }) as HTMLButtonElement).disabled).toBe(false);
  });
});
