import { describe, expect, it } from "vitest";
import {
  parseWalletCase,
  parseWalletCaseListResponse,
  parseWalletCaseUpsertResponse,
  type WalletCase,
} from "./walletCase";

const CASE_ID = "550e8400-e29b-41d4-a716-446655440000";
const SYNC_ID = "550e8400-e29b-41d4-b716-446655440001";

export function walletCaseFixture(overrides: Partial<WalletCase> = {}): WalletCase {
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
        surfaces: ["transactions", "balances"],
      },
      coverage: {
        state: "unknown",
        requested_start_at: "2026-08-08T12:00:00Z",
        requested_end_at: "2026-08-09T12:00:00Z",
        requested_surfaces: ["transactions", "balances"],
        unavailable_surfaces: [],
        incomplete_surfaces: [],
        streams: [],
        full_history_proven: false,
      },
      summary: {
        activity_counts: { transfers: 0, transactions: 3, swaps: 0, balances: 3 },
        failed_transaction_count: 0,
        warning_count: 1,
        portfolio_snapshot: {
          total_balance_usd: "950.42",
          priced_assets: 3,
          unpriced_assets: 0,
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
      activity_counts: { transfers: 0, transactions: 3, swaps: 0, balances: 3 },
      failed_transaction_count: 0,
      warning_count: 1,
      portfolio_snapshot: {
        total_balance_usd: "950.42",
        priced_assets: 3,
        unpriced_assets: 0,
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

describe("wallet case contracts", () => {
  it("accepts a bounded demo case without promoting full history", () => {
    const parsed = parseWalletCase(walletCaseFixture());
    expect(parsed.latest_sync?.coverage.full_history_proven).toBe(false);
    expect(parsed.summary.activity_counts.transactions).toBe(3);
  });

  it("fails closed when live case metadata contains mock evidence", () => {
    const value = walletCaseFixture({ data_environment: "live" });
    expect(() => parseWalletCase(value)).toThrow(/does not match/);
  });

  it("fails closed when bounded coverage claims full history", () => {
    const value = walletCaseFixture();
    const unsafe = {
      ...value,
      latest_sync: {
        ...value.latest_sync,
        coverage: { ...value.latest_sync?.coverage, full_history_proven: true },
      },
    };
    expect(() => parseWalletCase(unsafe)).toThrow(/cannot claim full wallet history/);
  });

  it("fails closed when coverage does not match the requested sync scope", () => {
    const value = walletCaseFixture();
    const unsafe = {
      ...value,
      latest_sync: {
        ...value.latest_sync,
        coverage: { ...value.latest_sync?.coverage, requested_surfaces: ["transactions"] },
      },
    };
    expect(() => parseWalletCase(unsafe)).toThrow(/does not match/);
  });

  it("fails closed when demo evidence claims bounded-complete coverage", () => {
    const value = walletCaseFixture();
    const unsafe = {
      ...value,
      latest_sync: {
        ...value.latest_sync,
        coverage: { ...value.latest_sync?.coverage, state: "bounded_complete" },
      },
    };
    expect(() => parseWalletCase(unsafe)).toThrow(/contradicts its evidence mode/);
  });

  it("fails closed when complete coverage contains gaps or incomplete streams", () => {
    const value = walletCaseFixture({ data_environment: "live" });
    const unsafe = {
      ...value,
      latest_sync: {
        ...value.latest_sync,
        data_mode: "real",
        coverage: {
          ...value.latest_sync?.coverage,
          state: "bounded_complete",
          incomplete_surfaces: ["transactions"],
          streams: [{
            provider: "tonapi_wallet_activity_live",
            stream_key: "account_transactions",
            completion_state: "incomplete",
            error_code: "page_cap_reached",
          }],
        },
      },
    };
    expect(() => parseWalletCase(unsafe)).toThrow(/complete coverage cannot contain/);
  });

  it("fails closed when requested coverage is empty or its gaps are out of scope", () => {
    const value = walletCaseFixture();
    const empty = {
      ...value,
      latest_sync: {
        ...value.latest_sync,
        requested_scope: { ...value.latest_sync?.requested_scope, surfaces: [] },
        coverage: { ...value.latest_sync?.coverage, requested_surfaces: [] },
      },
    };
    const outOfScope = {
      ...value,
      latest_sync: {
        ...value.latest_sync,
        coverage: {
          ...value.latest_sync?.coverage,
          unavailable_surfaces: ["swaps"],
        },
      },
    };
    expect(() => parseWalletCase(empty)).toThrow(/requested scope is invalid/);
    expect(() => parseWalletCase(outOfScope)).toThrow(/gaps do not match/);
  });

  it("fails closed when an unsynchronized case publishes non-zero evidence", () => {
    expect(() => parseWalletCase(walletCaseFixture({ latest_sync: null }))).toThrow(
      /unsynchronized wallet case/,
    );
  });

  it("fails closed when top-level summary is not from the latest sync", () => {
    const value = walletCaseFixture();
    expect(() => parseWalletCase({
      ...value,
      summary: {
        ...value.summary,
        activity_counts: { ...value.summary.activity_counts, transactions: 99 },
      },
    })).toThrow(/summary provenance/);
  });

  it("validates upsert and list envelopes", () => {
    expect(parseWalletCaseUpsertResponse({ created: true, case: walletCaseFixture() }).created).toBe(true);
    expect(
      parseWalletCaseListResponse({ cases: [walletCaseFixture()], limit: 20, truncated: false }).cases,
    ).toHaveLength(1);
  });
});
