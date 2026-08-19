import { CASE_ID, SYNC_ID } from "./walletCaseFixtures";
import { walletCaseReportFixture } from "./walletCaseReportFixtures";
import type {
  WalletCaseReportRevisionCatalog,
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
