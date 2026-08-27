import type {
  WalletCaseCatalogState,
  WalletCaseDataEnvironment,
  WalletCaseNetwork,
} from "./walletCase";

export interface CaseLibraryQuery {
  state: WalletCaseCatalogState;
  query: string | null;
  network: WalletCaseNetwork | null;
  dataEnvironment: WalletCaseDataEnvironment | null;
}

export type AppRoute =
  | { kind: "home" }
  | { kind: "case-list"; catalog: CaseLibraryQuery }
  | { kind: "case-summary"; caseId: string }
  | { kind: "case-activity"; caseId: string }
  | { kind: "case-findings"; caseId: string }
  | { kind: "case-evidence"; caseId: string }
  | { kind: "case-reports"; caseId: string }
  | { kind: "not-found" };

const CASE_PUBLIC_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const CASE_LIBRARY_PARAMETERS = new Set([
  "state",
  "q",
  "network",
  "data_environment",
]);

export const DEFAULT_CASE_LIBRARY_QUERY: CaseLibraryQuery = {
  state: "active",
  query: null,
  network: null,
  dataEnvironment: null,
};

export function parseAppRoute(pathname: string, search = ""): AppRoute {
  if (pathname === "/" || pathname === "") return { kind: "home" };
  if (pathname === "/cases" || pathname === "/cases/") {
    const parameters = new URLSearchParams(search);
    if (
      [...parameters.keys()].some((key) => !CASE_LIBRARY_PARAMETERS.has(key)) ||
      [...CASE_LIBRARY_PARAMETERS].some((key) => parameters.getAll(key).length > 1)
    ) {
      return { kind: "not-found" };
    }
    const state = parameters.get("state") ?? "active";
    const query = parameters.get("q");
    const network = parameters.get("network");
    const dataEnvironment = parameters.get("data_environment");
    if (
      (state !== "active" && state !== "archived") ||
      (query !== null && (!query || query.length > 120 || query.trim() !== query)) ||
      (network !== null && network !== "ton-mainnet" && network !== "ton-testnet") ||
      (dataEnvironment !== null && dataEnvironment !== "demo" && dataEnvironment !== "live")
    ) {
      return { kind: "not-found" };
    }
    return {
      kind: "case-list",
      catalog: {
        state,
        query,
        network,
        dataEnvironment,
      },
    };
  }

  const match = /^\/cases\/([^/]+)\/(summary|activity|findings|evidence|reports)\/?$/.exec(pathname);
  if (!match) return { kind: "not-found" };

  let caseId: string;
  try {
    caseId = decodeURIComponent(match[1]);
  } catch {
    return { kind: "not-found" };
  }
  if (!CASE_PUBLIC_ID.test(caseId)) return { kind: "not-found" };
  const kind = match[2] === "summary"
    ? "case-summary"
    : match[2] === "activity"
      ? "case-activity"
      : match[2] === "findings"
        ? "case-findings"
        : match[2] === "evidence"
          ? "case-evidence"
          : "case-reports";
  return { kind, caseId };
}

export function caseListPath(query: CaseLibraryQuery = DEFAULT_CASE_LIBRARY_QUERY): string {
  const parameters = new URLSearchParams();
  if (query.state !== "active") parameters.set("state", query.state);
  if (query.query !== null) {
    const canonicalQuery = query.query.trim();
    if (!canonicalQuery || canonicalQuery.length > 120) {
      throw new Error("Wallet Case library query must contain 1 through 120 characters");
    }
    parameters.set("q", canonicalQuery);
  }
  if (query.network !== null) parameters.set("network", query.network);
  if (query.dataEnvironment !== null) {
    parameters.set("data_environment", query.dataEnvironment);
  }
  const search = parameters.toString();
  return search ? `/cases?${search}` : "/cases";
}

export function caseSummaryPath(caseId: string): string {
  if (!CASE_PUBLIC_ID.test(caseId)) {
    throw new Error("Wallet Case id must be a canonical UUIDv4");
  }
  return `/cases/${encodeURIComponent(caseId)}/summary`;
}

export function caseActivityPath(caseId: string): string {
  if (!CASE_PUBLIC_ID.test(caseId)) {
    throw new Error("Wallet Case id must be a canonical UUIDv4");
  }
  return `/cases/${encodeURIComponent(caseId)}/activity`;
}

export function caseEvidencePath(caseId: string): string {
  if (!CASE_PUBLIC_ID.test(caseId)) {
    throw new Error("Wallet Case id must be a canonical UUIDv4");
  }
  return `/cases/${encodeURIComponent(caseId)}/evidence`;
}

export function caseFindingsPath(caseId: string): string {
  if (!CASE_PUBLIC_ID.test(caseId)) {
    throw new Error("Wallet Case id must be a canonical UUIDv4");
  }
  return `/cases/${encodeURIComponent(caseId)}/findings`;
}

export function caseReportsPath(caseId: string): string {
  if (!CASE_PUBLIC_ID.test(caseId)) {
    throw new Error("Wallet Case id must be a canonical UUIDv4");
  }
  return `/cases/${encodeURIComponent(caseId)}/reports`;
}
