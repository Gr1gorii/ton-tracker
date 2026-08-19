export type AppRoute =
  | { kind: "home" }
  | { kind: "case-summary"; caseId: string }
  | { kind: "case-activity"; caseId: string }
  | { kind: "case-findings"; caseId: string }
  | { kind: "case-evidence"; caseId: string }
  | { kind: "case-reports"; caseId: string }
  | { kind: "not-found" };

const CASE_PUBLIC_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

export function parseAppRoute(pathname: string): AppRoute {
  if (pathname === "/" || pathname === "") return { kind: "home" };

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
