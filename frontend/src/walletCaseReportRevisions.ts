import { parseRfc3339Instant } from "./rfc3339";
import type { WalletCaseLimitation } from "./walletCase";
import {
  parseWalletCaseReportResponse,
  type WalletCaseReportAssurance,
  type WalletCaseReportCanonicalGateCode,
  type WalletCaseReportResponse,
} from "./walletCaseReport";

export interface WalletCaseReportRevisionSummary {
  public_id: string;
  content_hash_sha256: string;
  case_public_id: string;
  snapshot_public_id: string;
  assurance_level: WalletCaseReportAssurance;
  captured_at: string;
  activity_digest_sha256: string;
  evidence_digest_sha256: string;
  activity_count: number;
  evidence_attempt_count: number;
  canonical_eligible: boolean;
  limitation_count: number;
  unverified_claim_count: number;
}

export interface WalletCaseReportRevisionCatalog {
  contract_version: "wallet_case_report_revision_catalog_v1";
  public_id: string;
  case_public_id: string;
  revision_cutoff_public_id: string | null;
  items: WalletCaseReportRevisionSummary[];
  aggregate: { total_revisions: number; returned_count: number };
  page: { limit: number; has_more: boolean; next_cursor: string | null };
  limitations: WalletCaseLimitation[];
}

export interface WalletCaseReportRevisionCaptureResponse {
  case_public_id: string;
  created: boolean;
  revision: WalletCaseReportRevisionSummary;
}

export interface WalletCaseReportRevisionDetailResponse {
  case_public_id: string;
  revision: WalletCaseReportRevisionSummary;
  report: WalletCaseReportResponse;
}

export interface WalletCaseReportRevisionIntegerDelta {
  baseline: number;
  target: number;
  delta: number;
}

export interface WalletCaseReportRevisionCodeChanges {
  added: string[];
  removed: string[];
  modified: string[];
  unchanged_count: number;
}

