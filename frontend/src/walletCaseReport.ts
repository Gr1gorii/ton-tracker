import { parseRfc3339Instant } from "./rfc3339";
import { isCanonicalRawTonAddress } from "./tonAddress";
import {
  parseWalletCaseCoverage,
  type WalletCaseCoverage,
  type WalletCaseLimitation,
} from "./walletCase";
import type { WalletCaseActivitySnapshot } from "./walletCaseActivity";

export type WalletCaseReportAssurance = "observed" | "normalized" | "partially_verified" | "canonical";

export type WalletCaseReportCanonicalGateCode =
  | "live_data_required"
  | "succeeded_snapshot_required"
  | "activity_required"
  | "complete_coverage_required"
  | "full_history_proof_required"
  | "activity_gaps_must_be_closed"
  | "identity_conflicts_must_be_resolved"
  | "evidence_history_must_be_fully_revalidated"
  | "every_transaction_must_be_chain_proven"
  | "every_transaction_needs_native_ledger";

export interface WalletCaseReportAggregate {
  total_items: number;
  transactions: number;
  transfers: number;
  swaps: number;
  failed_transactions: number;
  source_sync_count: number;
  suppressed_duplicate_observations: number;
  conflicted_identity_count: number;
}

export interface WalletCaseReportGap {
  code: string;
  surface: string | null;
  start_at: string | null;
  end_at: string | null;
  message: string;
}

export interface WalletCaseReport {
  contract_version: "wallet_case_report_v1";
  public_id: string;
  content_hash_sha256: string;
  case_public_id: string;
  snapshot_public_id: string;
  assurance_level: WalletCaseReportAssurance;
  subject: {
    network: "ton-mainnet" | "ton-testnet";
    data_environment: "demo" | "live";
    wallet_account_canonical: string;
  };
  snapshot: WalletCaseActivitySnapshot;
  activity_revision: {
    digest_sha256: string;
    aggregate: WalletCaseReportAggregate;
    observed_period: { start_at: string; end_at: string } | null;
  };
  evidence_revision: {
    digest_sha256: string;
    total_attempts: number;
    returned_revalidated: number;
    history_truncated: boolean;
    selected_activity_count: number;
    locally_verified_activity_count: number;
    chain_inclusion_proven_activity_count: number;
    native_ledger_activity_count: number;
  };
  coverage: WalletCaseCoverage;
  gaps: WalletCaseReportGap[];
  canonical_gate: {
    eligible: boolean;
    unmet: WalletCaseReportCanonicalGateCode[];
  };
  limitations: WalletCaseLimitation[];
  unverified_claims: Array<{ code: string; message: string; affected_count: number | null }>;
  truth_boundaries: {
    establishes_complete_wallet_history: false;
    eligible_for_cost_basis: false;
    used_by_pnl: false;
    includes_raw_provider_payloads: false;
    provider_free_full_report_revalidation: false;
  };
}

