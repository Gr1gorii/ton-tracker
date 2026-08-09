import type {
  WalletCase,
  WalletCaseCoverage,
  WalletCaseLimitation,
  WalletCaseSummary,
  WalletCaseSync,
  WalletCaseSyncResult,
} from "../walletCase";

export const CASE_ID = "550e8400-e29b-41d4-a716-446655440000";
export const SYNC_ID = "550e8400-e29b-41d4-b716-446655440001";
export const OLDER_SYNC_ID = "550e8400-e29b-41d4-b716-446655440002";
export const IDEMPOTENCY_KEY = "550e8400-e29b-41d4-a716-446655440003";
export const ALL_SURFACES = [
  "transfers",
  "transactions",
  "swaps",
  "balances",
  "jettons",
] as const;

export function zeroSummaryFixture(): WalletCaseSummary {
  return {
    activity_counts: { transfers: 0, transactions: 0, swaps: 0, balances: 0 },
    failed_transaction_count: 0,
    warning_count: 0,
    portfolio_snapshot: { total_balance_usd: null, priced_assets: 0, unpriced_assets: 0 },
  };
}

export function summaryFixture(): WalletCaseSummary {
  return {
    activity_counts: { transfers: 2, transactions: 3, swaps: 1, balances: 2 },
    failed_transaction_count: 1,
    warning_count: 2,
    portfolio_snapshot: {
      total_balance_usd: "950.42",
      priced_assets: 2,
      unpriced_assets: 1,
    },
  };
}

export function limitationFixture(): WalletCaseLimitation[] {
  return [{
    code: "bounded_interval_not_full_history",
    message: "The selected interval is not full wallet history.",
  }];
}

export function coverageFixture(): WalletCaseCoverage {
  return {
    state: "unknown",
    requested_start_at: "2026-08-08T12:00:00Z",
    requested_end_at: "2026-08-09T12:00:00Z",
    requested_surfaces: [...ALL_SURFACES],
    unavailable_surfaces: [],
    incomplete_surfaces: [],
    streams: [],
    full_history_proven: false,
  };
}

export function resultFixture(): WalletCaseSyncResult {
  return {
    summary: summaryFixture(),
    coverage: coverageFixture(),
    limitations: limitationFixture(),
    message: "Demo sync completed.",
  };
}

export function succeededSyncFixture(
  overrides: Partial<WalletCaseSync> = {},
): WalletCaseSync {
  const result = resultFixture();
  return {
    public_id: SYNC_ID,
    case_public_id: CASE_ID,
    state: "succeeded",
    stage: "completed",
    status_version: 4,
    poll_after_ms: 1_000,
    cancel_requested: false,
    progress: { current: 5, total: 5 },
    provider: "mock_wallet_activity",
    data_mode: "mock",
    requested_scope: {
      time_window: "24h",
      start_at: "2026-08-08T12:00:00Z",
      end_at: "2026-08-09T12:00:00Z",
      surfaces: [...ALL_SURFACES],
    },
    coverage: result.coverage,
    summary: result.summary,
    limitations: result.limitations,
    message: result.message,
    retry: null,
    error: null,
    result,
    created_at: "2026-08-09T12:00:00Z",
    updated_at: "2026-08-09T12:01:00Z",
    started_at: "2026-08-09T12:00:01Z",
    completed_at: "2026-08-09T12:01:00Z",
    ...overrides,
  };
}

export function activeSyncFixture(
  state: "queued" | "running" = "running",
  overrides: Partial<WalletCaseSync> = {},
): WalletCaseSync {
  const limitations = [{
    code: "sync_in_progress",
    message: "A bounded synchronization is still in progress.",
  }];
  return {
    ...succeededSyncFixture(),
    state,
    stage: state === "queued" ? "queued" : "ingesting",
    status_version: state === "queued" ? 1 : 2,
    progress: { current: state === "queued" ? 0 : 2, total: 5 },
    summary: zeroSummaryFixture(),
    coverage: coverageFixture(),
    limitations,
    message: state === "queued" ? "Sync queued." : "Acquiring bounded evidence.",
    retry: null,
    error: null,
    result: null,
    updated_at: state === "queued" ? "2026-08-09T12:00:00Z" : "2026-08-09T12:00:15Z",
    started_at: state === "queued" ? null : "2026-08-09T12:00:01Z",
    completed_at: null,
    ...overrides,
  };
}

export function retryWaitSyncFixture(
  overrides: Partial<WalletCaseSync> = {},
): WalletCaseSync {
  return activeSyncFixture("queued", {
    stage: "retry_wait",
    status_version: 3,
    message: "Provider request will retry.",
    retry: {
      attempt: 2,
      max_attempts: 4,
      retry_at: "2026-08-09T12:00:45Z",
      reason_code: "provider_unavailable",
      message_safe: "The provider is temporarily unavailable.",
    },
    ...overrides,
  });
}

export function failedSyncFixture(
  overrides: Partial<WalletCaseSync> = {},
): WalletCaseSync {
  return activeSyncFixture("running", {
    state: "failed",
    stage: "failed",
    status_version: 4,
    progress: { current: 2, total: 5 },
    message: "The bounded synchronization failed.",
    error: {
      code: "provider_unavailable",
      message_safe: "The provider did not respond after safe retries.",
      retryable: true,
    },
    updated_at: "2026-08-09T12:01:00Z",
    completed_at: "2026-08-09T12:01:00Z",
    ...overrides,
  });
}

export function walletCaseFixture({
  latestAttempt = succeededSyncFixture(),
  activeSync,
  currentSnapshot = succeededSyncFixture(),
  overrides = {},
}: {
  latestAttempt?: WalletCaseSync | null;
  activeSync?: WalletCaseSync | null;
  currentSnapshot?: WalletCaseSync | null;
  overrides?: Partial<WalletCase>;
} = {}): WalletCase {
  const derivedActive = activeSync === undefined && latestAttempt &&
    (latestAttempt.state === "queued" || latestAttempt.state === "running")
    ? latestAttempt
    : activeSync ?? null;
  const published = currentSnapshot?.result ?? null;
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
    latest_sync: latestAttempt,
    latest_sync_attempt: latestAttempt,
    active_sync: derivedActive,
    current_snapshot: currentSnapshot,
    summary: published?.summary ?? zeroSummaryFixture(),
    limitations: published?.limitations ?? [{
      code: latestAttempt ? "sync_in_progress" : "not_synchronized",
      message: latestAttempt
        ? "No usable snapshot has been published yet."
        : "This case has not been synchronized yet.",
    }],
    ...overrides,
  };
}

export function emptyWalletCaseFixture(overrides: Partial<WalletCase> = {}): WalletCase {
  return walletCaseFixture({
    latestAttempt: null,
    activeSync: null,
    currentSnapshot: null,
    overrides,
  });
}