export interface WalletCaseReportRevisionComparison {
  contract_version: "wallet_case_report_revision_comparison_v1";
  public_id: string;
  case_public_id: string;
  baseline: WalletCaseReportRevisionSummary;
  target: WalletCaseReportRevisionSummary;
  same_snapshot: boolean;
  content_changed: boolean;
  assurance: { baseline: WalletCaseReportAssurance; target: WalletCaseReportAssurance; changed: boolean };
  activity: {
    digest_changed: boolean;
    observed_period_changed: boolean;
    total_items: WalletCaseReportRevisionIntegerDelta;
    transactions: WalletCaseReportRevisionIntegerDelta;
    transfers: WalletCaseReportRevisionIntegerDelta;
    swaps: WalletCaseReportRevisionIntegerDelta;
    failed_transactions: WalletCaseReportRevisionIntegerDelta;
    source_sync_count: WalletCaseReportRevisionIntegerDelta;
    suppressed_duplicate_observations: WalletCaseReportRevisionIntegerDelta;
    conflicted_identity_count: WalletCaseReportRevisionIntegerDelta;
  };
  evidence: {
    digest_changed: boolean;
    total_attempts: WalletCaseReportRevisionIntegerDelta;
    returned_revalidated: WalletCaseReportRevisionIntegerDelta;
    selected_activity_count: WalletCaseReportRevisionIntegerDelta;
    locally_verified_activity_count: WalletCaseReportRevisionIntegerDelta;
    chain_inclusion_proven_activity_count: WalletCaseReportRevisionIntegerDelta;
    native_ledger_activity_count: WalletCaseReportRevisionIntegerDelta;
    history_truncated: { baseline: boolean; target: boolean; changed: boolean };
  };
  coverage_changed: boolean;
  canonical_gate: {
    eligible: { baseline: boolean; target: boolean; changed: boolean };
    newly_unmet: WalletCaseReportCanonicalGateCode[];
    resolved: WalletCaseReportCanonicalGateCode[];
    unchanged_count: number;
  };
  gaps: WalletCaseReportRevisionCodeChanges;
  limitations: WalletCaseReportRevisionCodeChanges;
  unverified_claims: WalletCaseReportRevisionCodeChanges;
  truth_boundaries_changed: false;
  comparison_limitations: WalletCaseLimitation[];
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const REPORT_ID = /^rpt_[0-9a-f]{64}$/;
const CATALOG_ID = /^rcat_[0-9a-f]{64}$/;
const COMPARISON_ID = /^rcmp_[0-9a-f]{64}$/;
const ASSURANCE = new Set<WalletCaseReportAssurance>(["observed", "normalized", "partially_verified", "canonical"]);
const GATE_CODES = new Set<WalletCaseReportCanonicalGateCode>([
  "live_data_required", "succeeded_snapshot_required", "activity_required",
  "complete_coverage_required", "full_history_proof_required", "activity_gaps_must_be_closed",
  "identity_conflicts_must_be_resolved", "evidence_history_must_be_fully_revalidated",
  "every_transaction_must_be_chain_proven", "every_transaction_needs_native_ledger",
]);

export function isWalletCaseReportPublicId(value: unknown): value is string {
  return typeof value === "string" && REPORT_ID.test(value);
}

export function parseWalletCaseReportRevisionCatalog(value: unknown): WalletCaseReportRevisionCatalog {
  const item = exactRecord(value, [
    "contract_version", "public_id", "case_public_id", "revision_cutoff_public_id",
    "items", "aggregate", "page", "limitations",
  ], "Wallet Case report revision catalog");
  literal(item.contract_version, "wallet_case_report_revision_catalog_v1", "report revision catalog contract");
  const publicId = text(item.public_id, "report revision catalog ID", 69);
  if (!CATALOG_ID.test(publicId)) fail("Wallet Case report revision catalog ID is invalid");
  const caseId = uuid(item.case_public_id, "report revision catalog case ID");
  const cutoff = item.revision_cutoff_public_id === null
    ? null
    : reportId(item.revision_cutoff_public_id, "report revision catalog cutoff");
  if (!Array.isArray(item.items) || item.items.length > 20) fail("Wallet Case report revision items are invalid");
  const items = item.items.map(parseWalletCaseReportRevisionSummary);
  if (items.some((entry) => entry.case_public_id !== caseId) || new Set(items.map((entry) => entry.public_id)).size !== items.length) {
    fail("Wallet Case report revision catalog crossed scope or contains duplicates");
  }
  const aggregateValue = exactRecord(item.aggregate, ["total_revisions", "returned_count"], "report revision aggregate");
  const aggregate = {
    total_revisions: integer(aggregateValue.total_revisions, "report revision total"),
    returned_count: integer(aggregateValue.returned_count, "report revision returned count", 20),
  };
  if (aggregate.returned_count !== items.length || aggregate.returned_count > aggregate.total_revisions) {
    fail("Wallet Case report revision aggregate is inconsistent");
  }
  if ((cutoff === null) !== (aggregate.total_revisions === 0)) fail("Wallet Case report revision cutoff is inconsistent");
  const pageValue = exactRecord(item.page, ["limit", "has_more", "next_cursor"], "report revision page");
  const limit = integer(pageValue.limit, "report revision page limit", 20, 1);
  const hasMore = boolean(pageValue.has_more, "report revision page has-more flag");
  const nextCursor = pageValue.next_cursor === null ? null : text(pageValue.next_cursor, "report revision cursor", 1024);
  if (hasMore !== (nextCursor !== null) || items.length > limit) fail("Wallet Case report revision page is inconsistent");
  const limitations = parseLimitations(item.limitations);
  if (!limitations.some((entry) => entry.code === "report_revisions_are_explicit_captures")) {
    fail("Wallet Case report revision catalog must disclose explicit capture scope");
  }
  if (hasMore !== limitations.some((entry) => entry.code === "report_revision_cursor_local_process_scope")) {
    fail("Wallet Case report revision cursor limitation is inconsistent");
  }
  return {
    contract_version: "wallet_case_report_revision_catalog_v1",
    public_id: publicId,
    case_public_id: caseId,
    revision_cutoff_public_id: cutoff,
    items,
    aggregate,
    page: { limit, has_more: hasMore, next_cursor: nextCursor },
    limitations,
  };
}

export function parseWalletCaseReportRevisionCaptureResponse(value: unknown): WalletCaseReportRevisionCaptureResponse {
  const item = exactRecord(value, ["case_public_id", "created", "revision"], "report revision capture response");
  const caseId = uuid(item.case_public_id, "captured report case ID");
  const revision = parseWalletCaseReportRevisionSummary(item.revision);
  if (revision.case_public_id !== caseId) fail("Captured Wallet Case report revision crossed scope");
  return { case_public_id: caseId, created: boolean(item.created, "report revision created flag"), revision };
}

export function parseWalletCaseReportRevisionDetailResponse(value: unknown): WalletCaseReportRevisionDetailResponse {
  const item = exactRecord(value, ["case_public_id", "revision", "report"], "report revision detail response");
  const caseId = uuid(item.case_public_id, "stored report case ID");
  const revision = parseWalletCaseReportRevisionSummary(item.revision);
  const report = parseWalletCaseReportResponse(item.report);
  if (
    revision.case_public_id !== caseId || report.case_public_id !== caseId || report.report === null
    || report.snapshot_public_id !== revision.snapshot_public_id
    || report.report.public_id !== revision.public_id
    || report.report.content_hash_sha256 !== revision.content_hash_sha256
    || report.report.assurance_level !== revision.assurance_level
    || report.report.activity_revision.digest_sha256 !== revision.activity_digest_sha256
    || report.report.evidence_revision.digest_sha256 !== revision.evidence_digest_sha256
    || report.report.activity_revision.aggregate.total_items !== revision.activity_count
    || report.report.evidence_revision.total_attempts !== revision.evidence_attempt_count
    || report.report.canonical_gate.eligible !== revision.canonical_eligible
    || report.report.limitations.length !== revision.limitation_count
    || report.report.unverified_claims.length !== revision.unverified_claim_count
  ) fail("Stored Wallet Case report revision detail is inconsistent");
  return { case_public_id: caseId, revision, report };
}

export function parseWalletCaseReportRevisionComparison(value: unknown): WalletCaseReportRevisionComparison {
  const item = exactRecord(value, [
    "contract_version", "public_id", "case_public_id", "baseline", "target", "same_snapshot",
    "content_changed", "assurance", "activity", "evidence", "coverage_changed", "canonical_gate",
    "gaps", "limitations", "unverified_claims", "truth_boundaries_changed", "comparison_limitations",
  ], "report revision comparison");
  literal(item.contract_version, "wallet_case_report_revision_comparison_v1", "report comparison contract");
  const publicId = text(item.public_id, "report comparison ID", 69);
  if (!COMPARISON_ID.test(publicId)) fail("Wallet Case report comparison ID is invalid");
  const caseId = uuid(item.case_public_id, "report comparison case ID");
  const baseline = parseWalletCaseReportRevisionSummary(item.baseline);
  const target = parseWalletCaseReportRevisionSummary(item.target);
  if (baseline.case_public_id !== caseId || target.case_public_id !== caseId) fail("Wallet Case report comparison crossed case scope");
  const sameSnapshot = boolean(item.same_snapshot, "report comparison same-snapshot flag");
  const contentChanged = boolean(item.content_changed, "report comparison content-changed flag");
  if (sameSnapshot !== (baseline.snapshot_public_id === target.snapshot_public_id)) fail("Wallet Case report comparison snapshot scope is inconsistent");
  if (contentChanged !== (baseline.public_id !== target.public_id)) fail("Wallet Case report comparison content state is inconsistent");

  const assuranceValue = exactRecord(item.assurance, ["baseline", "target", "changed"], "report comparison assurance");
  const assurance = {
    baseline: enumValue(assuranceValue.baseline, ASSURANCE, "report comparison baseline assurance"),
    target: enumValue(assuranceValue.target, ASSURANCE, "report comparison target assurance"),
    changed: boolean(assuranceValue.changed, "report comparison assurance change"),
  };
  if (
    assurance.baseline !== baseline.assurance_level || assurance.target !== target.assurance_level
    || assurance.changed !== (assurance.baseline !== assurance.target)
  ) fail("Wallet Case report comparison assurance is inconsistent");

  const activityValue = exactRecord(item.activity, [
    "digest_changed", "observed_period_changed", "total_items", "transactions", "transfers", "swaps",
    "failed_transactions", "source_sync_count", "suppressed_duplicate_observations", "conflicted_identity_count",
  ], "report comparison Activity");
  const activity = {
    digest_changed: boolean(activityValue.digest_changed, "report comparison Activity digest change"),
    observed_period_changed: boolean(activityValue.observed_period_changed, "report comparison observed-period change"),
    total_items: parseIntegerDelta(activityValue.total_items, "report comparison Activity total"),
    transactions: parseIntegerDelta(activityValue.transactions, "report comparison transactions"),
    transfers: parseIntegerDelta(activityValue.transfers, "report comparison transfers"),
    swaps: parseIntegerDelta(activityValue.swaps, "report comparison swaps"),
    failed_transactions: parseIntegerDelta(activityValue.failed_transactions, "report comparison failed transactions"),
    source_sync_count: parseIntegerDelta(activityValue.source_sync_count, "report comparison source syncs"),
    suppressed_duplicate_observations: parseIntegerDelta(activityValue.suppressed_duplicate_observations, "report comparison duplicate observations"),
    conflicted_identity_count: parseIntegerDelta(activityValue.conflicted_identity_count, "report comparison identity conflicts"),
  };
  if (
    activity.digest_changed !== (baseline.activity_digest_sha256 !== target.activity_digest_sha256)
    || activity.total_items.baseline !== baseline.activity_count || activity.total_items.target !== target.activity_count
  ) fail("Wallet Case report comparison Activity revision is inconsistent");

  const evidenceValue = exactRecord(item.evidence, [
    "digest_changed", "total_attempts", "returned_revalidated", "selected_activity_count",
    "locally_verified_activity_count", "chain_inclusion_proven_activity_count", "native_ledger_activity_count",
    "history_truncated",
  ], "report comparison Evidence");
  const evidence = {
    digest_changed: boolean(evidenceValue.digest_changed, "report comparison Evidence digest change"),
    total_attempts: parseIntegerDelta(evidenceValue.total_attempts, "report comparison Evidence attempts"),
    returned_revalidated: parseIntegerDelta(evidenceValue.returned_revalidated, "report comparison revalidated Evidence"),
    selected_activity_count: parseIntegerDelta(evidenceValue.selected_activity_count, "report comparison selected Activity"),
    locally_verified_activity_count: parseIntegerDelta(evidenceValue.locally_verified_activity_count, "report comparison locally verified Activity"),
    chain_inclusion_proven_activity_count: parseIntegerDelta(evidenceValue.chain_inclusion_proven_activity_count, "report comparison chain-proven Activity"),
    native_ledger_activity_count: parseIntegerDelta(evidenceValue.native_ledger_activity_count, "report comparison native-ledger Activity"),
    history_truncated: parseBooleanTransition(evidenceValue.history_truncated, "report comparison Evidence truncation"),
  };
  if (
    evidence.digest_changed !== (baseline.evidence_digest_sha256 !== target.evidence_digest_sha256)
    || evidence.total_attempts.baseline !== baseline.evidence_attempt_count
    || evidence.total_attempts.target !== target.evidence_attempt_count
  ) fail("Wallet Case report comparison Evidence revision is inconsistent");

  const gateValue = exactRecord(item.canonical_gate, ["eligible", "newly_unmet", "resolved", "unchanged_count"], "report comparison canonical gate");
  const canonicalGate = {
    eligible: parseBooleanTransition(gateValue.eligible, "report comparison canonical eligibility"),
    newly_unmet: parseEnumCodes(gateValue.newly_unmet, GATE_CODES, "report comparison newly unmet gates"),
    resolved: parseEnumCodes(gateValue.resolved, GATE_CODES, "report comparison resolved gates"),
    unchanged_count: integer(gateValue.unchanged_count, "report comparison unchanged gates", 16),
  };
  if (
    canonicalGate.eligible.baseline !== baseline.canonical_eligible
    || canonicalGate.eligible.target !== target.canonical_eligible
    || canonicalGate.newly_unmet.some((code) => canonicalGate.resolved.includes(code))
  ) fail("Wallet Case report comparison canonical gate is inconsistent");

  const gaps = parseCodeChanges(item.gaps, "report comparison gaps");
  const limitations = parseCodeChanges(item.limitations, "report comparison limitations");
  const unverifiedClaims = parseCodeChanges(item.unverified_claims, "report comparison unverified claims");
  const comparisonLimitations = parseLimitations(item.comparison_limitations);
  const expectedLimitationCodes = ["comparison_uses_explicit_captures", "comparison_does_not_establish_causality"];
  if (!sameSnapshot) expectedLimitationCodes.push("comparison_spans_pinned_snapshots");
  if (comparisonLimitations.map((entry) => entry.code).join("|") !== expectedLimitationCodes.join("|")) {
    fail("Wallet Case report comparison limitations are inconsistent");
  }
  return {
    contract_version: "wallet_case_report_revision_comparison_v1",
    public_id: publicId,
    case_public_id: caseId,
    baseline,
    target,
    same_snapshot: sameSnapshot,
    content_changed: contentChanged,
    assurance,
    activity,
    evidence,
    coverage_changed: boolean(item.coverage_changed, "report comparison coverage change"),
    canonical_gate: canonicalGate,
    gaps,
    limitations,
    unverified_claims: unverifiedClaims,
    truth_boundaries_changed: literal(item.truth_boundaries_changed, false, "report comparison truth-boundary change"),
    comparison_limitations: comparisonLimitations,
  };
}

export function parseWalletCaseReportRevisionSummary(value: unknown): WalletCaseReportRevisionSummary {
  const item = exactRecord(value, [
    "public_id", "content_hash_sha256", "case_public_id", "snapshot_public_id", "assurance_level",
    "captured_at", "activity_digest_sha256", "evidence_digest_sha256", "activity_count",
    "evidence_attempt_count", "canonical_eligible", "limitation_count", "unverified_claim_count",
  ], "Wallet Case report revision summary");
  const publicId = reportId(item.public_id, "stored report ID");
  const contentHash = digest(item.content_hash_sha256, "stored report content hash");
  if (publicId !== `rpt_${contentHash}`) fail("Stored Wallet Case report content address is invalid");
  const assurance = enumValue(item.assurance_level, ASSURANCE, "stored report assurance");
  const canonicalEligible = boolean(item.canonical_eligible, "stored report canonical gate");
  if ((assurance === "canonical") !== canonicalEligible) fail("Stored Wallet Case report assurance is inconsistent");
  const capturedAt = text(item.captured_at, "stored report capture time", 40);
  if (parseRfc3339Instant(capturedAt, { maximumFractionDigits: 6 }) === null) fail("Stored Wallet Case report capture time is invalid");
  return {
    public_id: publicId,
    content_hash_sha256: contentHash,
    case_public_id: uuid(item.case_public_id, "stored report case ID"),
    snapshot_public_id: uuid(item.snapshot_public_id, "stored report snapshot ID"),
    assurance_level: assurance,
    captured_at: capturedAt,
    activity_digest_sha256: digest(item.activity_digest_sha256, "stored report Activity digest"),
    evidence_digest_sha256: digest(item.evidence_digest_sha256, "stored report Evidence digest"),
    activity_count: integer(item.activity_count, "stored report Activity count"),
    evidence_attempt_count: integer(item.evidence_attempt_count, "stored report Evidence attempt count"),
    canonical_eligible: canonicalEligible,
    limitation_count: integer(item.limitation_count, "stored report limitation count"),
    unverified_claim_count: integer(item.unverified_claim_count, "stored report unverified claim count"),
  };
}

function parseLimitations(value: unknown): WalletCaseLimitation[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 8) fail("Report revision limitations are invalid");
  const parsed = value.map((entry, index) => {
    const item = exactRecord(entry, ["code", "message"], `report revision limitation ${index}`);
    return { code: text(item.code, `report revision limitation ${index} code`, 64), message: text(item.message, `report revision limitation ${index} message`, 500) };
  });
  if (new Set(parsed.map((entry) => entry.code)).size !== parsed.length) fail("Report revision limitations contain duplicates");
  return parsed;
}

