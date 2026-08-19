import {
  isWalletCaseActivityPublicId,
  isWalletCaseSnapshotPublicId,
} from "./walletCaseActivity";

export interface CaseEvidenceUrlState {
  snapshot: string | null;
  activity: string | null;
  verification: string | null;
}

const ALLOWED_KEYS = new Set(["snapshot", "activity", "verification"]);

export const EMPTY_CASE_EVIDENCE_URL_STATE: CaseEvidenceUrlState = {
  snapshot: null,
  activity: null,
  verification: null,
};

export function parseCaseEvidenceSearch(search: string): CaseEvidenceUrlState {
  const params = new URLSearchParams(search);
  for (const key of params.keys()) {
    if (!ALLOWED_KEYS.has(key)) {
      throw new Error(`Evidence URL contains an unsupported “${key}” parameter.`);
    }
    if (params.getAll(key).length !== 1) {
      throw new Error(`Evidence URL contains more than one “${key}” parameter.`);
    }
  }

  const snapshot = optionalExact(params, "snapshot");
  const activity = optionalExact(params, "activity");
  const verification = optionalExact(params, "verification");

  if (snapshot !== null && !isWalletCaseSnapshotPublicId(snapshot)) {
    throw new Error("Evidence snapshot must be a canonical UUIDv4.");
  }
  if (activity !== null && !isWalletCaseActivityPublicId(activity)) {
    throw new Error("Evidence Activity ID is invalid.");
  }
  if (verification !== null && !isWalletCaseSnapshotPublicId(verification)) {
    throw new Error("Evidence verification ID must be a canonical UUIDv4.");
  }
  if (activity !== null && snapshot === null) {
    throw new Error("Evidence Activity selection requires a pinned snapshot.");
  }
  if (verification !== null && (snapshot === null || activity === null)) {
    throw new Error("Evidence verification selection requires its pinned snapshot and Activity ID.");
  }

  return { snapshot, activity, verification };
}

export function readCaseEvidenceUrlState(): { state: CaseEvidenceUrlState; error: string | null } {
  try {
    return { state: parseCaseEvidenceSearch(window.location.search), error: null };
  } catch (error) {
    return {
      state: EMPTY_CASE_EVIDENCE_URL_STATE,
      error: error instanceof Error ? error.message : "Evidence URL is invalid.",
    };
  }
}

export function caseEvidenceSearch(state: CaseEvidenceUrlState): string {
  if (state.snapshot !== null && !isWalletCaseSnapshotPublicId(state.snapshot)) {
    throw new Error("Evidence snapshot must be a canonical UUIDv4.");
  }
  if (state.activity !== null && !isWalletCaseActivityPublicId(state.activity)) {
    throw new Error("Evidence Activity ID is invalid.");
  }
  if (state.verification !== null && !isWalletCaseSnapshotPublicId(state.verification)) {
    throw new Error("Evidence verification ID must be a canonical UUIDv4.");
  }
  if (state.activity !== null && state.snapshot === null) {
    throw new Error("Evidence Activity selection requires a pinned snapshot.");
  }
  if (state.verification !== null && (state.snapshot === null || state.activity === null)) {
    throw new Error("Evidence verification selection requires its pinned snapshot and Activity ID.");
  }
  const params = new URLSearchParams();
  if (state.snapshot !== null) params.set("snapshot", state.snapshot);
  if (state.activity !== null) params.set("activity", state.activity);
  if (state.verification !== null) params.set("verification", state.verification);
  const encoded = params.toString();
  return encoded ? `?${encoded}` : "";
}

function optionalExact(params: URLSearchParams, key: string): string | null {
  if (!params.has(key)) return null;
  const value = params.get(key);
  if (!value || value.trim() !== value) {
    throw new Error(`Evidence URL “${key}” parameter is invalid.`);
  }
  return value;
}
