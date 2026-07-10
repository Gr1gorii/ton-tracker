import type {
  TimeWindow,
  WalletIngestionRunResponse,
  WalletIngestionSurface,
} from "./types";

const ALLOWED_SURFACES = new Set<WalletIngestionSurface>([
  "transfers",
  "transactions",
  "swaps",
  "balances",
  "jettons",
]);

export interface RestoredStoredRunControls {
  walletAddress: string;
  timeWindow: TimeWindow;
  customStart: string;
  customEnd: string;
  canonicalCustomStart: string;
  canonicalCustomEnd: string;
  surfaces: WalletIngestionSurface[];
}

export function parseStoredRunId(value: string): number | null {
  const cleaned = value.trim();
  if (!/^[1-9][0-9]*$/.test(cleaned)) return null;
  const parsed = Number(cleaned);
  return Number.isSafeInteger(parsed) && parsed > 0 ? parsed : null;
}

export function requestSignature(
  walletAddress: string,
  timeWindow: TimeWindow,
  customStart: string,
  customEnd: string,
  surfaces: WalletIngestionSurface[],
): string {
  return JSON.stringify({
    walletAddress: walletAddress.trim(),
    timeWindow,
    customStart: canonicalDateTime(customStart),
    customEnd: canonicalDateTime(customEnd),
    surfaces: [...surfaces].sort(),
  });
}

export function restoreStoredRunControls(
  result: WalletIngestionRunResponse,
  requestedRunId: number,
): RestoredStoredRunControls {
  if (
    result.run_id !== requestedRunId ||
    !Number.isSafeInteger(result.run_id) ||
    requestedRunId <= 0
  ) {
    throw new Error("Stored run response did not match the requested run ID.");
  }
  const walletAddress = result.wallet_address.trim();
  if (!walletAddress) {
    throw new Error("Stored run response is missing its wallet address.");
  }
  if (!isTimeWindow(result.time_window)) {
    throw new Error("Stored run uses an unsupported time window.");
  }
  if (
    !Array.isArray(result.requested_surfaces) ||
    result.requested_surfaces.length === 0 ||
    new Set(result.requested_surfaces).size !== result.requested_surfaces.length ||
    result.requested_surfaces.some((surface) => !ALLOWED_SURFACES.has(surface))
  ) {
    throw new Error("Stored run has invalid requested-surface metadata.");
  }
  if (Number.isNaN(new Date(result.created_at).getTime())) {
    throw new Error("Stored run response has an invalid creation timestamp.");
  }

  let customStart = "";
  let customEnd = "";
  let canonicalCustomStart = "";
  let canonicalCustomEnd = "";
  if (result.time_window === "custom") {
    if (!result.custom_start || !result.custom_end) {
      throw new Error("Stored custom run is missing its exact time bounds.");
    }
    customStart = toDateTimeLocalValue(result.custom_start);
    customEnd = toDateTimeLocalValue(result.custom_end);
    canonicalCustomStart = canonicalDateTime(result.custom_start);
    canonicalCustomEnd = canonicalDateTime(result.custom_end);
  }

  return {
    walletAddress,
    timeWindow: result.time_window,
    customStart,
    customEnd,
    canonicalCustomStart,
    canonicalCustomEnd,
    surfaces: [...result.requested_surfaces],
  };
}

function isTimeWindow(value: string): value is TimeWindow {
  return value === "24h" || value === "3d" || value === "7d" || value === "custom";
}

function canonicalDateTime(value: string): string {
  if (!value) return "";
  const canonicalUtc = value.trim().match(
    /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.([0-9]{1,6}))?Z$/,
  );
  if (canonicalUtc && !Number.isNaN(new Date(value).getTime())) {
    const fraction = (canonicalUtc[2] ?? "").replace(/0+$/, "");
    return `${canonicalUtc[1]}${fraction ? `.${fraction}` : ""}Z`;
  }
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value.trim() : parsed.toISOString();
}

function toDateTimeLocalValue(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    throw new Error("Stored custom run contains an invalid time bound.");
  }
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 23);
  return local.endsWith(".000") ? local.slice(0, 19) : local;
}