function parseIntegerDelta(value: unknown, label: string): WalletCaseReportRevisionIntegerDelta {
  const item = exactRecord(value, ["baseline", "target", "delta"], label);
  const baseline = integer(item.baseline, `${label} baseline`);
  const target = integer(item.target, `${label} target`);
  const delta = signedInteger(item.delta, `${label} delta`);
  if (delta !== target - baseline) fail(`${label} delta is inconsistent`);
  return { baseline, target, delta };
}

function parseBooleanTransition(value: unknown, label: string) {
  const item = exactRecord(value, ["baseline", "target", "changed"], label);
  const baseline = boolean(item.baseline, `${label} baseline`);
  const target = boolean(item.target, `${label} target`);
  const changed = boolean(item.changed, `${label} change`);
  if (changed !== (baseline !== target)) fail(`${label} is inconsistent`);
  return { baseline, target, changed };
}

function parseCodeChanges(value: unknown, label: string): WalletCaseReportRevisionCodeChanges {
  const item = exactRecord(value, ["added", "removed", "modified", "unchanged_count"], label);
  const added = parseCodes(item.added, `${label} added`);
  const removed = parseCodes(item.removed, `${label} removed`);
  const modified = parseCodes(item.modified, `${label} modified`);
  if (
    added.some((code) => removed.includes(code) || modified.includes(code))
    || removed.some((code) => modified.includes(code))
  ) fail(`${label} overlap`);
  return { added, removed, modified, unchanged_count: integer(item.unchanged_count, `${label} unchanged count`, 64) };
}

