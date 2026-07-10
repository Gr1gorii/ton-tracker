export type ParsedRunIds = { runIds: number[] } | { error: string };

export function parseSelectedRunIds(
  input: string,
  targetRunId: number,
): ParsedRunIds {
  const tokens = input
    .split(/[\s,]+/)
    .map((token) => token.trim())
    .filter(Boolean);
  const invalid = tokens.filter((token) => {
    if (!/^[1-9][0-9]*$/.test(token)) return true;
    const value = Number(token);
    return !Number.isSafeInteger(value) || value <= 0;
  });
  if (invalid.length > 0) {
    return { error: `Not valid run IDs: ${invalid.join(", ")}.` };
  }

  const otherIds = Array.from(new Set(tokens.map(Number))).filter(
    (runId) => runId !== targetRunId,
  );
  if (otherIds.length < 1) {
    return { error: "Add at least one run ID other than the target run." };
  }
  if (otherIds.length > 49) {
    return { error: "At most 49 other run IDs can be inspected." };
  }
  return { runIds: [targetRunId, ...otherIds] };
}
