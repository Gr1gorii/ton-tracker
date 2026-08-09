// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WalletCase } from "../walletCase";

const apiMocks = vi.hoisted(() => ({
  createWalletCaseSync: vi.fn(),
  getWalletCase: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import GramCaseSummary from "./GramCaseSummary";

const CASE_ID = "550e8400-e29b-41d4-a716-446655440000";
const SYNC_ID = "550e8400-e29b-41d4-b716-446655440001";
const ALL_SURFACES = [
  "transfers",
  "transactions",
  "swaps",
  "balances",
  "jettons",
] as const;

function walletCaseFixture(overrides: Partial<WalletCase> = {}): WalletCase {
  return {
    public_id: CASE_ID,
    network: "ton-mainnet",
    data_environment: "demo",
    canonical_wallet_key: `0:${"a".repeat(64)}`,
    identity_version: "ton_std_address_v1",
    display_address: "EQC-demo-wallet",
    label: null,
    note: null,
    created_at: "2026-08-09T12:00:00Z",
    updated_at: "2026-08-09T12:01:00Z",
    latest_sync: {
      public_id: SYNC_ID,
      state: "succeeded",
      stage: "completed",
      progress: { current: 1, total: 1 },
      provider: "mock_wallet_activity",
      data_mode: "mock",
      requested_scope: {
        time_window: "24h",
        start_at: "2026-08-08T12:00:00Z",
        end_at: "2026-08-09T12:00:00Z",
        surfaces: [...ALL_SURFACES],
      },
      coverage: {
        state: "unknown",
        requested_start_at: "2026-08-08T12:00:00Z",
        requested_end_at: "2026-08-09T12:00:00Z",
        requested_surfaces: [...ALL_SURFACES],
        unavailable_surfaces: [],
        incomplete_surfaces: [],
        streams: [],
        full_history_proven: false,
      },
      summary: {
        activity_counts: { transfers: 2, transactions: 3, swaps: 1, balances: 2 },
        failed_transaction_count: 1,
        warning_count: 2,
        portfolio_snapshot: {
          total_balance_usd: "950.42",
          priced_assets: 2,
          unpriced_assets: 1,
        },
      },
      limitations: [
        {
          code: "bounded_interval_not_full_history",
          message: "The selected interval is not full wallet history.",
        },
      ],
      message: "Demo sync completed.",
      created_at: "2026-08-09T12:00:00Z",
      started_at: "2026-08-09T12:00:00Z",
      completed_at: "2026-08-09T12:01:00Z",
    },
    summary: {
      activity_counts: { transfers: 2, transactions: 3, swaps: 1, balances: 2 },
      failed_transaction_count: 1,
      warning_count: 2,
      portfolio_snapshot: {
        total_balance_usd: "950.42",
        priced_assets: 2,
        unpriced_assets: 1,
      },
    },
    limitations: [
      {
        code: "bounded_interval_not_full_history",
        message: "The selected interval is not full wallet history.",
      },
    ],
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(cleanup);

describe("GramCaseSummary", () => {
  it("shows persisted case identity and honest empty bounded-sync state", async () => {
    apiMocks.getWalletCase.mockResolvedValue(
      walletCaseFixture({
        latest_sync: null,
        summary: {
          activity_counts: { transfers: 0, transactions: 0, swaps: 0, balances: 0 },
          failed_transaction_count: 0,
          warning_count: 0,
          portfolio_snapshot: { total_balance_usd: null, priced_assets: 0, unpriced_assets: 0 },
        },
        limitations: [{ code: "not_synchronized", message: "This case has not been synchronized yet." }],
      }),
    );

    render(<GramCaseSummary caseId={CASE_ID} />);

    expect(await screen.findByRole("heading", { name: "EQC-demo-wallet" })).toBeTruthy();
    expect(screen.getAllByText("Demo data")).toHaveLength(2);
    expect(screen.getByText("TON mainnet")).toBeTruthy();
    expect(screen.getByText("Not proven")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Not started" })).toBeTruthy();
    expect(screen.getByText(/No sync has been run for this case/)).toBeTruthy();
    expect(screen.queryByText(/Run #/)).toBeNull();
  });

  it("runs the explicit 24-hour scope and refetches the case summary", async () => {
    const empty = walletCaseFixture({
      latest_sync: null,
      summary: {
        activity_counts: { transfers: 0, transactions: 0, swaps: 0, balances: 0 },
        failed_transaction_count: 0,
        warning_count: 0,
        portfolio_snapshot: { total_balance_usd: null, priced_assets: 0, unpriced_assets: 0 },
      },
      limitations: [{ code: "not_synchronized", message: "This case has not been synchronized yet." }],
    });
    const synced = walletCaseFixture();
    apiMocks.getWalletCase
      .mockResolvedValueOnce(empty)
      .mockResolvedValueOnce(synced);
    apiMocks.createWalletCaseSync.mockResolvedValue(synced.latest_sync);
    const user = userEvent.setup();

    render(<GramCaseSummary caseId={CASE_ID} />);
    await screen.findByRole("heading", { name: "Not started" });
    await user.click(screen.getByRole("button", { name: "Sync last 24 hours" }));

    await waitFor(() => expect(apiMocks.createWalletCaseSync).toHaveBeenCalledWith(
      CASE_ID,
      { time_window: "24h", surfaces: [...ALL_SURFACES] },
    ));
    await waitFor(() => expect(apiMocks.getWalletCase).toHaveBeenCalledTimes(2));
    expect(apiMocks.getWalletCase.mock.calls[0][0]).toBe(CASE_ID);
    expect(apiMocks.getWalletCase.mock.calls[0][1]).toBeInstanceOf(AbortSignal);
    expect(apiMocks.getWalletCase.mock.calls[1]).toEqual([CASE_ID, undefined]);

    expect(await screen.findByRole("heading", { name: "succeeded" })).toBeTruthy();
    expect(screen.getAllByText("Coverage not established").length).toBeGreaterThan(0);
    const observedMetric = screen.getByText("Returned activity rows").closest("article");
    expect(observedMetric?.textContent).toContain("6");
    expect(screen.queryByText(/Run #/)).toBeNull();
  });

  it("renders no summary metrics when case validation fails closed", async () => {
    apiMocks.getWalletCase.mockRejectedValue(
      new Error("wallet case environment does not match its latest sync evidence"),
    );

    render(<GramCaseSummary caseId={CASE_ID} />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(
      "wallet case environment does not match its latest sync evidence",
    );
    expect(screen.queryByText("Returned activity rows")).toBeNull();
    expect(screen.queryByRole("button", { name: "Sync last 24 hours" })).toBeNull();
  });

  it("shows migrated compact-summary gaps as unavailable instead of zero activity", async () => {
    const base = walletCaseFixture();
    if (!base.latest_sync) throw new Error("fixture must include a sync");
    const zeroSummary = {
      activity_counts: { transfers: 0, transactions: 0, swaps: 0, balances: 0 },
      failed_transaction_count: 0,
      warning_count: 0,
      portfolio_snapshot: { total_balance_usd: null, priced_assets: 0, unpriced_assets: 0 },
    };
    const limitations = [
      ...base.limitations,
      {
        code: "summary_unavailable",
        message: "Zero placeholders are not evidence of no activity.",
      },
    ];
    apiMocks.getWalletCase.mockResolvedValue(walletCaseFixture({
      latest_sync: {
        ...base.latest_sync,
        summary: zeroSummary,
        limitations,
        message: "Compact summary is unavailable for this pre-0016 synchronization.",
      },
      summary: zeroSummary,
      limitations,
    }));

    render(<GramCaseSummary caseId={CASE_ID} />);

    expect(await screen.findByRole("heading", { name: "succeeded" })).toBeTruthy();
    expect(screen.getAllByText("Not available").length).toBeGreaterThanOrEqual(4);
    expect(screen.getByText(/Compact summary is unavailable/)).toBeTruthy();
    expect(screen.getByText(/Zero placeholders are not evidence/)).toBeTruthy();
  });
});