function parseCodes(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.length > 64) fail(`${label} are invalid`);
  const parsed = value.map((entry) => text(entry, label, 64));
  if (new Set(parsed).size !== parsed.length || parsed.join("|") !== [...parsed].sort().join("|")) fail(`${label} are not canonical`);
  return parsed;
}

function parseEnumCodes<T extends string>(value: unknown, allowed: Set<T>, label: string): T[] {
  return parseCodes(value, label).map((entry) => enumValue(entry, allowed, label));
}

function exactRecord(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label} must be an object`);
  const item = value as Record<string, unknown>;
  const actual = Object.keys(item).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(`${label} fields are invalid`);
  return item;
}

function uuid(value: unknown, label: string): string {
  const parsed = text(value, label, 36);
  if (!UUID.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function reportId(value: unknown, label: string): string {
  const parsed = text(value, label, 68);
  if (!REPORT_ID.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function digest(value: unknown, label: string): string {
  const parsed = text(value, label, 64);
  if (!DIGEST.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function text(value: unknown, label: string, max: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max || value !== value.trim()) fail(`${label} is invalid`);
  return value;
}

function integer(value: unknown, label: string, max = Number.MAX_SAFE_INTEGER, min = 0): number {
  if (!Number.isSafeInteger(value) || (value as number) < min || (value as number) > max) fail(`${label} is invalid`);
  return value as number;
}

function signedInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value)) fail(`${label} is invalid`);
  return value as number;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") fail(`${label} is invalid`);
  return value;
}

function literal<T extends string | boolean>(value: unknown, expected: T, label: string): T {
  if (value !== expected) fail(`${label} is invalid`);
  return expected;
}

function enumValue<T extends string>(value: unknown, allowed: Set<T>, label: string): T {
  const parsed = text(value, label, 64) as T;
  if (!allowed.has(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function fail(message: string): never {
  throw new Error(message);
}
