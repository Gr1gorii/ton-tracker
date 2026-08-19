import { isWalletCaseSnapshotPublicId } from "./walletCaseActivity";
import { isWalletCaseReportPublicId } from "./walletCaseReportRevisions";

export interface CaseReportsUrlState {
  snapshot: string | null;
  revision: string | null;
}

export const EMPTY_CASE_REPORTS_URL_STATE: CaseReportsUrlState = {
  snapshot: null,
  revision: null,
};

export function readCaseReportsUrlState(search = window.location.search): {
  state: CaseReportsUrlState;
  error: string | null;
} {
  const params = new URLSearchParams(search);
  if ([...params.keys()].some((key) => key !== "snapshot" && key !== "revision")) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports URL accepts only snapshot and revision." };
  }
  const snapshots = params.getAll("snapshot");
  const revisions = params.getAll("revision");
  if (snapshots.length > 1 || revisions.length > 1) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports URL parameters must be provided at most once." };
  }
  const snapshot = snapshots[0] ?? null;
  const revision = revisions[0] ?? null;
  if (snapshot !== null && (snapshot !== snapshot.trim() || !isWalletCaseSnapshotPublicId(snapshot))) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports snapshot must be a canonical UUIDv4." };
  }
  if (revision !== null && (revision !== revision.trim() || !isWalletCaseReportPublicId(revision))) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports revision must be a content-addressed report ID." };
  }
  if (revision !== null && snapshot === null) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "A saved report revision requires its pinned snapshot." };
  }
  return { state: { snapshot, revision }, error: null };
}

export function caseReportsSearch(state: CaseReportsUrlState): string {
  if (state.snapshot !== null && !isWalletCaseSnapshotPublicId(state.snapshot)) throw new Error("Reports snapshot must be a canonical UUIDv4");
  if (state.revision !== null && !isWalletCaseReportPublicId(state.revision)) throw new Error("Reports revision must be a content-addressed report ID");
  if (state.revision !== null && state.snapshot === null) throw new Error("Reports revision requires a pinned snapshot");
  const params = new URLSearchParams();
  if (state.snapshot !== null) params.set("snapshot", state.snapshot);
  if (state.revision !== null) params.set("revision", state.revision);
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}
