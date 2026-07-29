// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletHistoryReadinessResponse,
  WalletIngestionRunCatalogItem,
} from "../types";

const apiMocks = vi.hoisted(() => ({ inspectWalletHistoryReadiness: vi.fn() }));
const readinessMocks = vi.hoisted(() => ({ validateWalletHistoryReadiness: vi.fn((value) => value) }));
const catalogMocks = vi.hoisted(() => ({
  runs: [] as WalletIngestionRunCatalogItem[],
  truncated: false,
  loading: false,
  error: null as string | null,
  refresh: vi.fn(),
}));

vi.mock("../api", () => apiMocks);
vi.mock("../useWalletRunCatalog", () => ({ useWalletRunCatalog: () => catalogMocks }));
vi.mock("../walletHistoryReadiness", () => ({
  validateWalletHistoryReadiness: readinessMocks.validateWalletHistoryReadiness,
  historyCoveragePercent: (layer: { selected_run_count: number; included_run_count: number }) => Math.round(layer.included_run_count / layer.selected_run_count * 100),
}));

import GramHistoryView from "./GramHistoryView";

function catalogRun(id: string, hint = "UQsame…cope"): WalletIngestionRunCatalogItem {
  return {
    run_id: id,
    wallet_hint: hint,
    time_window: id === "3" ? "7d" : "24h",
    created_at: `2026-07-${20 + Number(id)}T12:00:00Z`,
    status: "success",
    data_mode: "mock",
  };
}

function layer(stream: "transactions" | "account_events") {
  return {
    stream_key: stream,
    selected_run_count: 2,
    included_run_count: 1,
    selected_run_coverage_state: "partial",
    gap_intervals: [],
    overlap_intervals: [],
    state: "contiguous_selected_span",
    covered_duration_microseconds: "3600000000",
  };
}

function result(): WalletHistoryReadinessResponse {
  return {
    run_ids: [3, 1],
    wallet_address: "UQsame-wallet-scope",
    coverage: {
      activity_observations: 14,
      transaction_observations: 6,
      transaction_observations_with_exact_identity: 4,
      transaction_identity_coverage_state: "incomplete",
      event_action_observations: 8,
      event_action_observations_with_provider_scoped_identity: 6,
      event_action_identity_coverage_state: "incomplete",
      addressed_non_ton_swap_legs: 2,
      non_ton_swap_legs: 2,
      asset_address_coverage_state: "complete",
      same_run_fee_hash_match_candidates: 1,
      fee_link_candidate_swaps: 2,
      fee_hash_match_coverage_state: "incomplete",
    },
    bounded_interval_coverage: {
      low_level_transactions: layer("transactions"),
      provider_display_events: layer("account_events"),
    },
    blockers: [{ code: "history_completeness_unverified", reason: "Activity before the selected span remains unknown.", run_ids: [3, 1] }],
    note: "Diagnostic evidence only.",
  } as unknown as WalletHistoryReadinessResponse;
}

beforeEach(() => {
  vi.clearAllMocks();
  catalogMocks.runs = [catalogRun("3"), catalogRun("2", "UQother…cope"), catalogRun("1")];
  catalogMocks.loading = false;
  catalogMocks.error = null;
  apiMocks.inspectWalletHistoryReadiness.mockResolvedValue(result());
});

afterEach(cleanup);

describe("GramHistoryView", () => {
  it("prefilters one wallet, inspects the exact selected scope and explains blockers", async () => {
    const user = userEvent.setup();
    render(<GramHistoryView activeRun={null} onOpenActivity={vi.fn()} />);
    const inspect = screen.getByRole("button", { name: "Inspect history evidence" });
    await waitFor(() => expect((inspect as HTMLButtonElement).disabled).toBe(false));
    expect((screen.getByRole("button", { name: /Run #2/ }) as HTMLButtonElement).disabled).toBe(true);

    await user.click(inspect);
    await waitFor(() => expect(apiMocks.inspectWalletHistoryReadiness).toHaveBeenCalledWith(
      { target_run_id: 3, run_ids: [3, 1] },
      expect.any(AbortSignal),
    ));
    expect(await screen.findByText("Coverage remains bounded")).toBeTruthy();
    expect(screen.getByText("1 explicit blocker")).toBeTruthy();
    expect(screen.getByText("Full history: no")).toBeTruthy();
  });

  it("resets the scope when another wallet becomes the target", async () => {
    const user = userEvent.setup();
    render(<GramHistoryView activeRun={null} onOpenActivity={vi.fn()} />);
    const otherMain = screen.getByRole("button", { name: /Run #2/ });
    const otherRow = otherMain.closest("article");
    expect(otherRow).not.toBeNull();
    await user.click(within(otherRow as HTMLElement).getByRole("button", { name: "Use as target" }));

    await waitFor(() => expect(screen.getByText(/Create another mock run for wallet UQother/)).toBeTruthy());
    expect((screen.getByRole("button", { name: "Inspect history evidence" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("opens Activity from the empty state without calling readiness", async () => {
    catalogMocks.runs = [];
    const onOpenActivity = vi.fn();
    const user = userEvent.setup();
    render(<GramHistoryView activeRun={null} onOpenActivity={onOpenActivity} />);
    await user.click(screen.getByRole("button", { name: "Open activity" }));
    expect(onOpenActivity).toHaveBeenCalledOnce();
    expect(apiMocks.inspectWalletHistoryReadiness).not.toHaveBeenCalled();
  });
});
