const RFC3339_INSTANT = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,9}))?(Z|([+-])(\d{2}):(\d{2}))$/;

export function parseRfc3339Instant(
  value: unknown,
  {
    requireUtc = false,
    maximumFractionDigits = 6,
  }: { requireUtc?: boolean; maximumFractionDigits?: number } = {},
): bigint | null {
  if (typeof value !== "string") return null;
  const match = RFC3339_INSTANT.exec(value);
  if (!match || (match[7]?.length ?? 0) > maximumFractionDigits) return null;

  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6]);
  const zone = match[8];
  const offsetHour = zone === "Z" ? 0 : Number(match[10]);
  const offsetMinute = zone === "Z" ? 0 : Number(match[11]);
  if (
    year === 0 || offsetHour > 23 || offsetMinute > 59 ||
    (requireUtc && zone !== "Z" && zone !== "+00:00")
  ) return null;

  const local = new Date(0);
  local.setUTCHours(0, 0, 0, 0);
  local.setUTCFullYear(year, month - 1, day);
  local.setUTCHours(hour, minute, second, 0);
  if (
    local.getUTCFullYear() !== year || local.getUTCMonth() !== month - 1 ||
    local.getUTCDate() !== day || local.getUTCHours() !== hour ||
    local.getUTCMinutes() !== minute || local.getUTCSeconds() !== second
  ) return null;

  const offsetDirection = match[9] === "-" ? -1 : 1;
  const offsetMilliseconds = offsetDirection * (offsetHour * 60 + offsetMinute) * 60_000;
  const epochMilliseconds = local.getTime() - offsetMilliseconds;
  if (!Number.isSafeInteger(epochMilliseconds)) return null;
  const fractionNanoseconds = BigInt((match[7] ?? "").padEnd(9, "0"));
  return BigInt(epochMilliseconds) * 1_000_000n + fractionNanoseconds;
}
