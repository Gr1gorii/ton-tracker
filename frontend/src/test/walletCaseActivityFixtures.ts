import type {
  WalletCaseActivityDetailResponse,
  WalletCaseActivityFilters,
  WalletCaseActivityItem,
  WalletCaseActivityResponse,
} from "../walletCaseActivity";
import { CASE_ID, coverageFixture, SYNC_ID } from "./walletCaseFixtures";

export const ACTIVITY_ID = `act_${"1".repeat(64)}`;
export const SECOND_ACTIVITY_ID = `act_${"2".repeat(64)}`;
export const ASSET_ID = `asset_${"3".repeat(64)}`;
export const TRANSACTION_HASH = "4".repeat(64);

export function activityFiltersFixture(): WalletCaseActivityFilters {
  return {
    kinds: [],
    directions: [],
    outcomes: [],
    from_at: null,
    to_at: null,
    asset_id: null,
    protocol_id: null,
    counterparty: null,
    data_origins: [],
    sort: "newest",
  };
}

export function activityItemFixture(
  overrides: Partial<WalletCaseActivityItem> = {},
): WalletCaseActivityItem {
  return {
    public_id: ACTIVITY_ID,
    kind: "transaction",
    occurred_at: "2026-08-09T11:00:00Z",
    logical_time: "45000000000000",
    direction: null,
    outcome: "success",
    counterparty: null,
    assets: [],
    protocol: null,
    transaction: { linkage: "unknown", hash: null, event_id: null },
    details: { kind: "transaction", fee_ton: "0.01" },
    provenance: {
      data_origin: "demo_fixture",
      evidence_level: "fixture",
      provider: "mock_wallet_activity",
      source_status: "fixture",
      identity_assurance: "unavailable",
      deduplication_basis: "none",
      observation_count: 1,
      suppressed_count: 0,
      first_seen_sync_public_id: SYNC_ID,
      last_seen_sync_public_id: SYNC_ID,
    },
    limitations: [{ code: "demo_fixture_not_chain_data", message: "This row is a deterministic fixture." }],
    ...overrides,
  };
}

export function activityResponseFixture(
  overrides: Partial<WalletCaseActivityResponse> = {},
): WalletCaseActivityResponse {
  const item = activityItemFixture();
  return {
    case_public_id: CASE_ID,
    snapshot: {
      public_id: SYNC_ID,
      state: "succeeded",
      completed_at: "2026-08-09T12:01:00Z",
      data_mode: "mock",
      provider: "mock_wallet_activity",
      requested_period: {
        start_at: "2026-08-08T12:00:00Z",
        end_at: "2026-08-09T12:00:00Z",
      },
      coverage: coverageFixture(),
    },
    filters: activityFiltersFixture(),
    aggregate: {
      total_items: 1,
      transactions: 1,
      transfers: 0,
      swaps: 0,
      failed_transactions: 0,
      source_sync_count: 1,
      suppressed_duplicate_observations: 0,
      conflicted_identity_count: 0,
    },
    observed_period: { start_at: "2026-08-09T11:00:00Z", end_at: "2026-08-09T11:00:00.000001Z" },
    gaps: [],
    limitations: [{ code: "demo_fixture_not_chain_data", message: "Demo fixtures are not live TON observations." }],
    items: [item],
    page: { limit: 50, has_more: false, next_cursor: null },
    ...overrides,
  };
}

export function unsynchronizedActivityResponseFixture(): WalletCaseActivityResponse {
  return {
    ...activityResponseFixture(),
    snapshot: null,
    aggregate: {
      total_items: 0,
      transactions: 0,
      transfers: 0,
      swaps: 0,
      failed_transactions: 0,
      source_sync_count: 0,
      suppressed_duplicate_observations: 0,
      conflicted_identity_count: 0,
    },
    observed_period: null,
    gaps: [{ code: "not_synchronized", surface: null, start_at: null, end_at: null, message: "No usable snapshot exists." }],
    limitations: [{ code: "not_synchronized", message: "No usable snapshot exists." }],
    items: [],
    page: { limit: 50, has_more: false, next_cursor: null },
  };
}

export function activityDetailFixture(): WalletCaseActivityDetailResponse {
  return {
    case_public_id: CASE_ID,
    snapshot_public_id: SYNC_ID,
    item: activityItemFixture(),
    source_observations: [{
      sync_public_id: SYNC_ID,
      observed_at: "2026-08-09T11:00:00Z",
      provider: "mock_wallet_activity",
      source_status: "fixture",
      data_origin: "demo_fixture",
    }],
    sources_truncated: false,
  };
}
