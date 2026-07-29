// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletClusterCompareResponse,
  WalletIngestionRunCatalogItem,
  WalletSignalsRecord,
} from "../types";

const apiMocks = vi.hoisted(() => ({
  compareWalletRuns: vi.fn(),
  walletClusterCompareCsvExportUrl: vi.fn((ids: number[]) => `/compare/${ids.join("-")}.csv`),
  walletClusterCompareExportUrl: vi.fn((ids: number[]) => `/compare/${ids.join("-")}.json`),
}));
const catalogMocks = vi.hoisted(() => ({
  runs: [] as WalletIngestionRunCatalogItem[],
  truncated: false,
  loading: false,
  error: null as string | null,
  refresh: vi.fn(),
}));

vi.mock("../api", () => apiMocks);
vi.mock("../useWalletRunCatalog", () => ({ useWalletRunCatalog: () => catalogMocks }));

import GramCompareView from "./GramCompareView";

function wallet(runId: number, address: string): WalletSignalsRecord {
  return {
    run_id: runId,
    wallet_address: address,
    data_mode: "mock",
    ton_balance: "238.75",
    portfolio_value_usd: "950.42",
    distinct_tokens_touched: ["JETTON_ALPHA"],
    buy_swap_count: 1,
    sell_swap_count: 0,
    avg_ton_per_buy_swap: "15",
    first_buy_at: "2026-06-01T10:35:00Z",
    signal_basis: "legacy_mock_fixture",
    canonical_ledger_digest_sha256: null,
    canonical_activity_count: 0,
    incoming_activity_count: 0,
    outgoing_activity_count: 0,
    counterparties: [],
    warnings: [],
  };
}

function comparison(): WalletClusterCompareResponse {
  return {
    wallets: [wallet(2, "UQwallet-two-long-address"), wallet(1, "UQwallet-one-long-address")],
    comparison_window_seconds: 86_400,
    pairs: [{
      wallet_a_run_id: 2,
      wallet_b_run_id: 1,
      wallet_a_address: "UQwallet-two-long-address",
      wallet_b_address: "UQwallet-one-long-address",
      score: 88.5,
      band: "very high similarity, still not proof",
      shared_tokens: ["JETTON_ALPHA"],
      shared_counterparties: [],
      note: "Very similar behavior, still not proof of common ownership.",
    }],
    is_cluster_proof: false,
    signal_basis: "legacy_mock_fixture",
    note: "Probabilistic behavioral similarity only, not proof of common ownership.",
  };
}

function catalogRun(id: string, mode: "mock" | "real" = "mock"): WalletIngestionRunCatalogItem {
  return {
    run_id: id,
    wallet_hint: `UQwall…00${id}`,
    time_window: "24h",
    created_at: `2026-07-${20 + Number(id)}T12:00:00Z`,
    status: "success",
    data_mode: mode,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  catalogMocks.runs = [catalogRun("2"), catalogRun("1")];
  catalogMocks.loading = false;
  catalogMocks.error = null;
  apiMocks.compareWalletRuns.mockResolvedValue(comparison());
});

afterEach(cleanup);

describe("GramCompareView", () => {
  it("auto-selects compatible recent runs and renders an honest pair result", async () => {
    const user = userEvent.setup();
    render(<GramCompareView activeRun={null} onOpenActivity={vi.fn()} />);
    const button = screen.getByRole("button", { name: "Compare selected runs" });
    await waitFor(() => expect((button as HTMLButtonElement).disabled).toBe(false));
    await user.click(button);

    await waitFor(() => expect(apiMocks.compareWalletRuns).toHaveBeenCalledWith([2, 1], expect.any(AbortSignal)));
    expect((await screen.findAllByText("88.5")).length).toBe(2);
    expect(screen.getByText("very high similarity, still not proof")).toBeTruthy();
    expect(screen.getByText("Cluster proof: no")).toBeTruthy();
    expect((screen.getByRole("link", { name: "JSON" }) as HTMLAnchorElement).getAttribute("href")).toBe("/compare/2-1.json");
  });

  it("disables runs from another data mode once selection is locked", async () => {
    catalogMocks.runs = [catalogRun("3", "real"), catalogRun("2"), catalogRun("1")];
    render(<GramCompareView activeRun={null} onOpenActivity={vi.fn()} />);
    const mockRun = screen.getByRole("button", { name: /Run #2/ }) as HTMLButtonElement;
    await waitFor(() => expect(mockRun.disabled).toBe(true));
    expect(screen.getByText(/Real-mode comparison requires/)).toBeTruthy();
  });

  it("guides the user to create runs when the catalog is empty", async () => {
    catalogMocks.runs = [];
    const onOpenActivity = vi.fn();
    const user = userEvent.setup();
    render(<GramCompareView activeRun={null} onOpenActivity={onOpenActivity} />);
    await user.click(screen.getByRole("button", { name: "Open activity" }));
    expect(onOpenActivity).toHaveBeenCalledOnce();
    expect(apiMocks.compareWalletRuns).not.toHaveBeenCalled();
  });
});
