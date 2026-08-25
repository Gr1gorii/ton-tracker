import { CASE_ID, SYNC_ID } from "./walletCaseFixtures";
import { walletCaseReportFixture } from "./walletCaseReportFixtures";
import type {
  WalletCaseReportRevisionCatalog,
  WalletCaseReportRevisionComparison,
  WalletCaseReportRevisionDetailResponse,
  WalletCaseReportRevisionSummary,
} from "../walletCaseReportRevisions";

export function walletCaseReportRevisionSummaryFixture(
  overrides: Partial<WalletCaseReportRevisionSummary> = {},
): WalletCaseReportRevisionSummary {
  const report = walletCaseReportFixture().report!;
  return {
    public_id: report.public_id,
    content_hash_sha256: report.content_hash_sha256,
    case_public_id: CASE_ID,
    snapshot_public_id: SYNC_ID,
    assurance_level: report.assurance_level,
    captured_at: "2026-08-19T10:00:00Z",
    activity_digest_sha256: report.activity_revision.digest_sha256,
    evidence_digest_sha256: report.evidence_revision.digest_sha256,
    activity_count: report.activity_revision.aggregate.total_items,
    evidence_attempt_count: report.evidence_revision.total_attempts,
    canonical_eligible: false,
    limitation_count: report.limitations.length,
    unverified_claim_count: report.unverified_claims.length,
    ...overrides,
  };
}

export function walletCaseReportRevisionCatalogFixture(
  overrides: Partial<WalletCaseReportRevisionCatalog> = {},
): WalletCaseReportRevisionCatalog {
  const revision = walletCaseReportRevisionSummaryFixture();
  return {
    contract_version: "wallet_case_report_revision_catalog_v1",
    public_id: `rcat_${"ab".repeat(32)}`,
    case_public_id: CASE_ID,
    revision_cutoff_public_id: revision.public_id,
    items: [revision],
    aggregate: { total_revisions: 1, returned_count: 1 },
    page: { limit: 10, has_more: false, next_cursor: null },
    limitations: [{
      code: "report_revisions_are_explicit_captures",
      message: "Only explicitly captured report revisions are retained; intermediate Evidence states are not reconstructed.",
    }],
    ...overrides,
  };
}

export function walletCaseReportRevisionDetailFixture(
  overrides: Partial<WalletCaseReportRevisionDetailResponse> = {},
): WalletCaseReportRevisionDetailResponse {
  return {
    case_public_id: CASE_ID,
    revision: walletCaseReportRevisionSummaryFixture(),
    report: walletCaseReportFixture(),
    ...overrides,
  };
}

export function walletCaseReportRevisionComparisonFixture(
  overrides: Partial<WalletCaseReportRevisionComparison> = {},
): WalletCaseReportRevisionComparison {
  const report = walletCaseReportFixture().report!;
  const baseline = walletCaseReportRevisionSummaryFixture();
  const target = walletCaseReportRevisionSummaryFixture();
  const zero = (value: number) => ({ baseline: value, target: value, delta: 0 });
  return {
    contract_version: "wallet_case_report_revision_comparison_v1",
    public_id: `rcmp_${"ab".repeat(32)}`,
    case_public_id: CASE_ID,
    baseline,
    target,
    same_snapshot: true,
    content_changed: false,
    assurance: { baseline: report.assurance_level, target: report.assurance_level, changed: false },
    activity: {
      digest_changed: false,
      observed_period_changed: false,
      total_items: zero(report.activity_revision.aggregate.total_items),
      transactions: zero(report.activity_revision.aggregate.transactions),
      transfers: zero(report.activity_revision.aggregate.transfers),
      swaps: zero(report.activity_revision.aggregate.swaps),
      failed_transactions: zero(report.activity_revision.aggregate.failed_transactions),
      source_sync_count: zero(report.activity_revision.aggregate.source_sync_count),
      suppressed_duplicate_observations: zero(report.activity_revision.aggregate.suppressed_duplicate_observations),
      conflicted_identity_count: zero(report.activity_revision.aggregate.conflicted_identity_count),
    },
    evidence: {
      digest_changed: false,
      total_attempts: zero(report.evidence_revision.total_attempts),
      returned_revalidated: zero(report.evidence_revision.returned_revalidated),
      selected_activity_count: zero(report.evidence_revision.selected_activity_count),
      locally_verified_activity_count: zero(report.evidence_revision.locally_verified_activity_count),
      chain_inclusion_proven_activity_count: zero(report.evidence_revision.chain_inclusion_proven_activity_count),
      native_ledger_activity_count: zero(report.evidence_revision.native_ledger_activity_count),
      history_truncated: { baseline: report.evidence_revision.history_truncated, target: report.evidence_revision.history_truncated, changed: false },
    },
    coverage_changed: false,
    canonical_gate: {
      eligible: { baseline: report.canonical_gate.eligible, target: report.canonical_gate.eligible, changed: false },
      newly_unmet: [],
      resolved: [],
      unchanged_count: report.canonical_gate.unmet.length,
    },
    gaps: { added: [], removed: [], modified: [], unchanged_count: report.gaps.length },
    limitations: { added: [], removed: [], modified: [], unchanged_count: report.limitations.length },
    unverified_claims: { added: [], removed: [], modified: [], unchanged_count: report.unverified_claims.length },
    truth_boundaries_changed: false,
    comparison_limitations: [
      { code: "comparison_uses_explicit_captures", message: "This comparison covers two explicitly captured revisions." },
      { code: "comparison_does_not_establish_causality", message: "Directional deltas do not prove why a value changed." },
    ],
    ...overrides,
  };
}
