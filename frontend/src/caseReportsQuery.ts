import { isWalletCaseSnapshotPublicId } from "./walletCaseActivity";
import { isWalletCaseReportPublicId } from "./walletCaseReportRevisions";

export interface CaseReportsUrlState {
  snapshot: string | null;
  revision: string | null;
  baseline: string | null;
}

export const EMPTY_CASE_REPORTS_URL_STATE: CaseReportsUrlState = {
  snapshot: null,
  revision: null,
  baseline: null,
};

export function readCaseReportsUrlState(search = window.location.search): {
  state: CaseReportsUrlState;
  error: string | null;
} {
  const params = new URLSearchParams(search);
  if ([...params.keys()].some((key) => key !== "snapshot" && key !== "revision" && key !== "baseline")) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports URL accepts only snapshot, revision and baseline." };
  }
  const snapshots = params.getAll("snapshot");
  const revisions = params.getAll("revision");
  const baselines = params.getAll("baseline");
  if (snapshots.length > 1 || revisions.length > 1 || baselines.length > 1) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports URL parameters must be provided at most once." };
  }
  const snapshot = snapshots[0] ?? null;
  const revision = revisions[0] ?? null;
  const baseline = baselines[0] ?? null;
  if (snapshot !== null && (snapshot !== snapshot.trim() || !isWalletCaseSnapshotPublicId(snapshot))) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports snapshot must be a canonical UUIDv4." };
  }
  if (revision !== null && (revision !== revision.trim() || !isWalletCaseReportPublicId(revision))) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports revision must be a content-addressed report ID." };
  }
  if (baseline !== null && (baseline !== baseline.trim() || !isWalletCaseReportPublicId(baseline))) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "Reports baseline must be a content-addressed report ID." };
  }
  if (revision !== null && snapshot === null) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "A saved report revision requires its pinned snapshot." };
  }
  if (baseline !== null && revision === null) {
    return { state: EMPTY_CASE_REPORTS_URL_STATE, error: "A comparison baseline requires a selected report revision." };
  }
  return { state: { snapshot, revision, baseline }, error: null };
}

export function caseReportsSearch(state: CaseReportsUrlState): string {
  if (state.snapshot !== null && !isWalletCaseSnapshotPublicId(state.snapshot)) throw new Error("Reports snapshot must be a canonical UUIDv4");
  if (state.revision !== null && !isWalletCaseReportPublicId(state.revision)) throw new Error("Reports revision must be a content-addressed report ID");
  if (state.baseline !== null && !isWalletCaseReportPublicId(state.baseline)) throw new Error("Reports baseline must be a content-addressed report ID");
  if (state.revision !== null && state.snapshot === null) throw new Error("Reports revision requires a pinned snapshot");
  if (state.baseline !== null && state.revision === null) throw new Error("Reports baseline requires a selected revision");
  const params = new URLSearchParams();
  if (state.snapshot !== null) params.set("snapshot", state.snapshot);
  if (state.revision !== null) params.set("revision", state.revision);
  if (state.baseline !== null) params.set("baseline", state.baseline);
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}
