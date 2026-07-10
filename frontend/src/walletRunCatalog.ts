import type {
  TimeWindow,
  WalletIngestionRunCatalogItem,
  WalletIngestionRunCatalogResponse,
  WalletIngestionStatus,
} from "./types";

const MAX_SIGNED_64_BIT_ID = 9_223_372_036_854_775_807n;
const ITEM_KEYS = [
  "created_at",
  "data_mode",
  "run_id",
  "status",
  "time_window",
  "wallet_hint",
] as const;
const RESPONSE_KEYS = ["limit", "runs", "truncated"] as const;
const TIME_WINDOWS = new Set<TimeWindow>(["24h", "3d", "7d", "custom"]);
const RUN_STATUSES = new Set<WalletIngestionStatus>([
  "planned",
  "queued",
  "running",
  "success",
  "partial",
  "error",
  "stale",
]);

export function validateWalletRunCatalogResponse(
  value: unknown,
  requestedLimit: number,
): WalletIngestionRunCatalogResponse {
  if (!isRecord(value) || !hasExactKeys(value, RESPONSE_KEYS)) {
    throw new Error("Recent-run catalog returned an unexpected response shape.");
  }
  if (
    typeof value.limit !== "number" ||
    !Number.isSafeInteger(value.limit) ||
    value.limit !== requestedLimit ||
    value.limit < 1 ||
    value.limit > 50 ||
    typeof value.truncated !== "boolean" ||
    !Array.isArray(value.runs) ||
    value.runs.length > value.limit ||
    (value.truncated && value.runs.length !== value.limit)
  ) {
    throw new Error("Recent-run catalog returned invalid page metadata.");
  }

  const runs = value.runs.map(validateCatalogItem);
  const ids = runs.map((run) => BigInt(run.run_id));
  if (ids.some((id, index) => index > 0 && ids[index - 1] <= id)) {
    throw new Error("Recent-run catalog IDs are not unique newest-first values.");
  }

  return {
    runs,
    limit: value.limit,
    truncated: value.truncated,
  };
}

function validateCatalogItem(value: unknown): WalletIngestionRunCatalogItem {
  if (!isRecord(value) || !hasExactKeys(value, ITEM_KEYS)) {
    throw new Error("Recent-run catalog item returned an unexpected shape.");
  }
  if (
    typeof value.run_id !== "string" ||
    !/^[1-9][0-9]*$/.test(value.run_id) ||
    value.run_id.length > 19 ||
    BigInt(value.run_id) > MAX_SIGNED_64_BIT_ID
  ) {
    throw new Error("Recent-run catalog item has an invalid canonical run ID.");
  }
  if (
    typeof value.wallet_hint !== "string" ||
    !(
      value.wallet_hint === "stored…run" ||
      (value.wallet_hint.length === 11 && value.wallet_hint[6] === "…")
    )
  ) {
    throw new Error("Recent-run catalog item has an invalid wallet hint.");
  }
  if (
    typeof value.time_window !== "string" ||
    !TIME_WINDOWS.has(value.time_window as TimeWindow) ||
    typeof value.created_at !== "string" ||
    Number.isNaN(new Date(value.created_at).getTime()) ||
    typeof value.status !== "string" ||
    !RUN_STATUSES.has(value.status as WalletIngestionStatus) ||
    (value.data_mode !== "mock" && value.data_mode !== "real")
  ) {
    throw new Error("Recent-run catalog item has invalid stored metadata.");
  }

  return {
    run_id: value.run_id,
    wallet_hint: value.wallet_hint,
    time_window: value.time_window as TimeWindow,
    created_at: value.created_at,
    status: value.status as WalletIngestionStatus,
    data_mode: value.data_mode,
  };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  const keys = Object.keys(value).sort();
  const expected = [...allowed].sort();
  return (
    keys.length === expected.length &&
    keys.every((key, index) => key === expected[index])
  );
}
