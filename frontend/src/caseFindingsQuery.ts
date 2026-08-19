import { isWalletCaseSnapshotPublicId } from "./walletCaseActivity";

export interface CaseFindingsUrlState {
  snapshot: string | null;
}

export const EMPTY_CASE_FINDINGS_URL_STATE: CaseFindingsUrlState = { snapshot: null };

export function readCaseFindingsUrlState(search = window.location.search): {
  state: CaseFindingsUrlState;
  error: string | null;
} {
  const params = new URLSearchParams(search);
  if ([...params.keys()].some((key) => key !== "snapshot")) {
    return { state: EMPTY_CASE_FINDINGS_URL_STATE, error: "Findings URL accepts only the snapshot parameter." };
  }
  const values = params.getAll("snapshot");
  if (values.length > 1) {
    return { state: EMPTY_CASE_FINDINGS_URL_STATE, error: "Findings snapshot must be provided once." };
  }
  const snapshot = values[0] ?? null;
  if (snapshot !== null && (!isWalletCaseSnapshotPublicId(snapshot) || snapshot !== snapshot.trim())) {
    return { state: EMPTY_CASE_FINDINGS_URL_STATE, error: "Findings snapshot must be a canonical UUIDv4." };
  }
  return { state: { snapshot }, error: null };
}

export function caseFindingsSearch(state: CaseFindingsUrlState): string {
  if (state.snapshot === null) return "";
  if (!isWalletCaseSnapshotPublicId(state.snapshot)) throw new Error("Findings snapshot must be a canonical UUIDv4");
  return `?snapshot=${encodeURIComponent(state.snapshot)}`;
}