export interface WalletCaseReportResponse {
  case_public_id: string;
  snapshot_public_id: string | null;
  report: WalletCaseReport | null;
  limitations: WalletCaseLimitation[];
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const DIGEST = /^[0-9a-f]{64}$/;
const REPORT_ID = /^rpt_[0-9a-f]{64}$/;
const ASSURANCE = new Set<WalletCaseReportAssurance>(["observed", "normalized", "partially_verified", "canonical"]);
const NETWORKS = new Set<"ton-mainnet" | "ton-testnet">(["ton-mainnet", "ton-testnet"]);
const ENVIRONMENTS = new Set<"demo" | "live">(["demo", "live"]);
const SNAPSHOT_STATES = new Set<"partial" | "succeeded">(["partial", "succeeded"]);
const DATA_MODES = new Set<"mock" | "real">(["mock", "real"]);
const GATE_CODES = new Set<WalletCaseReportCanonicalGateCode>([
  "live_data_required",
  "succeeded_snapshot_required",
  "activity_required",
  "complete_coverage_required",
  "full_history_proof_required",
  "activity_gaps_must_be_closed",
  "identity_conflicts_must_be_resolved",
  "evidence_history_must_be_fully_revalidated",
  "every_transaction_must_be_chain_proven",
  "every_transaction_needs_native_ledger",
]);

export function parseWalletCaseReportResponse(value: unknown): WalletCaseReportResponse {
  const response = exactRecord(value, ["case_public_id", "snapshot_public_id", "report", "limitations"], "Wallet Case report response");
  const casePublicId = uuid(response.case_public_id, "Wallet Case report case ID");
  const snapshotPublicId = response.snapshot_public_id === null
    ? null
    : uuid(response.snapshot_public_id, "Wallet Case report snapshot ID");
  const limitations = parseLimitations(response.limitations, "Wallet Case report response limitations");
  const report = response.report === null ? null : parseReport(response.report);
  if ((report === null) !== (snapshotPublicId === null)) fail("Wallet Case report availability is inconsistent");
  if (report) {
    if (report.case_public_id !== casePublicId || report.snapshot_public_id !== snapshotPublicId || limitations.length !== 0) {
      fail("Wallet Case report response scope is inconsistent");
    }
  } else if (limitations.length !== 1 || limitations[0].code !== "not_synchronized") {
    fail("Missing Wallet Case report requires not_synchronized");
  }
  return { case_public_id: casePublicId, snapshot_public_id: snapshotPublicId, report, limitations };
}

function parseReport(value: unknown): WalletCaseReport {
  const item = exactRecord(value, [
    "contract_version", "public_id", "content_hash_sha256", "case_public_id", "snapshot_public_id",
    "assurance_level", "subject", "snapshot", "activity_revision", "evidence_revision", "coverage",
    "gaps", "canonical_gate", "limitations", "unverified_claims", "truth_boundaries",
  ], "Wallet Case report");
  literal(item.contract_version, "wallet_case_report_v1", "Wallet Case report contract");
  const publicId = text(item.public_id, "Wallet Case report ID", 68);
  const contentHash = digest(item.content_hash_sha256, "Wallet Case report content hash");
  if (!REPORT_ID.test(publicId) || publicId !== `rpt_${contentHash}`) fail("Wallet Case report content address is invalid");
  const casePublicId = uuid(item.case_public_id, "Wallet Case report case ID");
  const snapshotPublicId = uuid(item.snapshot_public_id, "Wallet Case report snapshot ID");
  const assurance = enumValue(item.assurance_level, ASSURANCE, "Wallet Case report assurance");

  const subjectValue = exactRecord(item.subject, ["network", "data_environment", "wallet_account_canonical"], "Wallet Case report subject");
  const network = enumValue(subjectValue.network, NETWORKS, "Wallet Case report network");
  const environment = enumValue(subjectValue.data_environment, ENVIRONMENTS, "Wallet Case report environment");
  const account = text(subjectValue.wallet_account_canonical, "Wallet Case report wallet account", 67);
  if (!isCanonicalRawTonAddress(account) || !/^(?:0|-1):/.test(account)) fail("Wallet Case report wallet account is invalid");

  const snapshot = parseSnapshot(item.snapshot);
  if (snapshot.public_id !== snapshotPublicId || snapshot.coverage.requested_start_at !== snapshot.requested_period.start_at || snapshot.coverage.requested_end_at !== snapshot.requested_period.end_at) {
    fail("Wallet Case report snapshot is inconsistent");
  }
  if ((environment === "demo") !== (snapshot.data_mode === "mock")) fail("Wallet Case report environment is inconsistent");

  const activityValue = exactRecord(item.activity_revision, ["digest_sha256", "aggregate", "observed_period"], "Wallet Case report Activity revision");
  const activityRevision = {
    digest_sha256: digest(activityValue.digest_sha256, "Wallet Case report Activity digest"),
    aggregate: parseAggregate(activityValue.aggregate),
    observed_period: activityValue.observed_period === null ? null : parsePeriod(activityValue.observed_period, "Wallet Case report observed period"),
  };
  const evidenceRevision = parseEvidenceRevision(item.evidence_revision);
  const coverage = parseCoverage(item.coverage);
  if (JSON.stringify(coverage) !== JSON.stringify(snapshot.coverage)) fail("Wallet Case report coverage changed from its snapshot");

  if (!Array.isArray(item.gaps)) fail("Wallet Case report gaps are invalid");
  const gaps = item.gaps.map(parseGap);
  const gateValue = exactRecord(item.canonical_gate, ["eligible", "unmet"], "Wallet Case report canonical gate");
  const eligible = boolean(gateValue.eligible, "Wallet Case report canonical eligibility");
  if (!Array.isArray(gateValue.unmet)) fail("Wallet Case report canonical gates are invalid");
  const unmet = gateValue.unmet.map((entry) => enumValue(entry, GATE_CODES, "Wallet Case report canonical gate"));
  if (new Set(unmet).size !== unmet.length || eligible !== (unmet.length === 0)) fail("Wallet Case report canonical gate is inconsistent");
  if ((assurance === "canonical") !== eligible) fail("Wallet Case report assurance contradicts its canonical gate");
  if (environment === "demo" && assurance !== "observed") fail("Demo Wallet Case report cannot exceed observed assurance");

  const limitations = parseLimitations(item.limitations, "Wallet Case report limitations");
  if (new Set(limitations.map((entry) => entry.code)).size !== limitations.length) fail("Wallet Case report limitations contain duplicates");
  if (!Array.isArray(item.unverified_claims)) fail("Wallet Case report unverified claims are invalid");
  const unverifiedClaims = item.unverified_claims.map((entry, index) => {
    const claim = exactRecord(entry, ["code", "message", "affected_count"], `Wallet Case report unverified claim ${index}`);
    return {
      code: text(claim.code, `Wallet Case report unverified claim ${index} code`, 64),
      message: text(claim.message, `Wallet Case report unverified claim ${index} message`, 500),
      affected_count: claim.affected_count === null ? null : integer(claim.affected_count, `Wallet Case report unverified claim ${index} count`),
    };
  });
  if (new Set(unverifiedClaims.map((entry) => entry.code)).size !== unverifiedClaims.length) fail("Wallet Case report unverified claims contain duplicates");
  const truthValue = exactRecord(item.truth_boundaries, [
    "establishes_complete_wallet_history", "eligible_for_cost_basis", "used_by_pnl",
    "includes_raw_provider_payloads", "provider_free_full_report_revalidation",
  ], "Wallet Case report truth boundaries");
  const truthBoundaries = {
    establishes_complete_wallet_history: literal(truthValue.establishes_complete_wallet_history, false, "complete history boundary"),
    eligible_for_cost_basis: literal(truthValue.eligible_for_cost_basis, false, "cost basis boundary"),
    used_by_pnl: literal(truthValue.used_by_pnl, false, "PnL boundary"),
    includes_raw_provider_payloads: literal(truthValue.includes_raw_provider_payloads, false, "raw payload boundary"),
    provider_free_full_report_revalidation: literal(truthValue.provider_free_full_report_revalidation, false, "provider-free report boundary"),
  };

  return {
    contract_version: "wallet_case_report_v1",
    public_id: publicId,
    content_hash_sha256: contentHash,
    case_public_id: casePublicId,
    snapshot_public_id: snapshotPublicId,
    assurance_level: assurance,
    subject: { network, data_environment: environment, wallet_account_canonical: account },
    snapshot,
    activity_revision: activityRevision,
    evidence_revision: evidenceRevision,
    coverage,
    gaps,
    canonical_gate: { eligible, unmet },
    limitations,
    unverified_claims: unverifiedClaims,
    truth_boundaries: truthBoundaries,
  };
}

function parseSnapshot(value: unknown): WalletCaseActivitySnapshot {
  const item = exactRecord(value, ["public_id", "state", "completed_at", "data_mode", "provider", "requested_period", "coverage"], "Wallet Case report snapshot");
  return {
    public_id: uuid(item.public_id, "Wallet Case report snapshot ID"),
    state: enumValue(item.state, SNAPSHOT_STATES, "Wallet Case report snapshot state"),
    completed_at: timestamp(item.completed_at, "Wallet Case report snapshot completion"),
    data_mode: enumValue(item.data_mode, DATA_MODES, "Wallet Case report snapshot mode"),
    provider: text(item.provider, "Wallet Case report snapshot provider", 64),
    requested_period: parsePeriod(item.requested_period, "Wallet Case report requested period"),
    coverage: parseCoverage(item.coverage),
  };
}

function parseAggregate(value: unknown): WalletCaseReportAggregate {
  const item = exactRecord(value, [
    "total_items", "transactions", "transfers", "swaps", "failed_transactions", "source_sync_count",
    "suppressed_duplicate_observations", "conflicted_identity_count",
  ], "Wallet Case report Activity aggregate");
  const aggregate = {
    total_items: integer(item.total_items, "Wallet Case report Activity total"),
    transactions: integer(item.transactions, "Wallet Case report transaction total"),
    transfers: integer(item.transfers, "Wallet Case report transfer total"),
    swaps: integer(item.swaps, "Wallet Case report swap total"),
    failed_transactions: integer(item.failed_transactions, "Wallet Case report failed transaction total"),
    source_sync_count: integer(item.source_sync_count, "Wallet Case report source sync total"),
    suppressed_duplicate_observations: integer(item.suppressed_duplicate_observations, "Wallet Case report duplicate total"),
    conflicted_identity_count: integer(item.conflicted_identity_count, "Wallet Case report conflict total"),
  };
  if (aggregate.transactions + aggregate.transfers + aggregate.swaps !== aggregate.total_items || aggregate.failed_transactions > aggregate.transactions) {
    fail("Wallet Case report Activity aggregate is inconsistent");
  }
  return aggregate;
}

function parseEvidenceRevision(value: unknown): WalletCaseReport["evidence_revision"] {
  const item = exactRecord(value, [
    "digest_sha256", "total_attempts", "returned_revalidated", "history_truncated", "selected_activity_count",
    "locally_verified_activity_count", "chain_inclusion_proven_activity_count", "native_ledger_activity_count",
  ], "Wallet Case report Evidence revision");
  const parsed = {
    digest_sha256: digest(item.digest_sha256, "Wallet Case report Evidence digest"),
    total_attempts: integer(item.total_attempts, "Wallet Case report Evidence attempts"),
    returned_revalidated: integer(item.returned_revalidated, "Wallet Case report revalidated Evidence"),
    history_truncated: boolean(item.history_truncated, "Wallet Case report Evidence truncation"),
    selected_activity_count: integer(item.selected_activity_count, "Wallet Case report selected Activity count"),
    locally_verified_activity_count: integer(item.locally_verified_activity_count, "Wallet Case report locally verified count"),
    chain_inclusion_proven_activity_count: integer(item.chain_inclusion_proven_activity_count, "Wallet Case report chain-proven count"),
    native_ledger_activity_count: integer(item.native_ledger_activity_count, "Wallet Case report native ledger count"),
  };
  if (
    parsed.returned_revalidated > 50 || parsed.returned_revalidated > parsed.total_attempts ||
    parsed.history_truncated !== (parsed.total_attempts > parsed.returned_revalidated) ||
    !(parsed.native_ledger_activity_count <= parsed.chain_inclusion_proven_activity_count &&
      parsed.chain_inclusion_proven_activity_count <= parsed.locally_verified_activity_count &&
      parsed.locally_verified_activity_count <= parsed.selected_activity_count &&
      parsed.selected_activity_count <= parsed.returned_revalidated)
  ) fail("Wallet Case report Evidence revision is inconsistent");
  return parsed;
}

function parseCoverage(value: unknown): WalletCaseCoverage {
  const item = exactRecord(value, [
    "state", "requested_start_at", "requested_end_at", "requested_surfaces", "unavailable_surfaces",
    "incomplete_surfaces", "streams", "full_history_proven",
  ], "Wallet Case report coverage");
  if (!Array.isArray(item.streams)) fail("Wallet Case report coverage streams are invalid");
  item.streams.forEach((stream, index) => exactRecord(stream, ["provider", "stream_key", "completion_state", "error_code"], `Wallet Case report coverage stream ${index}`));
  return parseWalletCaseCoverage(item);
}

function parseGap(value: unknown, index: number): WalletCaseReportGap {
  const item = exactRecord(value, ["code", "surface", "start_at", "end_at", "message"], `Wallet Case report gap ${index}`);
  const startAt = item.start_at === null ? null : timestamp(item.start_at, `Wallet Case report gap ${index} start`);
  const endAt = item.end_at === null ? null : timestamp(item.end_at, `Wallet Case report gap ${index} end`);
  if ((startAt === null) !== (endAt === null) || (startAt && endAt && parseInstant(startAt) >= parseInstant(endAt))) fail(`Wallet Case report gap ${index} period is invalid`);
  return {
    code: text(item.code, `Wallet Case report gap ${index} code`, 64),
    surface: item.surface === null ? null : text(item.surface, `Wallet Case report gap ${index} surface`, 32),
    start_at: startAt,
    end_at: endAt,
    message: text(item.message, `Wallet Case report gap ${index} message`, 500),
  };
}

function parsePeriod(value: unknown, label: string): { start_at: string; end_at: string } {
  const item = exactRecord(value, ["start_at", "end_at"], label);
  const startAt = timestamp(item.start_at, `${label} start`);
  const endAt = timestamp(item.end_at, `${label} end`);
  if (parseInstant(startAt) >= parseInstant(endAt)) fail(`${label} is invalid`);
  return { start_at: startAt, end_at: endAt };
}

function parseLimitations(value: unknown, label: string): WalletCaseLimitation[] {
  if (!Array.isArray(value)) fail(`${label} are invalid`);
  return value.map((entry, index) => {
    const item = exactRecord(entry, ["code", "message"], `${label} ${index}`);
    return { code: text(item.code, `${label} ${index} code`, 64), message: text(item.message, `${label} ${index} message`, 500) };
  });
}

function exactRecord(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) fail(`${label} must be an object`);
  const item = value as Record<string, unknown>;
  const actual = Object.keys(item).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(`${label} fields are invalid`);
  return item;
}

function text(value: unknown, label: string, max = 500): string {
  if (typeof value !== "string" || value.length === 0 || value.length > max) fail(`${label} is invalid`);
  return value;
}

function uuid(value: unknown, label: string): string {
  const parsed = text(value, label, 36);
  if (!UUID.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function digest(value: unknown, label: string): string {
  const parsed = text(value, label, 64);
  if (!DIGEST.test(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function timestamp(value: unknown, label: string): string {
  const parsed = text(value, label, 40);
  if (parseRfc3339Instant(parsed) === null) fail(`${label} is invalid`);
  return parsed;
}

function parseInstant(value: string): bigint {
  const parsed = parseRfc3339Instant(value);
  if (parsed === null) fail("Wallet Case report timestamp is invalid");
  return parsed;
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) fail(`${label} is invalid`);
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
  const parsed = text(value, label) as T;
  if (!allowed.has(parsed)) fail(`${label} is invalid`);
  return parsed;
}

function fail(message: string): never {
  throw new Error(message);
}
