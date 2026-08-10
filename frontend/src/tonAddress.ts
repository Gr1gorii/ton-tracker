const RAW_TON_ADDRESS = /^((?:0|[1-9][0-9]{0,9}|-[1-9][0-9]{0,9})):[0-9a-f]{64}$/;
const MIN_SIGNED_INT32 = -2_147_483_648n;
const MAX_SIGNED_INT32 = 2_147_483_647n;

export function isCanonicalRawTonAddress(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = RAW_TON_ADDRESS.exec(value);
  if (!match) return false;
  const workchain = BigInt(match[1]);
  return workchain >= MIN_SIGNED_INT32 && workchain <= MAX_SIGNED_INT32;
}
