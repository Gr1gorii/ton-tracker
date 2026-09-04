import type { WalletCaseLimitation, WalletCaseSyncMode } from "./walletCase";
import type { WalletCaseSyncManifestPeriod } from "./walletCaseSyncManifest";

export type WalletCaseStreamResumeState = "ready" | "complete" | "blocked";

export interface WalletCaseStreamCheckpointLastPage {
  page_index: number;
  response_cursor: string | null;
  response_digest_sha256: string | null;
  min_logical_time: string | null;
  max_logical_time: string | null;
  min_timestamp: string | null;
  max_timestamp: string | null;
  fetched_at: string | null;
}

export interface WalletCaseStreamCheckpointDocument {
  contract_version: "wallet_case_stream_checkpoint_v1";
  case_public_id: string;
  source_sync_public_id: string;
  source_manifest_public_id: string;
  source_manifest_hash_sha256: string;
  provider: string;
  stream_key: string;
  provider_contract_version: string;
  acquisition_mode: WalletCaseSyncMode;
  requested_period: WalletCaseSyncManifestPeriod;
  sort_order: string | null;
  page_size: number;
  page_cap: number;
  completion_state: string;
  termination_reason: string | null;
  page_count: number;
  pages_succeeded: number;
  resume_state: WalletCaseStreamResumeState;
  resume_blocker: string | null;
  continuation_cursor: string | null;
  continuation_page_index: number | null;
  last_successful_page: WalletCaseStreamCheckpointLastPage | null;
}

export interface WalletCaseStreamCheckpointDescriptor {
  public_id: string;
  contract_version: "wallet_case_stream_checkpoint_v1";
  checkpoint_hash_sha256: string;
  provider: string;
  stream_key: string;
  provider_contract_version: string;
  source_sync_public_id: string;
  resume_state: WalletCaseStreamResumeState;
  created_at: string;
}

export interface WalletCaseStreamCheckpointResponse {
  checkpoint: WalletCaseStreamCheckpointDescriptor;
  document: WalletCaseStreamCheckpointDocument;
}

export interface WalletCaseStreamCheckpointCatalogResponse {
  case_public_id: string;
  checkpoint_count: number;
  ready_count: number;
  complete_count: number;
  blocked_count: number;
  checkpoints: WalletCaseStreamCheckpointResponse[];
}

export interface WalletCaseStreamCheckpointLineage {
  acquisition_mode: WalletCaseSyncMode;
  base_snapshot_public_id: string | null;
  parent_checkpoint_public_id: string | null;
  chain_depth: number;
}

export interface WalletCaseStreamCheckpointDetailResponse extends WalletCaseStreamCheckpointResponse {
  lineage: WalletCaseStreamCheckpointLineage;
}

export interface WalletCaseStreamCheckpointHistoryItem {
  checkpoint: WalletCaseStreamCheckpointDescriptor;
  lineage: WalletCaseStreamCheckpointLineage;
  continuation_page_index: number | null;
  page_count: number;
  pages_succeeded: number;
}

export interface WalletCaseStreamCheckpointHistoryResponse {
  contract_version: "wallet_case_stream_checkpoint_history_v1";
  case_public_id: string;
  revision_cutoff_public_id: string | null;
  items: WalletCaseStreamCheckpointHistoryItem[];
  aggregate: { total_revisions: number; returned_count: number };
  page: { limit: number; has_more: boolean; next_cursor: string | null };
  limitations: WalletCaseLimitation[];
}

export interface WalletCaseStreamCheckpointChainRevision {
  ordinal: number;
  checkpoint: WalletCaseStreamCheckpointDescriptor;
  acquisition_mode: WalletCaseSyncMode;
  base_snapshot_public_id: string | null;
  parent_checkpoint_public_id: string | null;
  source_manifest_public_id: string;
  source_manifest_hash_sha256: string;
  requested_period: WalletCaseSyncManifestPeriod;
  continuation_page_index: number | null;
  page_count: number;
  pages_succeeded: number;
  last_response_digest_sha256: string | null;
}

export interface WalletCaseStreamCheckpointChainResponse {
  chain: {
    public_id: string;
    contract_version: "wallet_case_stream_checkpoint_chain_v1";
    content_hash_sha256: string;
    revision_count: number;
    page_count: number;
    pages_succeeded: number;
  };
  document: {
    contract_version: "wallet_case_stream_checkpoint_chain_v1";
    case_public_id: string;
    tip_checkpoint_public_id: string;
    provider: string;
    stream_key: string;
    provider_contract_version: string;
    root_acquisition_mode: "bounded" | "incremental";
    root_base_snapshot_public_id: string | null;
    current_resume_state: WalletCaseStreamResumeState;
    next_page_index: number | null;
    aggregate: {
      revision_count: number;
      page_count: number;
      pages_succeeded: number;
    };
    revisions: WalletCaseStreamCheckpointChainRevision[];
    limitations: WalletCaseLimitation[];
  };
}

export interface WalletCaseBackfillProgressFrontier {
  checkpoint_public_id: string;
  page: WalletCaseStreamCheckpointLastPage;
}

export interface WalletCaseBackfillProgressStream {
  provider: string;
  stream_key: string;
  provider_contract_version: string;
  root_checkpoint_public_id: string;
  tip_checkpoint: WalletCaseStreamCheckpointDescriptor;
  chain_public_id: string;
  chain_content_hash_sha256: string;
  root_acquisition_mode: "bounded" | "incremental";
  requested_period: WalletCaseSyncManifestPeriod;
  revision_count: number;
  initial_page_count: number;
  initial_pages_succeeded: number;
  continuation_revision_count: number;
  continuation_page_count: number;
  continuation_pages_succeeded: number;
  page_count: number;
  pages_succeeded: number;
  resume_state: WalletCaseStreamResumeState;
  requested_interval_complete: boolean;
  next_page_index: number | null;
  termination_reason: string | null;
  resume_blocker: string | null;
  root_frontier: WalletCaseBackfillProgressFrontier | null;
  current_frontier: WalletCaseBackfillProgressFrontier | null;
  frontier_advanced: boolean;
}

export interface WalletCaseBackfillProgressAggregate {
  stream_count: number;
  ready_count: number;
  complete_count: number;
  blocked_count: number;
  revision_count: number;
  continuation_revision_count: number;
  page_count: number;
  pages_succeeded: number;
  continuation_page_count: number;
  continuation_pages_succeeded: number;
  observed_frontier_count: number;
  advanced_frontier_count: number;
}

export interface WalletCaseBackfillProgressResponse {
  progress: {
    public_id: string;
    contract_version: "wallet_case_backfill_progress_v1";
    content_hash_sha256: string;
    checkpoint_cutoff_public_id: string | null;
  } & WalletCaseBackfillProgressAggregate;
  document: {
    contract_version: "wallet_case_backfill_progress_v1";
    case_public_id: string;
    checkpoint_cutoff_public_id: string | null;
    aggregate: WalletCaseBackfillProgressAggregate;
    streams: WalletCaseBackfillProgressStream[];
    limitations: WalletCaseLimitation[];
  };
}

export type WalletCaseBackfillScheduleState =
  | "ready"
  | "backpressured"
  | "empty"
  | "complete"
  | "blocked";

export interface WalletCaseBackfillScheduleSelection {
  provider: string;
  stream_key: string;
  checkpoint_public_id: string;
  continuation_revision_count: number;
  continuation_page_count: number;
  next_page_index: number;
}

export interface WalletCaseBackfillScheduleResponse {
  schedule: {
    public_id: string;
    contract_version: "wallet_case_backfill_schedule_v1";
    content_hash_sha256: string;
    state: WalletCaseBackfillScheduleState;
    input_progress_public_id: string;
    input_plan_public_id: string;
    checkpoint_cutoff_public_id: string | null;
    page_budget: number;
    selected_checkpoint_public_id: string | null;
    active_sync_public_id: string | null;
  };
  document: {
    contract_version: "wallet_case_backfill_schedule_v1";
    case_public_id: string;
    input_progress_public_id: string;
    input_plan_public_id: string;
    checkpoint_cutoff_public_id: string | null;
    page_budget: number;
    selection_policy: "least_continuation_pages_then_revisions_then_provider_stream_v1";
    state: WalletCaseBackfillScheduleState;
    stream_count: number;
    ready_count: number;
    complete_count: number;
    blocked_count: number;
    active_sync_public_id: string | null;
    selection: WalletCaseBackfillScheduleSelection | null;
    limitations: WalletCaseLimitation[];
  };
}

export interface WalletCaseCheckpointContinuationPlanStream {
  provider: string;
  stream_key: string;
  provider_contract_version: string;
  tip_checkpoint: WalletCaseStreamCheckpointDescriptor;
  chain_public_id: string;
  chain_content_hash_sha256: string;
  revision_count: number;
  page_count: number;
  pages_succeeded: number;
  resume_state: WalletCaseStreamResumeState;
  next_page_index: number | null;
  resume_blocker: string | null;
}

export interface WalletCaseCheckpointContinuationPlanAggregate {
  stream_count: number;
  ready_count: number;
  complete_count: number;
  blocked_count: number;
  revision_count: number;
  page_count: number;
  pages_succeeded: number;
}

export interface WalletCaseCheckpointContinuationPlanResponse {
  plan: {
    public_id: string;
    contract_version: "wallet_case_checkpoint_continuation_plan_v1";
    content_hash_sha256: string;
    checkpoint_cutoff_public_id: string | null;
  } & WalletCaseCheckpointContinuationPlanAggregate;
  document: {
    contract_version: "wallet_case_checkpoint_continuation_plan_v1";
    case_public_id: string;
    checkpoint_cutoff_public_id: string | null;
    aggregate: WalletCaseCheckpointContinuationPlanAggregate;
    streams: WalletCaseCheckpointContinuationPlanStream[];
    limitations: WalletCaseLimitation[];
  };
}

export interface WalletCaseCheckpointContinuationReceiptInput {
  continuation_plan_public_id: string;
  checkpoint: WalletCaseStreamCheckpointDescriptor;
  chain_public_id: string;
  chain_content_hash_sha256: string;
  revision_count: number;
  page_count: number;
  pages_succeeded: number;
  next_page_index: number;
}

export interface WalletCaseCheckpointContinuationReceiptOutput {
  checkpoint: WalletCaseStreamCheckpointDescriptor;
  chain_public_id: string;
  chain_content_hash_sha256: string;
  revision_count: number;
  page_count: number;
  pages_succeeded: number;
  resume_state: WalletCaseStreamResumeState;
  next_page_index: number | null;
  resume_blocker: string | null;
}

export interface WalletCaseCheckpointContinuationReceiptV1Response {
  receipt: {
    public_id: string;
    contract_version: "wallet_case_checkpoint_continuation_receipt_v1";
    content_hash_sha256: string;
    sync_public_id: string;
    input_plan_public_id: string;
    input_checkpoint_public_id: string;
    output_checkpoint_public_id: string;
    after_plan_public_id: string;
    revision_delta: 1;
    page_count_delta: number;
    pages_succeeded_delta: number;
  };
  document: {
    contract_version: "wallet_case_checkpoint_continuation_receipt_v1";
    case_public_id: string;
    sync_public_id: string;
    input: WalletCaseCheckpointContinuationReceiptInput;
    output: WalletCaseCheckpointContinuationReceiptOutput;
    after_plan: WalletCaseCheckpointContinuationPlanResponse;
    transition: {
      checkpoint_changed: true;
      plan_changed: true;
      revision_delta: 1;
      page_count_delta: number;
      pages_succeeded_delta: number;
    };
    limitations: WalletCaseLimitation[];
  };
}

export interface WalletCaseCheckpointContinuationReceiptV2Response {
  receipt: {
    public_id: string;
    contract_version: "wallet_case_checkpoint_continuation_receipt_v2";
    content_hash_sha256: string;
    sync_public_id: string;
    input_plan_public_id: string;
    input_checkpoint_public_id: string;
    output_checkpoint_public_id: string;
    after_plan_public_id: string;
    revision_delta: 1;
    page_count_delta: number;
    pages_succeeded_delta: number;
    page_budget: number;
    page_budget_consumed: number;
    page_budget_remaining: number;
  };
  document: {
    contract_version: "wallet_case_checkpoint_continuation_receipt_v2";
    case_public_id: string;
    sync_public_id: string;
    input: WalletCaseCheckpointContinuationReceiptInput & {
      page_budget: number;
    };
    output: WalletCaseCheckpointContinuationReceiptOutput;
    after_plan: WalletCaseCheckpointContinuationPlanResponse;
    transition: {
      checkpoint_changed: true;
      plan_changed: true;
      revision_delta: 1;
      page_count_delta: number;
      pages_succeeded_delta: number;
      page_budget_consumed: number;
      page_budget_remaining: number;
    };
    limitations: WalletCaseLimitation[];
  };
}

export interface WalletCaseCheckpointContinuationReceiptV3Response {
  receipt: Omit<WalletCaseCheckpointContinuationReceiptV2Response["receipt"], "contract_version"> & {
    contract_version: "wallet_case_checkpoint_continuation_receipt_v3";
    input_schedule_public_id: string;
  };
  document: Omit<WalletCaseCheckpointContinuationReceiptV2Response["document"], "contract_version" | "input"> & {
    contract_version: "wallet_case_checkpoint_continuation_receipt_v3";
    input: WalletCaseCheckpointContinuationReceiptV2Response["document"]["input"] & {
      backfill_schedule_public_id: string;
    };
  };
}

export type WalletCaseCheckpointContinuationReceiptResponse =
  | WalletCaseCheckpointContinuationReceiptV1Response
  | WalletCaseCheckpointContinuationReceiptV2Response
  | WalletCaseCheckpointContinuationReceiptV3Response;

export type WalletCaseBackfillOutcomeState =
  | "advanced"
  | "completed"
  | "blocked"
  | "no_progress";

export interface WalletCaseBackfillOutcomeTransition {
  provider: string;
  stream_key: string;
  input_checkpoint_public_id: string;
  output_checkpoint_public_id: string;
  before_resume_state: "ready";
  after_resume_state: WalletCaseStreamResumeState;
  revision_delta: 1;
  page_count_delta: number;
  pages_succeeded_delta: number;
  continuation_revision_delta: 1;
  continuation_page_count_delta: number;
  continuation_pages_succeeded_delta: number;
  ready_count_delta: number;
  complete_count_delta: number;
  blocked_count_delta: number;
  frontier_changed: boolean;
}

export interface WalletCaseBackfillOutcomeResponse {
  outcome: {
    public_id: string;
    contract_version: "wallet_case_backfill_outcome_v1";
    content_hash_sha256: string;
    sync_public_id: string;
    outcome: WalletCaseBackfillOutcomeState;
    input_schedule_public_id: string;
    continuation_receipt_public_id: string;
    input_progress_public_id: string;
    output_progress_public_id: string;
    provider: string;
    stream_key: string;
    page_count_delta: number;
    pages_succeeded_delta: number;
    before_resume_state: "ready";
    after_resume_state: WalletCaseStreamResumeState;
  };
  document: {
    contract_version: "wallet_case_backfill_outcome_v1";
    case_public_id: string;
    sync_public_id: string;
    input_schedule: WalletCaseBackfillScheduleResponse;
    input_progress: WalletCaseBackfillProgressResponse;
    continuation_receipt: WalletCaseCheckpointContinuationReceiptV3Response;
    output_progress: WalletCaseBackfillProgressResponse;
    outcome: WalletCaseBackfillOutcomeState;
    transition: WalletCaseBackfillOutcomeTransition;
    limitations: WalletCaseLimitation[];
  };
}

const PUBLIC_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const CHECKPOINT_ID = /^scp_([0-9a-f]{64})$/;
const CHECKPOINT_CHAIN_ID = /^cch_([0-9a-f]{64})$/;
const BACKFILL_PROGRESS_ID = /^bfp_([0-9a-f]{64})$/;
const BACKFILL_SCHEDULE_ID = /^bfs_([0-9a-f]{64})$/;
const BACKFILL_OUTCOME_ID = /^bfo_([0-9a-f]{64})$/;
const CHECKPOINT_CONTINUATION_PLAN_ID = /^cpl_([0-9a-f]{64})$/;
const CHECKPOINT_CONTINUATION_RECEIPT_ID = /^ctr_([0-9a-f]{64})$/;
const MANIFEST_ID = /^smf_([0-9a-f]{64})$/;
const RESUME_STATES = new Set<WalletCaseStreamResumeState>([
  "ready", "complete", "blocked",
]);

function fail(message: string): never {
  throw new Error(message);
}

function record(
  value: unknown,
  keys: readonly string[],
  label: string,
): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    fail(`${label} is invalid`);
  }
  const item = value as Record<string, unknown>;
  if (
    Object.keys(item).length !== keys.length ||
    keys.some((key) => !Object.prototype.hasOwnProperty.call(item, key))
  ) fail(`${label} shape is invalid`);
  return item;
}

function text(value: unknown, label: string, maximum: number): string {
  if (
    typeof value !== "string" || !value || value !== value.trim() ||
    value.length > maximum
  ) fail(`${label} is invalid`);
  return value;
}

function nullableText(
  value: unknown,
  label: string,
  maximum: number,
): string | null {
  return value === null ? null : text(value, label, maximum);
}

function integer(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0) {
    fail(`${label} is invalid`);
  }
  return value as number;
}

function signedInteger(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value)) fail(`${label} is invalid`);
  return value as number;
}

function timestamp(value: unknown, label: string): string {
  const result = text(value, label, 40);
  if (!Number.isFinite(Date.parse(result))) fail(`${label} is invalid`);
  return result;
}

function nullableTimestamp(value: unknown, label: string): string | null {
  return value === null ? null : timestamp(value, label);
}

function publicId(value: unknown, label: string): string {
  const result = text(value, label, 36);
  if (!PUBLIC_ID.test(result)) fail(`${label} is invalid`);
  return result;
}

function digest(value: unknown, label: string): string {
  const result = text(value, label, 64);
  if (!SHA256.test(result)) fail(`${label} is invalid`);
  return result;
}

function resumeState(value: unknown, label: string): WalletCaseStreamResumeState {
  const result = text(value, label, 16) as WalletCaseStreamResumeState;
  if (!RESUME_STATES.has(result)) fail(`${label} is invalid`);
  return result;
}

function checkpointId(value: unknown, label: string): string {
  const result = text(value, label, 68);
  if (!CHECKPOINT_ID.test(result)) fail(`${label} is invalid`);
  return result;
}

function limitations(value: unknown, label: string): WalletCaseLimitation[] {
  if (!Array.isArray(value)) fail(`${label} are invalid`);
  return value.map((entry, index) => {
    const item = record(entry, ["code", "message"], `${label} ${index}`);
    return {
      code: text(item.code, `${label} ${index} code`, 64),
      message: text(item.message, `${label} ${index} message`, 500),
    };
  });
}

function period(value: unknown): WalletCaseSyncManifestPeriod {
  const item = record(value, ["start_at", "end_at"], "checkpoint period");
  const start = nullableTimestamp(item.start_at, "checkpoint period start");
  const end = nullableTimestamp(item.end_at, "checkpoint period end");
  if (
    (start === null) !== (end === null) ||
    (start !== null && end !== null && Date.parse(start) >= Date.parse(end))
  ) fail("checkpoint period is invalid");
  return { start_at: start, end_at: end };
}

function lastPage(value: unknown): WalletCaseStreamCheckpointLastPage | null {
  if (value === null) return null;
  const item = record(value, [
    "page_index", "response_cursor", "response_digest_sha256",
    "min_logical_time", "max_logical_time", "min_timestamp", "max_timestamp",
    "fetched_at",
  ], "checkpoint last page");
  return {
    page_index: integer(item.page_index, "checkpoint last page index"),
    response_cursor: nullableText(
      item.response_cursor, "checkpoint last page cursor", 128,
    ),
    response_digest_sha256: item.response_digest_sha256 === null
      ? null : digest(item.response_digest_sha256, "checkpoint response digest"),
    min_logical_time: nullableText(
      item.min_logical_time, "checkpoint minimum logical time", 20,
    ),
    max_logical_time: nullableText(
      item.max_logical_time, "checkpoint maximum logical time", 20,
    ),
    min_timestamp: nullableTimestamp(
      item.min_timestamp, "checkpoint minimum timestamp",
    ),
    max_timestamp: nullableTimestamp(
      item.max_timestamp, "checkpoint maximum timestamp",
    ),
    fetched_at: nullableTimestamp(item.fetched_at, "checkpoint fetched time"),
  };
}

function parseDocument(value: unknown): WalletCaseStreamCheckpointDocument {
  const item = record(value, [
    "contract_version", "case_public_id", "source_sync_public_id",
    "source_manifest_public_id", "source_manifest_hash_sha256", "provider",
    "stream_key", "provider_contract_version", "acquisition_mode",
    "requested_period", "sort_order", "page_size", "page_cap",
    "completion_state", "termination_reason", "page_count", "pages_succeeded",
    "resume_state", "resume_blocker", "continuation_cursor",
    "continuation_page_index", "last_successful_page",
  ], "stream checkpoint document");
  if (item.contract_version !== "wallet_case_stream_checkpoint_v1") {
    fail("stream checkpoint contract is unsupported");
  }
  const sourceManifestHash = digest(
    item.source_manifest_hash_sha256,
    "stream checkpoint source manifest hash",
  );
  const sourceManifestId = text(
    item.source_manifest_public_id,
    "stream checkpoint source manifest id",
    68,
  );
  if (MANIFEST_ID.exec(sourceManifestId)?.[1] !== sourceManifestHash) {
    fail("stream checkpoint source manifest identity is invalid");
  }
  const mode = text(item.acquisition_mode, "stream checkpoint mode", 16);
  if (mode !== "bounded" && mode !== "incremental" && mode !== "resume") {
    fail("stream checkpoint mode is invalid");
  }
  const state = resumeState(item.resume_state, "stream checkpoint resume state");
  const blocker = nullableText(item.resume_blocker, "stream checkpoint blocker", 64);
  const cursor = nullableText(item.continuation_cursor, "stream checkpoint cursor", 128);
  const continuationPage = item.continuation_page_index === null
    ? null : integer(item.continuation_page_index, "stream checkpoint next page");
  const ready = state === "ready";
  if (
    ready !== (cursor !== null) || ready !== (continuationPage !== null) ||
    (continuationPage !== null && continuationPage < 1) ||
    (state === "blocked") !== (blocker !== null)
  ) fail("stream checkpoint continuation state is inconsistent");
  const pageCount = integer(item.page_count, "stream checkpoint page count");
  const pagesSucceeded = integer(
    item.pages_succeeded,
    "stream checkpoint pages succeeded",
  );
  const parsedLastPage = lastPage(item.last_successful_page);
  if (
    pagesSucceeded > pageCount ||
    (pagesSucceeded === 0) !== (parsedLastPage === null) ||
    (ready && parsedLastPage?.response_cursor !== cursor) ||
    (ready && parsedLastPage !== null && continuationPage !== parsedLastPage.page_index + 1)
  ) fail("stream checkpoint page evidence is inconsistent");
  return {
    contract_version: "wallet_case_stream_checkpoint_v1",
    case_public_id: publicId(item.case_public_id, "stream checkpoint case id"),
    source_sync_public_id: publicId(
      item.source_sync_public_id,
      "stream checkpoint source sync id",
    ),
    source_manifest_public_id: sourceManifestId,
    source_manifest_hash_sha256: sourceManifestHash,
    provider: text(item.provider, "stream checkpoint provider", 64),
    stream_key: text(item.stream_key, "stream checkpoint key", 40),
    provider_contract_version: text(
      item.provider_contract_version,
      "stream checkpoint provider contract",
      48,
    ),
    acquisition_mode: mode,
    requested_period: period(item.requested_period),
    sort_order: nullableText(item.sort_order, "stream checkpoint sort order", 32),
    page_size: integer(item.page_size, "stream checkpoint page size"),
    page_cap: integer(item.page_cap, "stream checkpoint page cap"),
    completion_state: text(
      item.completion_state, "stream checkpoint completion state", 24,
    ),
    termination_reason: nullableText(
      item.termination_reason, "stream checkpoint termination", 48,
    ),
    page_count: pageCount,
    pages_succeeded: pagesSucceeded,
    resume_state: state,
    resume_blocker: blocker,
    continuation_cursor: cursor,
    continuation_page_index: continuationPage,
    last_successful_page: parsedLastPage,
  };
}

function parseDescriptor(value: unknown): WalletCaseStreamCheckpointDescriptor {
  const descriptor = record(value, [
    "public_id", "contract_version", "checkpoint_hash_sha256", "provider",
    "stream_key", "provider_contract_version", "source_sync_public_id",
    "resume_state", "created_at",
  ], "stream checkpoint descriptor");
  if (descriptor.contract_version !== "wallet_case_stream_checkpoint_v1") {
    fail("stream checkpoint descriptor contract is unsupported");
  }
  const hash = digest(
    descriptor.checkpoint_hash_sha256,
    "stream checkpoint hash",
  );
  const id = text(descriptor.public_id, "stream checkpoint id", 68);
  if (CHECKPOINT_ID.exec(id)?.[1] !== hash) {
    fail("stream checkpoint identity is invalid");
  }
  return {
    public_id: id,
    contract_version: "wallet_case_stream_checkpoint_v1",
    checkpoint_hash_sha256: hash,
    provider: text(descriptor.provider, "stream checkpoint provider", 64),
    stream_key: text(descriptor.stream_key, "stream checkpoint key", 40),
    provider_contract_version: text(
      descriptor.provider_contract_version,
      "stream checkpoint provider contract",
      48,
    ),
    source_sync_public_id: publicId(
      descriptor.source_sync_public_id,
      "stream checkpoint source sync id",
    ),
    resume_state: resumeState(
      descriptor.resume_state,
      "stream checkpoint resume state",
    ),
    created_at: timestamp(descriptor.created_at, "stream checkpoint creation time"),
  };
}

function parseCheckpoint(value: unknown): WalletCaseStreamCheckpointResponse {
  const envelope = record(value, ["checkpoint", "document"], "stream checkpoint");
  const parsedDescriptor = parseDescriptor(envelope.checkpoint);
  const document = parseDocument(envelope.document);
  if (
    parsedDescriptor.provider !== document.provider ||
    parsedDescriptor.stream_key !== document.stream_key ||
    parsedDescriptor.provider_contract_version !== document.provider_contract_version ||
    parsedDescriptor.source_sync_public_id !== document.source_sync_public_id ||
    parsedDescriptor.resume_state !== document.resume_state
  ) fail("stream checkpoint descriptor does not match its document");
  return { checkpoint: parsedDescriptor, document };
}

function parseLineage(value: unknown): WalletCaseStreamCheckpointLineage {
  const item = record(value, [
    "acquisition_mode", "base_snapshot_public_id",
    "parent_checkpoint_public_id", "chain_depth",
  ], "stream checkpoint lineage");
  const mode = text(item.acquisition_mode, "stream checkpoint lineage mode", 16);
  if (mode !== "bounded" && mode !== "incremental" && mode !== "resume") {
    fail("stream checkpoint lineage mode is invalid");
  }
  const baseId = item.base_snapshot_public_id === null
    ? null : publicId(item.base_snapshot_public_id, "stream checkpoint base snapshot id");
  const parentId = item.parent_checkpoint_public_id === null
    ? null : checkpointId(
      item.parent_checkpoint_public_id,
      "stream checkpoint parent id",
    );
  const chainDepth = integer(item.chain_depth, "stream checkpoint lineage depth");
  if (
    (mode === "bounded" && (baseId !== null || parentId !== null || chainDepth !== 0)) ||
    (mode === "incremental" && (baseId === null || parentId !== null || chainDepth !== 0)) ||
    (mode === "resume" && (baseId === null || parentId === null || chainDepth < 1))
  ) fail("stream checkpoint lineage is inconsistent");
  return {
    acquisition_mode: mode,
    base_snapshot_public_id: baseId,
    parent_checkpoint_public_id: parentId,
    chain_depth: chainDepth,
  };
}

export function parseWalletCaseStreamCheckpointDetail(
  value: unknown,
): WalletCaseStreamCheckpointDetailResponse {
  const item = record(
    value,
    ["checkpoint", "document", "lineage"],
    "stream checkpoint detail",
  );
  const checkpoint = parseCheckpoint({
    checkpoint: item.checkpoint,
    document: item.document,
  });
  const lineage = parseLineage(item.lineage);
  if (lineage.acquisition_mode !== checkpoint.document.acquisition_mode) {
    fail("stream checkpoint detail lineage does not match its document");
  }
  return { ...checkpoint, lineage };
}

export function parseWalletCaseStreamCheckpointHistory(
  value: unknown,
): WalletCaseStreamCheckpointHistoryResponse {
  const item = record(value, [
    "contract_version", "case_public_id", "revision_cutoff_public_id", "items",
    "aggregate", "page", "limitations",
  ], "stream checkpoint history");
  if (item.contract_version !== "wallet_case_stream_checkpoint_history_v1") {
    fail("stream checkpoint history contract is unsupported");
  }
  const caseId = publicId(item.case_public_id, "stream checkpoint history case id");
  const cutoffId = item.revision_cutoff_public_id === null
    ? null : checkpointId(
      item.revision_cutoff_public_id,
      "stream checkpoint history cutoff id",
    );
  if (!Array.isArray(item.items) || item.items.length > 50) {
    fail("stream checkpoint history items are invalid");
  }
  const items = item.items.map((value, index) => {
    const entry = record(value, [
      "checkpoint", "lineage", "continuation_page_index", "page_count",
      "pages_succeeded",
    ], `stream checkpoint history item ${index}`);
    const checkpoint = parseDescriptor(entry.checkpoint);
    const lineage = parseLineage(entry.lineage);
    const continuationPage = entry.continuation_page_index === null
      ? null : integer(
        entry.continuation_page_index,
        `stream checkpoint history item ${index} continuation page`,
      );
    const pageCount = integer(
      entry.page_count,
      `stream checkpoint history item ${index} page count`,
    );
    const pagesSucceeded = integer(
      entry.pages_succeeded,
      `stream checkpoint history item ${index} pages succeeded`,
    );
    if (
      pagesSucceeded > pageCount ||
      (checkpoint.resume_state === "ready") !== (continuationPage !== null) ||
      (continuationPage !== null && continuationPage < 1)
    ) fail(`stream checkpoint history item ${index} is inconsistent`);
    return {
      checkpoint,
      lineage,
      continuation_page_index: continuationPage,
      page_count: pageCount,
      pages_succeeded: pagesSucceeded,
    };
  });
  const aggregate = record(
    item.aggregate,
    ["total_revisions", "returned_count"],
    "stream checkpoint history aggregate",
  );
  const totalRevisions = integer(
    aggregate.total_revisions,
    "stream checkpoint history total revisions",
  );
  const returnedCount = integer(
    aggregate.returned_count,
    "stream checkpoint history returned count",
  );
  const page = record(
    item.page,
    ["limit", "has_more", "next_cursor"],
    "stream checkpoint history page",
  );
  const limit = integer(page.limit, "stream checkpoint history limit");
  const hasMore = page.has_more;
  if (typeof hasMore !== "boolean") fail("stream checkpoint history has-more flag is invalid");
  const nextCursor = nullableText(
    page.next_cursor,
    "stream checkpoint history cursor",
    1024,
  );
  const parsedLimitations = limitations(
    item.limitations,
    "stream checkpoint history limitations",
  );
  if (
    limit < 1 || limit > 50 || items.length > limit ||
    returnedCount !== items.length || returnedCount > totalRevisions ||
    (hasMore && returnedCount >= totalRevisions) ||
    (cutoffId === null) !== (totalRevisions === 0) ||
    hasMore !== (nextCursor !== null) ||
    new Set(items.map(({ checkpoint }) => checkpoint.public_id)).size !== items.length
  ) fail("stream checkpoint history is inconsistent");
  return {
    contract_version: "wallet_case_stream_checkpoint_history_v1",
    case_public_id: caseId,
    revision_cutoff_public_id: cutoffId,
    items,
    aggregate: { total_revisions: totalRevisions, returned_count: returnedCount },
    page: { limit, has_more: hasMore, next_cursor: nextCursor },
    limitations: parsedLimitations,
  };
}

export function parseWalletCaseStreamCheckpointChain(
  value: unknown,
): WalletCaseStreamCheckpointChainResponse {
  const envelope = record(value, ["chain", "document"], "checkpoint chain response");
  const chain = record(envelope.chain, [
    "public_id", "contract_version", "content_hash_sha256", "revision_count",
    "page_count", "pages_succeeded",
  ], "checkpoint chain descriptor");
  if (chain.contract_version !== "wallet_case_stream_checkpoint_chain_v1") {
    fail("checkpoint chain descriptor contract is unsupported");
  }
  const contentHash = digest(chain.content_hash_sha256, "checkpoint chain hash");
  const chainId = text(chain.public_id, "checkpoint chain id", 68);
  if (CHECKPOINT_CHAIN_ID.exec(chainId)?.[1] !== contentHash) {
    fail("checkpoint chain identity is invalid");
  }
  const revisionCount = integer(chain.revision_count, "checkpoint chain revision count");
  const pageCount = integer(chain.page_count, "checkpoint chain page count");
  const pagesSucceeded = integer(
    chain.pages_succeeded,
    "checkpoint chain pages succeeded",
  );
  const document = record(envelope.document, [
    "contract_version", "case_public_id", "tip_checkpoint_public_id", "provider",
    "stream_key", "provider_contract_version", "root_acquisition_mode",
    "root_base_snapshot_public_id", "current_resume_state", "next_page_index",
    "aggregate", "revisions", "limitations",
  ], "checkpoint chain document");
  if (document.contract_version !== "wallet_case_stream_checkpoint_chain_v1") {
    fail("checkpoint chain document contract is unsupported");
  }
  const caseId = publicId(document.case_public_id, "checkpoint chain case id");
  const tipId = checkpointId(
    document.tip_checkpoint_public_id,
    "checkpoint chain tip id",
  );
  const provider = text(document.provider, "checkpoint chain provider", 64);
  const streamKey = text(document.stream_key, "checkpoint chain stream key", 40);
  const providerContract = text(
    document.provider_contract_version,
    "checkpoint chain provider contract",
    48,
  );
  const rootMode = text(
    document.root_acquisition_mode,
    "checkpoint chain root mode",
    16,
  );
  if (rootMode !== "bounded" && rootMode !== "incremental") {
    fail("checkpoint chain root mode is invalid");
  }
  const rootBase = document.root_base_snapshot_public_id === null
    ? null : publicId(
      document.root_base_snapshot_public_id,
      "checkpoint chain root base id",
    );
  const currentState = resumeState(
    document.current_resume_state,
    "checkpoint chain current resume state",
  );
  const nextPage = document.next_page_index === null
    ? null : integer(document.next_page_index, "checkpoint chain next page");
  const aggregate = record(document.aggregate, [
    "revision_count", "page_count", "pages_succeeded",
  ], "checkpoint chain aggregate");
  const aggregateRevisionCount = integer(
    aggregate.revision_count,
    "checkpoint chain aggregate revision count",
  );
  const aggregatePageCount = integer(
    aggregate.page_count,
    "checkpoint chain aggregate page count",
  );
  const aggregatePagesSucceeded = integer(
    aggregate.pages_succeeded,
    "checkpoint chain aggregate pages succeeded",
  );
  if (!Array.isArray(document.revisions) || document.revisions.length < 1 || document.revisions.length > 100) {
    fail("checkpoint chain revisions are invalid");
  }
  const revisions = document.revisions.map((value, index) => {
    const item = record(value, [
      "ordinal", "checkpoint", "acquisition_mode", "base_snapshot_public_id",
      "parent_checkpoint_public_id", "source_manifest_public_id",
      "source_manifest_hash_sha256", "requested_period",
      "continuation_page_index", "page_count", "pages_succeeded",
      "last_response_digest_sha256",
    ], `checkpoint chain revision ${index}`);
    const checkpoint = parseDescriptor(item.checkpoint);
    const mode = text(
      item.acquisition_mode,
      `checkpoint chain revision ${index} mode`,
      16,
    ) as WalletCaseSyncMode;
    if (mode !== "bounded" && mode !== "incremental" && mode !== "resume") {
      fail(`checkpoint chain revision ${index} mode is invalid`);
    }
    const baseId = item.base_snapshot_public_id === null
      ? null : publicId(
        item.base_snapshot_public_id,
        `checkpoint chain revision ${index} base id`,
      );
    const parentId = item.parent_checkpoint_public_id === null
      ? null : checkpointId(
        item.parent_checkpoint_public_id,
        `checkpoint chain revision ${index} parent id`,
      );
    const manifestHash = digest(
      item.source_manifest_hash_sha256,
      `checkpoint chain revision ${index} manifest hash`,
    );
    const manifestId = text(
      item.source_manifest_public_id,
      `checkpoint chain revision ${index} manifest id`,
      68,
    );
    if (MANIFEST_ID.exec(manifestId)?.[1] !== manifestHash) {
      fail(`checkpoint chain revision ${index} manifest identity is invalid`);
    }
    const continuationPage = item.continuation_page_index === null
      ? null : integer(
        item.continuation_page_index,
        `checkpoint chain revision ${index} continuation page`,
      );
    const revisionPageCount = integer(
      item.page_count,
      `checkpoint chain revision ${index} page count`,
    );
    const revisionPagesSucceeded = integer(
      item.pages_succeeded,
      `checkpoint chain revision ${index} pages succeeded`,
    );
    if (
      revisionPagesSucceeded > revisionPageCount ||
      (checkpoint.resume_state === "ready") !== (continuationPage !== null) ||
      (continuationPage !== null && continuationPage < 1)
    ) fail(`checkpoint chain revision ${index} continuation is inconsistent`);
    return {
      ordinal: integer(item.ordinal, `checkpoint chain revision ${index} ordinal`),
      checkpoint,
      acquisition_mode: mode,
      base_snapshot_public_id: baseId,
      parent_checkpoint_public_id: parentId,
      source_manifest_public_id: manifestId,
      source_manifest_hash_sha256: manifestHash,
      requested_period: period(item.requested_period),
      continuation_page_index: continuationPage,
      page_count: revisionPageCount,
      pages_succeeded: revisionPagesSucceeded,
      last_response_digest_sha256: item.last_response_digest_sha256 === null
        ? null : digest(
          item.last_response_digest_sha256,
          `checkpoint chain revision ${index} response digest`,
        ),
    };
  });
  const root = revisions[0];
  const tip = revisions[revisions.length - 1];
  if (
    revisionCount < 1 || revisionCount > 100 ||
    revisionCount !== revisions.length ||
    revisionCount !== aggregateRevisionCount ||
    pageCount !== aggregatePageCount || pagesSucceeded !== aggregatePagesSucceeded ||
    pageCount !== revisions.reduce((sum, item) => sum + item.page_count, 0) ||
    pagesSucceeded !== revisions.reduce((sum, item) => sum + item.pages_succeeded, 0) ||
    pagesSucceeded > pageCount ||
    root.ordinal !== 0 || root.acquisition_mode !== rootMode ||
    root.base_snapshot_public_id !== rootBase || root.parent_checkpoint_public_id !== null ||
    (rootMode === "bounded") !== (rootBase === null) ||
    tip.checkpoint.public_id !== tipId || tip.checkpoint.resume_state !== currentState ||
    tip.continuation_page_index !== nextPage ||
    (currentState === "ready") !== (nextPage !== null)
  ) fail("checkpoint chain endpoints or aggregate are inconsistent");
  for (let index = 0; index < revisions.length; index += 1) {
    const revision = revisions[index];
    if (
      revision.ordinal !== index ||
      revision.checkpoint.provider !== provider ||
      revision.checkpoint.stream_key !== streamKey ||
      revision.checkpoint.provider_contract_version !== providerContract
    ) fail("checkpoint chain revision identity is inconsistent");
    if (index > 0) {
      const parent = revisions[index - 1];
      if (
        revision.acquisition_mode !== "resume" ||
        revision.parent_checkpoint_public_id !== parent.checkpoint.public_id ||
        revision.base_snapshot_public_id !== parent.checkpoint.source_sync_public_id
      ) fail("checkpoint chain parent lineage is inconsistent");
    }
  }
  return {
    chain: {
      public_id: chainId,
      contract_version: "wallet_case_stream_checkpoint_chain_v1",
      content_hash_sha256: contentHash,
      revision_count: revisionCount,
      page_count: pageCount,
      pages_succeeded: pagesSucceeded,
    },
    document: {
      contract_version: "wallet_case_stream_checkpoint_chain_v1",
      case_public_id: caseId,
      tip_checkpoint_public_id: tipId,
      provider,
      stream_key: streamKey,
      provider_contract_version: providerContract,
      root_acquisition_mode: rootMode,
      root_base_snapshot_public_id: rootBase,
      current_resume_state: currentState,
      next_page_index: nextPage,
      aggregate: {
        revision_count: aggregateRevisionCount,
        page_count: aggregatePageCount,
        pages_succeeded: aggregatePagesSucceeded,
      },
      revisions,
      limitations: limitations(document.limitations, "checkpoint chain limitations"),
    },
  };
}

export function serializeWalletCaseStreamCheckpointChain(value: unknown): string {
  return `${JSON.stringify(parseWalletCaseStreamCheckpointChain(value), null, 2)}\n`;
}

function parseBackfillProgressAggregate(
  value: Record<string, unknown>,
  label: string,
): WalletCaseBackfillProgressAggregate {
  const aggregate = {
    stream_count: integer(value.stream_count, `${label} stream count`),
    ready_count: integer(value.ready_count, `${label} ready count`),
    complete_count: integer(value.complete_count, `${label} complete count`),
    blocked_count: integer(value.blocked_count, `${label} blocked count`),
    revision_count: integer(value.revision_count, `${label} revision count`),
    continuation_revision_count: integer(
      value.continuation_revision_count,
      `${label} continuation revision count`,
    ),
    page_count: integer(value.page_count, `${label} page count`),
    pages_succeeded: integer(value.pages_succeeded, `${label} pages succeeded`),
    continuation_page_count: integer(
      value.continuation_page_count,
      `${label} continuation page count`,
    ),
    continuation_pages_succeeded: integer(
      value.continuation_pages_succeeded,
      `${label} continuation pages succeeded`,
    ),
    observed_frontier_count: integer(
      value.observed_frontier_count,
      `${label} observed frontier count`,
    ),
    advanced_frontier_count: integer(
      value.advanced_frontier_count,
      `${label} advanced frontier count`,
    ),
  };
  if (
    aggregate.stream_count > 32 || aggregate.ready_count > 32 ||
    aggregate.complete_count > 32 || aggregate.blocked_count > 32 ||
    aggregate.revision_count > 3_200 ||
    aggregate.continuation_revision_count > 3_168 ||
    aggregate.observed_frontier_count > 32 ||
    aggregate.advanced_frontier_count > aggregate.observed_frontier_count ||
    aggregate.pages_succeeded > aggregate.page_count ||
    aggregate.continuation_pages_succeeded > aggregate.continuation_page_count ||
    aggregate.stream_count !== aggregate.ready_count + aggregate.complete_count + aggregate.blocked_count
  ) fail(`${label} is inconsistent`);
  return aggregate;
}

function parseBackfillFrontier(
  value: unknown,
  label: string,
): WalletCaseBackfillProgressFrontier | null {
  if (value === null) return null;
  const item = record(value, ["checkpoint_public_id", "page"], label);
  const page = lastPage(item.page);
  if (page === null) fail(`${label} page is invalid`);
  return {
    checkpoint_public_id: checkpointId(
      item.checkpoint_public_id,
      `${label} checkpoint id`,
    ),
    page,
  };
}

export function parseWalletCaseBackfillProgress(
  value: unknown,
): WalletCaseBackfillProgressResponse {
  const envelope = record(value, ["progress", "document"], "backfill progress response");
  const descriptor = record(envelope.progress, [
    "public_id", "contract_version", "content_hash_sha256",
    "checkpoint_cutoff_public_id", "stream_count", "ready_count",
    "complete_count", "blocked_count", "revision_count",
    "continuation_revision_count", "page_count", "pages_succeeded",
    "continuation_page_count", "continuation_pages_succeeded",
    "observed_frontier_count", "advanced_frontier_count",
  ], "backfill progress descriptor");
  if (descriptor.contract_version !== "wallet_case_backfill_progress_v1") {
    fail("backfill progress descriptor contract is unsupported");
  }
  const contentHash = digest(
    descriptor.content_hash_sha256,
    "backfill progress hash",
  );
  const progressId = text(descriptor.public_id, "backfill progress id", 68);
  if (BACKFILL_PROGRESS_ID.exec(progressId)?.[1] !== contentHash) {
    fail("backfill progress identity is invalid");
  }
  const descriptorCutoff = descriptor.checkpoint_cutoff_public_id === null
    ? null
    : checkpointId(
      descriptor.checkpoint_cutoff_public_id,
      "backfill progress descriptor cutoff",
    );
  const descriptorAggregate = parseBackfillProgressAggregate(
    descriptor,
    "backfill progress descriptor",
  );
  const document = record(envelope.document, [
    "contract_version", "case_public_id", "checkpoint_cutoff_public_id",
    "aggregate", "streams", "limitations",
  ], "backfill progress document");
  if (document.contract_version !== "wallet_case_backfill_progress_v1") {
    fail("backfill progress document contract is unsupported");
  }
  const caseId = publicId(document.case_public_id, "backfill progress case id");
  const cutoff = document.checkpoint_cutoff_public_id === null
    ? null
    : checkpointId(
      document.checkpoint_cutoff_public_id,
      "backfill progress cutoff",
    );
  const aggregate = parseBackfillProgressAggregate(
    record(document.aggregate, [
      "stream_count", "ready_count", "complete_count", "blocked_count",
      "revision_count", "continuation_revision_count", "page_count",
      "pages_succeeded", "continuation_page_count",
      "continuation_pages_succeeded", "observed_frontier_count",
      "advanced_frontier_count",
    ], "backfill progress aggregate"),
    "backfill progress aggregate",
  );
  if (!Array.isArray(document.streams) || document.streams.length > 32) {
    fail("backfill progress streams are invalid");
  }
  const streams = document.streams.map((value, index) => {
    const label = `backfill progress stream ${index}`;
    const item = record(value, [
      "provider", "stream_key", "provider_contract_version",
      "root_checkpoint_public_id", "tip_checkpoint", "chain_public_id",
      "chain_content_hash_sha256", "root_acquisition_mode",
      "requested_period", "revision_count", "initial_page_count",
      "initial_pages_succeeded", "continuation_revision_count",
      "continuation_page_count", "continuation_pages_succeeded",
      "page_count", "pages_succeeded", "resume_state",
      "requested_interval_complete", "next_page_index", "termination_reason",
      "resume_blocker", "root_frontier", "current_frontier",
      "frontier_advanced",
    ], label);
    const provider = text(item.provider, `${label} provider`, 64);
    const streamKey = text(item.stream_key, `${label} key`, 40);
    const providerContract = text(
      item.provider_contract_version,
      `${label} provider contract`,
      48,
    );
    const rootCheckpointId = checkpointId(
      item.root_checkpoint_public_id,
      `${label} root checkpoint id`,
    );
    const tip = parseDescriptor(item.tip_checkpoint);
    const chainHash = digest(item.chain_content_hash_sha256, `${label} chain hash`);
    const chainId = text(item.chain_public_id, `${label} chain id`, 68);
    const rootMode = text(item.root_acquisition_mode, `${label} root mode`, 16);
    if (rootMode !== "bounded" && rootMode !== "incremental") {
      fail(`${label} root mode is invalid`);
    }
    const revisionCount = integer(item.revision_count, `${label} revision count`);
    const initialPageCount = integer(item.initial_page_count, `${label} initial page count`);
    const initialPagesSucceeded = integer(
      item.initial_pages_succeeded,
      `${label} initial pages succeeded`,
    );
    const continuationRevisionCount = integer(
      item.continuation_revision_count,
      `${label} continuation revision count`,
    );
    const continuationPageCount = integer(
      item.continuation_page_count,
      `${label} continuation page count`,
    );
    const continuationPagesSucceeded = integer(
      item.continuation_pages_succeeded,
      `${label} continuation pages succeeded`,
    );
    const pageCount = integer(item.page_count, `${label} page count`);
    const pagesSucceeded = integer(item.pages_succeeded, `${label} pages succeeded`);
    const state = resumeState(item.resume_state, `${label} resume state`);
    if (typeof item.requested_interval_complete !== "boolean") {
      fail(`${label} requested interval state is invalid`);
    }
    const requestedIntervalComplete = item.requested_interval_complete;
    const nextPage = item.next_page_index === null
      ? null : integer(item.next_page_index, `${label} next page`);
    const terminationReason = nullableText(
      item.termination_reason,
      `${label} termination reason`,
      48,
    );
    const blocker = nullableText(item.resume_blocker, `${label} blocker`, 64);
    const rootFrontier = parseBackfillFrontier(item.root_frontier, `${label} root frontier`);
    const currentFrontier = parseBackfillFrontier(
      item.current_frontier,
      `${label} current frontier`,
    );
    if (typeof item.frontier_advanced !== "boolean") {
      fail(`${label} frontier state is invalid`);
    }
    const frontierAdvanced = item.frontier_advanced;
    if (
      tip.provider !== provider || tip.stream_key !== streamKey ||
      tip.provider_contract_version !== providerContract ||
      tip.resume_state !== state || CHECKPOINT_CHAIN_ID.exec(chainId)?.[1] !== chainHash ||
      revisionCount < 1 || revisionCount > 100 ||
      revisionCount !== continuationRevisionCount + 1 ||
      initialPagesSucceeded > initialPageCount ||
      continuationPagesSucceeded > continuationPageCount ||
      pageCount !== initialPageCount + continuationPageCount ||
      pagesSucceeded !== initialPagesSucceeded + continuationPagesSucceeded ||
      requestedIntervalComplete !== (state === "complete") ||
      (state === "ready") !== (nextPage !== null) ||
      (nextPage !== null && nextPage < 1) ||
      (state === "blocked") !== (blocker !== null) ||
      (rootFrontier === null) !== (initialPagesSucceeded === 0) ||
      (currentFrontier === null) !== (pagesSucceeded === 0) ||
      (rootFrontier !== null && rootFrontier.checkpoint_public_id !== rootCheckpointId) ||
      frontierAdvanced !== (
        rootFrontier !== null && currentFrontier !== null &&
        JSON.stringify(rootFrontier.page) !== JSON.stringify(currentFrontier.page)
      )
    ) fail(`${label} is inconsistent`);
    return {
      provider,
      stream_key: streamKey,
      provider_contract_version: providerContract,
      root_checkpoint_public_id: rootCheckpointId,
      tip_checkpoint: tip,
      chain_public_id: chainId,
      chain_content_hash_sha256: chainHash,
      root_acquisition_mode: rootMode,
      requested_period: period(item.requested_period),
      revision_count: revisionCount,
      initial_page_count: initialPageCount,
      initial_pages_succeeded: initialPagesSucceeded,
      continuation_revision_count: continuationRevisionCount,
      continuation_page_count: continuationPageCount,
      continuation_pages_succeeded: continuationPagesSucceeded,
      page_count: pageCount,
      pages_succeeded: pagesSucceeded,
      resume_state: state,
      requested_interval_complete: requestedIntervalComplete,
      next_page_index: nextPage,
      termination_reason: terminationReason,
      resume_blocker: blocker,
      root_frontier: rootFrontier,
      current_frontier: currentFrontier,
      frontier_advanced: frontierAdvanced,
    } satisfies WalletCaseBackfillProgressStream;
  });
  const keys = streams.map(({ provider, stream_key }) => `${provider}\0${stream_key}`);
  const states = streams.map(({ resume_state }) => resume_state);
  const expectedAggregate: WalletCaseBackfillProgressAggregate = {
    stream_count: streams.length,
    ready_count: states.filter((state) => state === "ready").length,
    complete_count: states.filter((state) => state === "complete").length,
    blocked_count: states.filter((state) => state === "blocked").length,
    revision_count: streams.reduce((total, item) => total + item.revision_count, 0),
    continuation_revision_count: streams.reduce(
      (total, item) => total + item.continuation_revision_count,
      0,
    ),
    page_count: streams.reduce((total, item) => total + item.page_count, 0),
    pages_succeeded: streams.reduce((total, item) => total + item.pages_succeeded, 0),
    continuation_page_count: streams.reduce(
      (total, item) => total + item.continuation_page_count,
      0,
    ),
    continuation_pages_succeeded: streams.reduce(
      (total, item) => total + item.continuation_pages_succeeded,
      0,
    ),
    observed_frontier_count: streams.filter((item) => item.current_frontier !== null).length,
    advanced_frontier_count: streams.filter((item) => item.frontier_advanced).length,
  };
  const cutoffIds = new Set(streams.map(({ tip_checkpoint }) => tip_checkpoint.public_id));
  if (
    JSON.stringify(aggregate) !== JSON.stringify(expectedAggregate) ||
    JSON.stringify(descriptorAggregate) !== JSON.stringify(aggregate) ||
    descriptorCutoff !== cutoff || lenOrNullMismatch(cutoff, streams.length) ||
    (cutoff !== null && !cutoffIds.has(cutoff)) ||
    new Set(keys).size !== keys.length ||
    JSON.stringify(keys) !== JSON.stringify([...keys].sort())
  ) fail("backfill progress is inconsistent");
  return {
    progress: {
      public_id: progressId,
      contract_version: "wallet_case_backfill_progress_v1",
      content_hash_sha256: contentHash,
      checkpoint_cutoff_public_id: descriptorCutoff,
      ...descriptorAggregate,
    },
    document: {
      contract_version: "wallet_case_backfill_progress_v1",
      case_public_id: caseId,
      checkpoint_cutoff_public_id: cutoff,
      aggregate,
      streams,
      limitations: limitations(document.limitations, "backfill progress limitations"),
    },
  };
}

export function serializeWalletCaseBackfillProgress(value: unknown): string {
  return `${JSON.stringify(parseWalletCaseBackfillProgress(value), null, 2)}\n`;
}

export function parseWalletCaseBackfillSchedule(
  value: unknown,
): WalletCaseBackfillScheduleResponse {
  const envelope = record(value, ["schedule", "document"], "backfill schedule response");
  const descriptor = record(envelope.schedule, [
    "public_id", "contract_version", "content_hash_sha256", "state",
    "input_progress_public_id", "input_plan_public_id",
    "checkpoint_cutoff_public_id", "page_budget",
    "selected_checkpoint_public_id", "active_sync_public_id",
  ], "backfill schedule descriptor");
  if (descriptor.contract_version !== "wallet_case_backfill_schedule_v1") {
    fail("backfill schedule descriptor contract is unsupported");
  }
  const contentHash = digest(descriptor.content_hash_sha256, "backfill schedule hash");
  const scheduleId = text(descriptor.public_id, "backfill schedule id", 68);
  if (BACKFILL_SCHEDULE_ID.exec(scheduleId)?.[1] !== contentHash) {
    fail("backfill schedule identity is invalid");
  }
  const descriptorState = backfillScheduleState(
    descriptor.state,
    "backfill schedule descriptor state",
  );
  const descriptorProgressId = backfillProgressId(
    descriptor.input_progress_public_id,
    "backfill schedule descriptor progress id",
  );
  const descriptorPlanId = continuationPlanId(
    descriptor.input_plan_public_id,
    "backfill schedule descriptor plan id",
  );
  const descriptorCutoff = descriptor.checkpoint_cutoff_public_id === null
    ? null : checkpointId(descriptor.checkpoint_cutoff_public_id, "backfill schedule descriptor cutoff");
  const descriptorBudget = backfillPageBudget(
    descriptor.page_budget,
    "backfill schedule descriptor page budget",
  );
  const descriptorSelected = descriptor.selected_checkpoint_public_id === null
    ? null : checkpointId(
      descriptor.selected_checkpoint_public_id,
      "backfill schedule descriptor selected checkpoint",
    );
  const descriptorActive = descriptor.active_sync_public_id === null
    ? null : publicId(descriptor.active_sync_public_id, "backfill schedule descriptor active sync");

  const document = record(envelope.document, [
    "contract_version", "case_public_id", "input_progress_public_id",
    "input_plan_public_id", "checkpoint_cutoff_public_id", "page_budget",
    "selection_policy", "state", "stream_count", "ready_count",
    "complete_count", "blocked_count", "active_sync_public_id", "selection",
    "limitations",
  ], "backfill schedule document");
  if (document.contract_version !== "wallet_case_backfill_schedule_v1") {
    fail("backfill schedule document contract is unsupported");
  }
  const caseId = publicId(document.case_public_id, "backfill schedule case id");
  const progressId = backfillProgressId(
    document.input_progress_public_id,
    "backfill schedule progress id",
  );
  const planId = continuationPlanId(document.input_plan_public_id, "backfill schedule plan id");
  const cutoff = document.checkpoint_cutoff_public_id === null
    ? null : checkpointId(document.checkpoint_cutoff_public_id, "backfill schedule cutoff");
  const pageBudget = backfillPageBudget(document.page_budget, "backfill schedule page budget");
  if (
    document.selection_policy !==
    "least_continuation_pages_then_revisions_then_provider_stream_v1"
  ) fail("backfill schedule selection policy is unsupported");
  const state = backfillScheduleState(document.state, "backfill schedule state");
  const streamCount = integer(document.stream_count, "backfill schedule stream count");
  const readyCount = integer(document.ready_count, "backfill schedule ready count");
  const completeCount = integer(document.complete_count, "backfill schedule complete count");
  const blockedCount = integer(document.blocked_count, "backfill schedule blocked count");
  const activeSyncId = document.active_sync_public_id === null
    ? null : publicId(document.active_sync_public_id, "backfill schedule active sync id");
  let selection: WalletCaseBackfillScheduleSelection | null = null;
  if (document.selection !== null) {
    const item = record(document.selection, [
      "provider", "stream_key", "checkpoint_public_id",
      "continuation_revision_count", "continuation_page_count", "next_page_index",
    ], "backfill schedule selection");
    selection = {
      provider: text(item.provider, "backfill schedule selection provider", 64),
      stream_key: text(item.stream_key, "backfill schedule selection stream", 40),
      checkpoint_public_id: checkpointId(
        item.checkpoint_public_id,
        "backfill schedule selection checkpoint",
      ),
      continuation_revision_count: integer(
        item.continuation_revision_count,
        "backfill schedule selection continuation revisions",
      ),
      continuation_page_count: integer(
        item.continuation_page_count,
        "backfill schedule selection continuation pages",
      ),
      next_page_index: integer(item.next_page_index, "backfill schedule selection next page"),
    };
    if (
      selection.continuation_revision_count > 99 || selection.next_page_index < 1
    ) fail("backfill schedule selection is inconsistent");
  }
  const countsValid = streamCount <= 32 && readyCount <= 32 &&
    completeCount <= 32 && blockedCount <= 32 &&
    streamCount === readyCount + completeCount + blockedCount;
  const stateValid = state === "ready"
    ? readyCount > 0 && activeSyncId === null && selection !== null
    : state === "backpressured"
      ? activeSyncId !== null && selection === null
      : state === "empty"
        ? streamCount === 0 && activeSyncId === null && selection === null
        : state === "complete"
          ? streamCount > 0 && readyCount === 0 && blockedCount === 0 &&
            activeSyncId === null && selection === null
          : readyCount === 0 && blockedCount > 0 && activeSyncId === null && selection === null;
  if (
    !countsValid || !stateValid || descriptorState !== state ||
    descriptorProgressId !== progressId || descriptorPlanId !== planId ||
    descriptorCutoff !== cutoff || descriptorBudget !== pageBudget ||
    descriptorSelected !== (
      selection === null ? null : selection.checkpoint_public_id
    ) ||
    descriptorActive !== activeSyncId
  ) fail("backfill schedule is inconsistent");
  return {
    schedule: {
      public_id: scheduleId,
      contract_version: "wallet_case_backfill_schedule_v1",
      content_hash_sha256: contentHash,
      state: descriptorState,
      input_progress_public_id: descriptorProgressId,
      input_plan_public_id: descriptorPlanId,
      checkpoint_cutoff_public_id: descriptorCutoff,
      page_budget: descriptorBudget,
      selected_checkpoint_public_id: descriptorSelected,
      active_sync_public_id: descriptorActive,
    },
    document: {
      contract_version: "wallet_case_backfill_schedule_v1",
      case_public_id: caseId,
      input_progress_public_id: progressId,
      input_plan_public_id: planId,
      checkpoint_cutoff_public_id: cutoff,
      page_budget: pageBudget,
      selection_policy: "least_continuation_pages_then_revisions_then_provider_stream_v1",
      state,
      stream_count: streamCount,
      ready_count: readyCount,
      complete_count: completeCount,
      blocked_count: blockedCount,
      active_sync_public_id: activeSyncId,
      selection,
      limitations: limitations(document.limitations, "backfill schedule limitations"),
    },
  };
}

export function serializeWalletCaseBackfillSchedule(value: unknown): string {
  return `${JSON.stringify(parseWalletCaseBackfillSchedule(value), null, 2)}\n`;
}

export function parseWalletCaseCheckpointContinuationPlan(
  value: unknown,
): WalletCaseCheckpointContinuationPlanResponse {
  const envelope = record(value, ["plan", "document"], "checkpoint continuation plan response");
  const plan = record(envelope.plan, [
    "public_id", "contract_version", "content_hash_sha256",
    "checkpoint_cutoff_public_id", "stream_count", "ready_count",
    "complete_count", "blocked_count", "revision_count", "page_count",
    "pages_succeeded",
  ], "checkpoint continuation plan descriptor");
  if (plan.contract_version !== "wallet_case_checkpoint_continuation_plan_v1") {
    fail("checkpoint continuation plan descriptor contract is unsupported");
  }
  const contentHash = digest(
    plan.content_hash_sha256,
    "checkpoint continuation plan hash",
  );
  const planId = text(plan.public_id, "checkpoint continuation plan id", 68);
  if (CHECKPOINT_CONTINUATION_PLAN_ID.exec(planId)?.[1] !== contentHash) {
    fail("checkpoint continuation plan identity is invalid");
  }
  const descriptorCutoff = plan.checkpoint_cutoff_public_id === null
    ? null : checkpointId(
      plan.checkpoint_cutoff_public_id,
      "checkpoint continuation plan descriptor cutoff",
    );
  const descriptorAggregate = parseContinuationPlanAggregate(
    plan,
    "checkpoint continuation plan descriptor",
  );
  const document = record(envelope.document, [
    "contract_version", "case_public_id", "checkpoint_cutoff_public_id",
    "aggregate", "streams", "limitations",
  ], "checkpoint continuation plan document");
  if (document.contract_version !== "wallet_case_checkpoint_continuation_plan_v1") {
    fail("checkpoint continuation plan document contract is unsupported");
  }
  const caseId = publicId(
    document.case_public_id,
    "checkpoint continuation plan case id",
  );
  const cutoff = document.checkpoint_cutoff_public_id === null
    ? null : checkpointId(
      document.checkpoint_cutoff_public_id,
      "checkpoint continuation plan cutoff",
    );
  const aggregate = parseContinuationPlanAggregate(
    record(document.aggregate, [
      "stream_count", "ready_count", "complete_count", "blocked_count",
      "revision_count", "page_count", "pages_succeeded",
    ], "checkpoint continuation plan aggregate"),
    "checkpoint continuation plan aggregate",
  );
  if (!Array.isArray(document.streams) || document.streams.length > 32) {
    fail("checkpoint continuation plan streams are invalid");
  }
  const streams = document.streams.map((value, index) => {
    const item = record(value, [
      "provider", "stream_key", "provider_contract_version", "tip_checkpoint",
      "chain_public_id", "chain_content_hash_sha256", "revision_count",
      "page_count", "pages_succeeded", "resume_state", "next_page_index",
      "resume_blocker",
    ], `checkpoint continuation plan stream ${index}`);
    const provider = text(
      item.provider,
      `checkpoint continuation plan stream ${index} provider`,
      64,
    );
    const streamKey = text(
      item.stream_key,
      `checkpoint continuation plan stream ${index} key`,
      40,
    );
    const providerContract = text(
      item.provider_contract_version,
      `checkpoint continuation plan stream ${index} provider contract`,
      48,
    );
    const tip = parseDescriptor(item.tip_checkpoint);
    const chainHash = digest(
      item.chain_content_hash_sha256,
      `checkpoint continuation plan stream ${index} chain hash`,
    );
    const chainId = text(
      item.chain_public_id,
      `checkpoint continuation plan stream ${index} chain id`,
      68,
    );
    const revisionCount = integer(
      item.revision_count,
      `checkpoint continuation plan stream ${index} revision count`,
    );
    const pageCount = integer(
      item.page_count,
      `checkpoint continuation plan stream ${index} page count`,
    );
    const pagesSucceeded = integer(
      item.pages_succeeded,
      `checkpoint continuation plan stream ${index} pages succeeded`,
    );
    const state = resumeState(
      item.resume_state,
      `checkpoint continuation plan stream ${index} state`,
    );
    const nextPage = item.next_page_index === null
      ? null : integer(
        item.next_page_index,
        `checkpoint continuation plan stream ${index} next page`,
      );
    const blocker = nullableText(
      item.resume_blocker,
      `checkpoint continuation plan stream ${index} blocker`,
      64,
    );
    if (
      tip.provider !== provider || tip.stream_key !== streamKey ||
      tip.provider_contract_version !== providerContract ||
      tip.resume_state !== state || CHECKPOINT_CHAIN_ID.exec(chainId)?.[1] !== chainHash ||
      revisionCount < 1 || revisionCount > 100 || pagesSucceeded > pageCount ||
      (state === "ready") !== (nextPage !== null) ||
      (nextPage !== null && nextPage < 1) ||
      (state === "blocked") !== (blocker !== null)
    ) fail(`checkpoint continuation plan stream ${index} is inconsistent`);
    return {
      provider,
      stream_key: streamKey,
      provider_contract_version: providerContract,
      tip_checkpoint: tip,
      chain_public_id: chainId,
      chain_content_hash_sha256: chainHash,
      revision_count: revisionCount,
      page_count: pageCount,
      pages_succeeded: pagesSucceeded,
      resume_state: state,
      next_page_index: nextPage,
      resume_blocker: blocker,
    };
  });
  const keys = streams.map(({ provider, stream_key }) => `${provider}\0${stream_key}`);
  const states = streams.map(({ resume_state }) => resume_state);
  const expectedAggregate: WalletCaseCheckpointContinuationPlanAggregate = {
    stream_count: streams.length,
    ready_count: states.filter((state) => state === "ready").length,
    complete_count: states.filter((state) => state === "complete").length,
    blocked_count: states.filter((state) => state === "blocked").length,
    revision_count: streams.reduce((total, item) => total + item.revision_count, 0),
    page_count: streams.reduce((total, item) => total + item.page_count, 0),
    pages_succeeded: streams.reduce((total, item) => total + item.pages_succeeded, 0),
  };
  const cutoffIds = new Set(streams.map(({ tip_checkpoint }) => tip_checkpoint.public_id));
  if (
    JSON.stringify(aggregate) !== JSON.stringify(expectedAggregate) ||
    JSON.stringify(descriptorAggregate) !== JSON.stringify(aggregate) ||
    descriptorCutoff !== cutoff || lenOrNullMismatch(cutoff, streams.length) ||
    (cutoff !== null && !cutoffIds.has(cutoff)) ||
    new Set(keys).size !== keys.length ||
    JSON.stringify(keys) !== JSON.stringify([...keys].sort())
  ) fail("checkpoint continuation plan is inconsistent");
  return {
    plan: {
      public_id: planId,
      contract_version: "wallet_case_checkpoint_continuation_plan_v1",
      content_hash_sha256: contentHash,
      checkpoint_cutoff_public_id: descriptorCutoff,
      ...descriptorAggregate,
    },
    document: {
      contract_version: "wallet_case_checkpoint_continuation_plan_v1",
      case_public_id: caseId,
      checkpoint_cutoff_public_id: cutoff,
      aggregate,
      streams,
      limitations: limitations(
        document.limitations,
        "checkpoint continuation plan limitations",
      ),
    },
  };
}

function parseContinuationPlanAggregate(
  value: Record<string, unknown>,
  label: string,
): WalletCaseCheckpointContinuationPlanAggregate {
  const aggregate = {
    stream_count: integer(value.stream_count, `${label} stream count`),
    ready_count: integer(value.ready_count, `${label} ready count`),
    complete_count: integer(value.complete_count, `${label} complete count`),
    blocked_count: integer(value.blocked_count, `${label} blocked count`),
    revision_count: integer(value.revision_count, `${label} revision count`),
    page_count: integer(value.page_count, `${label} page count`),
    pages_succeeded: integer(value.pages_succeeded, `${label} pages succeeded`),
  };
  if (
    aggregate.stream_count > 32 || aggregate.ready_count > 32 ||
    aggregate.complete_count > 32 || aggregate.blocked_count > 32 ||
    aggregate.revision_count > 3_200 ||
    aggregate.pages_succeeded > aggregate.page_count ||
    aggregate.stream_count !== aggregate.ready_count + aggregate.complete_count + aggregate.blocked_count
  ) fail(`${label} is inconsistent`);
  return aggregate;
}

function lenOrNullMismatch(value: string | null, length: number): boolean {
  return (value === null) !== (length === 0);
}

export function serializeWalletCaseCheckpointContinuationPlan(value: unknown): string {
  return `${JSON.stringify(parseWalletCaseCheckpointContinuationPlan(value), null, 2)}\n`;
}

export function parseWalletCaseCheckpointContinuationReceipt(
  value: unknown,
): WalletCaseCheckpointContinuationReceiptResponse {
  const envelope = record(
    value,
    ["receipt", "document"],
    "checkpoint continuation receipt response",
  );
  if (
    !envelope.receipt || typeof envelope.receipt !== "object" ||
    Array.isArray(envelope.receipt)
  ) fail("checkpoint continuation receipt descriptor is invalid");
  const receiptContract = (envelope.receipt as Record<string, unknown>)
    .contract_version;
  const isScheduled = receiptContract ===
    "wallet_case_checkpoint_continuation_receipt_v3";
  const isBudgeted = isScheduled || receiptContract ===
    "wallet_case_checkpoint_continuation_receipt_v2";
  if (
    !isBudgeted &&
    receiptContract !== "wallet_case_checkpoint_continuation_receipt_v1"
  ) fail("checkpoint continuation receipt descriptor contract is unsupported");
  const receipt = record(envelope.receipt, [
    "public_id", "contract_version", "content_hash_sha256", "sync_public_id",
    "input_plan_public_id", "input_checkpoint_public_id",
    "output_checkpoint_public_id", "after_plan_public_id", "revision_delta",
    "page_count_delta", "pages_succeeded_delta",
    ...(isBudgeted ? [
      "page_budget", "page_budget_consumed", "page_budget_remaining",
    ] : []),
    ...(isScheduled ? ["input_schedule_public_id"] : []),
  ], "checkpoint continuation receipt descriptor");
  const contentHash = digest(
    receipt.content_hash_sha256,
    "checkpoint continuation receipt hash",
  );
  const receiptId = text(
    receipt.public_id,
    "checkpoint continuation receipt id",
    68,
  );
  if (CHECKPOINT_CONTINUATION_RECEIPT_ID.exec(receiptId)?.[1] !== contentHash) {
    fail("checkpoint continuation receipt identity is invalid");
  }
  const receiptSyncId = publicId(
    receipt.sync_public_id,
    "checkpoint continuation receipt sync id",
  );
  const receiptInputPlanId = continuationPlanId(
    receipt.input_plan_public_id,
    "checkpoint continuation receipt input plan id",
  );
  const receiptInputCheckpointId = checkpointId(
    receipt.input_checkpoint_public_id,
    "checkpoint continuation receipt input checkpoint id",
  );
  const receiptOutputCheckpointId = checkpointId(
    receipt.output_checkpoint_public_id,
    "checkpoint continuation receipt output checkpoint id",
  );
  const receiptAfterPlanId = continuationPlanId(
    receipt.after_plan_public_id,
    "checkpoint continuation receipt after plan id",
  );
  const receiptRevisionDelta = integer(
    receipt.revision_delta,
    "checkpoint continuation receipt revision delta",
  );
  const receiptPageDelta = integer(
    receipt.page_count_delta,
    "checkpoint continuation receipt page delta",
  );
  const receiptSuccessDelta = integer(
    receipt.pages_succeeded_delta,
    "checkpoint continuation receipt success delta",
  );
  const receiptPageBudget = isBudgeted
    ? integer(receipt.page_budget, "checkpoint continuation receipt page budget")
    : null;
  const receiptBudgetConsumed = isBudgeted
    ? integer(
        receipt.page_budget_consumed,
        "checkpoint continuation receipt consumed page budget",
      )
    : null;
  const receiptBudgetRemaining = isBudgeted
    ? integer(
        receipt.page_budget_remaining,
        "checkpoint continuation receipt remaining page budget",
      )
    : null;
  const receiptInputScheduleId = isScheduled
    ? backfillScheduleId(
        receipt.input_schedule_public_id,
        "checkpoint continuation receipt input schedule id",
      )
    : null;

  const document = record(envelope.document, [
    "contract_version", "case_public_id", "sync_public_id", "input", "output",
    "after_plan", "transition", "limitations",
  ], "checkpoint continuation receipt document");
  if (document.contract_version !== receiptContract) {
    fail("checkpoint continuation receipt document contract is unsupported");
  }
  const caseId = publicId(
    document.case_public_id,
    "checkpoint continuation receipt case id",
  );
  const syncId = publicId(
    document.sync_public_id,
    "checkpoint continuation receipt document sync id",
  );
  const sourceItem = record(document.input, [
    "continuation_plan_public_id", "checkpoint", "chain_public_id",
    "chain_content_hash_sha256", "revision_count", "page_count",
    "pages_succeeded", "next_page_index",
    ...(isBudgeted ? ["page_budget"] : []),
    ...(isScheduled ? ["backfill_schedule_public_id"] : []),
  ], "checkpoint continuation receipt input");
  const inputPlanId = continuationPlanId(
    sourceItem.continuation_plan_public_id,
    "checkpoint continuation receipt accepted plan id",
  );
  const inputCheckpoint = parseDescriptor(sourceItem.checkpoint);
  const inputChainHash = digest(
    sourceItem.chain_content_hash_sha256,
    "checkpoint continuation receipt input chain hash",
  );
  const inputChainId = text(
    sourceItem.chain_public_id,
    "checkpoint continuation receipt input chain id",
    68,
  );
  const inputRevisionCount = integer(
    sourceItem.revision_count,
    "checkpoint continuation receipt input revision count",
  );
  const inputPageCount = integer(
    sourceItem.page_count,
    "checkpoint continuation receipt input page count",
  );
  const inputSuccessCount = integer(
    sourceItem.pages_succeeded,
    "checkpoint continuation receipt input success count",
  );
  const inputNextPage = integer(
    sourceItem.next_page_index,
    "checkpoint continuation receipt input next page",
  );
  const inputPageBudget = isBudgeted
    ? integer(
        sourceItem.page_budget,
        "checkpoint continuation receipt input page budget",
      )
    : null;
  const inputScheduleId = isScheduled
    ? backfillScheduleId(
        sourceItem.backfill_schedule_public_id,
        "checkpoint continuation receipt accepted schedule id",
      )
    : null;
  if (
    inputCheckpoint.resume_state !== "ready" ||
    CHECKPOINT_CHAIN_ID.exec(inputChainId)?.[1] !== inputChainHash ||
    inputRevisionCount < 1 || inputRevisionCount > 99 ||
    inputSuccessCount > inputPageCount || inputNextPage < 1 ||
    (inputPageBudget !== null && (inputPageBudget < 1 || inputPageBudget > 10))
  ) fail("checkpoint continuation receipt input is inconsistent");
  const input: WalletCaseCheckpointContinuationReceiptInput = {
    continuation_plan_public_id: inputPlanId,
    checkpoint: inputCheckpoint,
    chain_public_id: inputChainId,
    chain_content_hash_sha256: inputChainHash,
    revision_count: inputRevisionCount,
    page_count: inputPageCount,
    pages_succeeded: inputSuccessCount,
    next_page_index: inputNextPage,
  };

  const outputItem = record(document.output, [
    "checkpoint", "chain_public_id", "chain_content_hash_sha256",
    "revision_count", "page_count", "pages_succeeded", "resume_state",
    "next_page_index", "resume_blocker",
  ], "checkpoint continuation receipt output");
  const outputCheckpoint = parseDescriptor(outputItem.checkpoint);
  const outputChainHash = digest(
    outputItem.chain_content_hash_sha256,
    "checkpoint continuation receipt output chain hash",
  );
  const outputChainId = text(
    outputItem.chain_public_id,
    "checkpoint continuation receipt output chain id",
    68,
  );
  const outputRevisionCount = integer(
    outputItem.revision_count,
    "checkpoint continuation receipt output revision count",
  );
  const outputPageCount = integer(
    outputItem.page_count,
    "checkpoint continuation receipt output page count",
  );
  const outputSuccessCount = integer(
    outputItem.pages_succeeded,
    "checkpoint continuation receipt output success count",
  );
  const outputState = resumeState(
    outputItem.resume_state,
    "checkpoint continuation receipt output state",
  );
  const outputNextPage = outputItem.next_page_index === null
    ? null : integer(
      outputItem.next_page_index,
      "checkpoint continuation receipt output next page",
    );
  const outputBlocker = nullableText(
    outputItem.resume_blocker,
    "checkpoint continuation receipt output blocker",
    64,
  );
  if (
    outputCheckpoint.resume_state !== outputState ||
    CHECKPOINT_CHAIN_ID.exec(outputChainId)?.[1] !== outputChainHash ||
    outputRevisionCount < 2 || outputRevisionCount > 100 ||
    outputSuccessCount > outputPageCount ||
    (outputState === "ready") !== (outputNextPage !== null) ||
    (outputNextPage !== null && outputNextPage < 1) ||
    (outputState === "blocked") !== (outputBlocker !== null)
  ) fail("checkpoint continuation receipt output is inconsistent");
  const output: WalletCaseCheckpointContinuationReceiptOutput = {
    checkpoint: outputCheckpoint,
    chain_public_id: outputChainId,
    chain_content_hash_sha256: outputChainHash,
    revision_count: outputRevisionCount,
    page_count: outputPageCount,
    pages_succeeded: outputSuccessCount,
    resume_state: outputState,
    next_page_index: outputNextPage,
    resume_blocker: outputBlocker,
  };

  const afterPlan = parseWalletCaseCheckpointContinuationPlan(document.after_plan);
  const transitionItem = record(document.transition, [
    "checkpoint_changed", "plan_changed", "revision_delta",
    "page_count_delta", "pages_succeeded_delta",
    ...(isBudgeted ? [
      "page_budget_consumed", "page_budget_remaining",
    ] : []),
  ], "checkpoint continuation receipt transition");
  const revisionDelta = integer(
    transitionItem.revision_delta,
    "checkpoint continuation receipt transition revision delta",
  );
  const pageDelta = integer(
    transitionItem.page_count_delta,
    "checkpoint continuation receipt transition page delta",
  );
  const successDelta = integer(
    transitionItem.pages_succeeded_delta,
    "checkpoint continuation receipt transition success delta",
  );
  const budgetConsumed = isBudgeted
    ? integer(
        transitionItem.page_budget_consumed,
        "checkpoint continuation receipt consumed budget",
      )
    : null;
  const budgetRemaining = isBudgeted
    ? integer(
        transitionItem.page_budget_remaining,
        "checkpoint continuation receipt remaining budget",
      )
    : null;
  const matchingStreams = afterPlan.document.streams.filter((stream) => (
    stream.provider === output.checkpoint.provider &&
    stream.stream_key === output.checkpoint.stream_key
  ));
  const afterStream = matchingStreams[0];
  if (
    transitionItem.checkpoint_changed !== true ||
    transitionItem.plan_changed !== true || revisionDelta !== 1 ||
    afterPlan.document.case_public_id !== caseId ||
    input.checkpoint.provider !== output.checkpoint.provider ||
    input.checkpoint.stream_key !== output.checkpoint.stream_key ||
    input.checkpoint.provider_contract_version !==
      output.checkpoint.provider_contract_version ||
    output.checkpoint.source_sync_public_id !== syncId ||
    input.checkpoint.public_id === output.checkpoint.public_id ||
    input.continuation_plan_public_id === afterPlan.plan.public_id ||
    output.revision_count !== input.revision_count + 1 ||
    pageDelta !== output.page_count - input.page_count ||
    successDelta !== output.pages_succeeded - input.pages_succeeded ||
    matchingStreams.length !== 1 || !afterStream ||
    afterStream.tip_checkpoint.public_id !== output.checkpoint.public_id ||
    afterStream.chain_public_id !== output.chain_public_id ||
    afterStream.chain_content_hash_sha256 !== output.chain_content_hash_sha256 ||
    afterStream.revision_count !== output.revision_count ||
    afterStream.page_count !== output.page_count ||
    afterStream.pages_succeeded !== output.pages_succeeded ||
    afterStream.resume_state !== output.resume_state ||
    afterStream.next_page_index !== output.next_page_index ||
    afterStream.resume_blocker !== output.resume_blocker ||
    receiptSyncId !== syncId || receiptInputPlanId !== inputPlanId ||
    receiptInputCheckpointId !== inputCheckpoint.public_id ||
    receiptOutputCheckpointId !== outputCheckpoint.public_id ||
    receiptAfterPlanId !== afterPlan.plan.public_id ||
    receiptRevisionDelta !== revisionDelta || receiptRevisionDelta !== 1 ||
    receiptPageDelta !== pageDelta || receiptSuccessDelta !== successDelta ||
    (isBudgeted && (
      inputPageBudget === null || inputPageBudget < 1 || inputPageBudget > 10 ||
      budgetConsumed === null || budgetRemaining === null ||
      budgetConsumed !== pageDelta || successDelta > budgetConsumed ||
      budgetConsumed + budgetRemaining !== inputPageBudget ||
      receiptPageBudget !== inputPageBudget ||
      receiptBudgetConsumed !== budgetConsumed ||
      receiptBudgetRemaining !== budgetRemaining
    )) ||
    (isScheduled && receiptInputScheduleId !== inputScheduleId)
  ) fail("checkpoint continuation receipt transition is inconsistent");

  const parsedLimitations = limitations(
    document.limitations,
    "checkpoint continuation receipt limitations",
  );
  if (isBudgeted) {
    if (
      inputPageBudget === null || budgetConsumed === null ||
      budgetRemaining === null || receiptPageBudget === null ||
      receiptBudgetConsumed === null || receiptBudgetRemaining === null
    ) fail("checkpoint continuation receipt budget is inconsistent");
    const budgetedResponse = {
      receipt: {
        public_id: receiptId,
        contract_version: receiptContract,
        content_hash_sha256: contentHash,
        sync_public_id: receiptSyncId,
        input_plan_public_id: receiptInputPlanId,
        input_checkpoint_public_id: receiptInputCheckpointId,
        output_checkpoint_public_id: receiptOutputCheckpointId,
        after_plan_public_id: receiptAfterPlanId,
        revision_delta: 1,
        page_count_delta: receiptPageDelta,
        pages_succeeded_delta: receiptSuccessDelta,
        page_budget: receiptPageBudget,
        page_budget_consumed: receiptBudgetConsumed,
        page_budget_remaining: receiptBudgetRemaining,
        ...(isScheduled && inputScheduleId !== null
          ? { input_schedule_public_id: inputScheduleId }
          : {}),
      },
      document: {
        contract_version: receiptContract,
        case_public_id: caseId,
        sync_public_id: syncId,
        input: {
          ...input,
          page_budget: inputPageBudget,
          ...(isScheduled && inputScheduleId !== null
            ? { backfill_schedule_public_id: inputScheduleId }
            : {}),
        },
        output,
        after_plan: afterPlan,
        transition: {
          checkpoint_changed: true,
          plan_changed: true,
          revision_delta: 1,
          page_count_delta: pageDelta,
          pages_succeeded_delta: successDelta,
          page_budget_consumed: budgetConsumed,
          page_budget_remaining: budgetRemaining,
        },
        limitations: parsedLimitations,
      },
    };
    return budgetedResponse as WalletCaseCheckpointContinuationReceiptResponse;
  }

  return {
    receipt: {
      public_id: receiptId,
      contract_version: "wallet_case_checkpoint_continuation_receipt_v1",
      content_hash_sha256: contentHash,
      sync_public_id: receiptSyncId,
      input_plan_public_id: receiptInputPlanId,
      input_checkpoint_public_id: receiptInputCheckpointId,
      output_checkpoint_public_id: receiptOutputCheckpointId,
      after_plan_public_id: receiptAfterPlanId,
      revision_delta: 1,
      page_count_delta: receiptPageDelta,
      pages_succeeded_delta: receiptSuccessDelta,
    },
    document: {
      contract_version: "wallet_case_checkpoint_continuation_receipt_v1",
      case_public_id: caseId,
      sync_public_id: syncId,
      input,
      output,
      after_plan: afterPlan,
      transition: {
        checkpoint_changed: true,
        plan_changed: true,
        revision_delta: 1,
        page_count_delta: pageDelta,
        pages_succeeded_delta: successDelta,
      },
      limitations: parsedLimitations,
    },
  };
}

function continuationPlanId(value: unknown, label: string): string {
  const result = text(value, label, 68);
  if (!CHECKPOINT_CONTINUATION_PLAN_ID.test(result)) fail(`${label} is invalid`);
  return result;
}

function backfillProgressId(value: unknown, label: string): string {
  const result = text(value, label, 68);
  if (!BACKFILL_PROGRESS_ID.test(result)) fail(`${label} is invalid`);
  return result;
}

function backfillScheduleId(value: unknown, label: string): string {
  const result = text(value, label, 68);
  if (!BACKFILL_SCHEDULE_ID.test(result)) fail(`${label} is invalid`);
  return result;
}

function continuationReceiptId(value: unknown, label: string): string {
  const result = text(value, label, 68);
  if (!CHECKPOINT_CONTINUATION_RECEIPT_ID.test(result)) fail(`${label} is invalid`);
  return result;
}

function backfillOutcomeState(
  value: unknown,
  label: string,
): WalletCaseBackfillOutcomeState {
  const result = text(value, label, 16) as WalletCaseBackfillOutcomeState;
  if (!new Set(["advanced", "completed", "blocked", "no_progress"]).has(result)) {
    fail(`${label} is invalid`);
  }
  return result;
}

function backfillScheduleState(
  value: unknown,
  label: string,
): WalletCaseBackfillScheduleState {
  const result = text(value, label, 16) as WalletCaseBackfillScheduleState;
  if (!new Set(["ready", "backpressured", "empty", "complete", "blocked"]).has(result)) {
    fail(`${label} is invalid`);
  }
  return result;
}

function backfillPageBudget(value: unknown, label: string): number {
  const result = integer(value, label);
  if (result < 1 || result > 10) fail(`${label} is invalid`);
  return result;
}

export function serializeWalletCaseCheckpointContinuationReceipt(
  value: unknown,
): string {
  return `${JSON.stringify(parseWalletCaseCheckpointContinuationReceipt(value), null, 2)}\n`;
}

export function parseWalletCaseBackfillOutcome(
  value: unknown,
): WalletCaseBackfillOutcomeResponse {
  const envelope = record(value, ["outcome", "document"], "backfill outcome response");
  const descriptor = record(envelope.outcome, [
    "public_id", "contract_version", "content_hash_sha256", "sync_public_id",
    "outcome", "input_schedule_public_id", "continuation_receipt_public_id",
    "input_progress_public_id", "output_progress_public_id", "provider",
    "stream_key", "page_count_delta", "pages_succeeded_delta",
    "before_resume_state", "after_resume_state",
  ], "backfill outcome descriptor");
  if (descriptor.contract_version !== "wallet_case_backfill_outcome_v1") {
    fail("backfill outcome descriptor contract is unsupported");
  }
  const contentHash = digest(descriptor.content_hash_sha256, "backfill outcome hash");
  const outcomeId = text(descriptor.public_id, "backfill outcome id", 68);
  if (BACKFILL_OUTCOME_ID.exec(outcomeId)?.[1] !== contentHash) {
    fail("backfill outcome identity is invalid");
  }
  const descriptorSyncId = publicId(descriptor.sync_public_id, "backfill outcome sync id");
  const descriptorState = backfillOutcomeState(
    descriptor.outcome,
    "backfill outcome descriptor state",
  );
  const descriptorScheduleId = backfillScheduleId(
    descriptor.input_schedule_public_id,
    "backfill outcome schedule id",
  );
  const descriptorReceiptId = continuationReceiptId(
    descriptor.continuation_receipt_public_id,
    "backfill outcome receipt id",
  );
  const descriptorInputProgressId = backfillProgressId(
    descriptor.input_progress_public_id,
    "backfill outcome input progress id",
  );
  const descriptorOutputProgressId = backfillProgressId(
    descriptor.output_progress_public_id,
    "backfill outcome output progress id",
  );
  const descriptorProvider = text(descriptor.provider, "backfill outcome provider", 64);
  const descriptorStreamKey = text(descriptor.stream_key, "backfill outcome stream", 40);
  const descriptorPageDelta = integer(
    descriptor.page_count_delta,
    "backfill outcome page delta",
  );
  const descriptorSuccessDelta = integer(
    descriptor.pages_succeeded_delta,
    "backfill outcome success delta",
  );
  const descriptorBeforeState = resumeState(
    descriptor.before_resume_state,
    "backfill outcome before state",
  );
  const descriptorAfterState = resumeState(
    descriptor.after_resume_state,
    "backfill outcome after state",
  );

  const document = record(envelope.document, [
    "contract_version", "case_public_id", "sync_public_id", "input_schedule",
    "input_progress", "continuation_receipt", "output_progress", "outcome",
    "transition", "limitations",
  ], "backfill outcome document");
  if (document.contract_version !== "wallet_case_backfill_outcome_v1") {
    fail("backfill outcome document contract is unsupported");
  }
  const caseId = publicId(document.case_public_id, "backfill outcome case id");
  const syncId = publicId(document.sync_public_id, "backfill outcome document sync id");
  const schedule = parseWalletCaseBackfillSchedule(document.input_schedule);
  const before = parseWalletCaseBackfillProgress(document.input_progress);
  const parsedReceipt = parseWalletCaseCheckpointContinuationReceipt(
    document.continuation_receipt,
  );
  if (parsedReceipt.receipt.contract_version !== (
    "wallet_case_checkpoint_continuation_receipt_v3"
  )) fail("backfill outcome receipt contract is unsupported");
  const receipt = parsedReceipt as WalletCaseCheckpointContinuationReceiptV3Response;
  const after = parseWalletCaseBackfillProgress(document.output_progress);
  const state = backfillOutcomeState(document.outcome, "backfill outcome state");
  const item = record(document.transition, [
    "provider", "stream_key", "input_checkpoint_public_id",
    "output_checkpoint_public_id", "before_resume_state", "after_resume_state",
    "revision_delta", "page_count_delta", "pages_succeeded_delta",
    "continuation_revision_delta", "continuation_page_count_delta",
    "continuation_pages_succeeded_delta", "ready_count_delta",
    "complete_count_delta", "blocked_count_delta", "frontier_changed",
  ], "backfill outcome transition");
  const provider = text(item.provider, "backfill outcome transition provider", 64);
  const streamKey = text(item.stream_key, "backfill outcome transition stream", 40);
  const inputCheckpointId = checkpointId(
    item.input_checkpoint_public_id,
    "backfill outcome input checkpoint id",
  );
  const outputCheckpointId = checkpointId(
    item.output_checkpoint_public_id,
    "backfill outcome output checkpoint id",
  );
  const beforeState = resumeState(item.before_resume_state, "backfill outcome transition before state");
  const afterState = resumeState(item.after_resume_state, "backfill outcome transition after state");
  const revisionDelta = integer(item.revision_delta, "backfill outcome revision delta");
  const pageDelta = integer(item.page_count_delta, "backfill outcome transition page delta");
  const successDelta = integer(
    item.pages_succeeded_delta,
    "backfill outcome transition success delta",
  );
  const continuationRevisionDelta = integer(
    item.continuation_revision_delta,
    "backfill outcome continuation revision delta",
  );
  const continuationPageDelta = integer(
    item.continuation_page_count_delta,
    "backfill outcome continuation page delta",
  );
  const continuationSuccessDelta = integer(
    item.continuation_pages_succeeded_delta,
    "backfill outcome continuation success delta",
  );
  const readyDelta = signedInteger(item.ready_count_delta, "backfill outcome ready delta");
  const completeDelta = signedInteger(
    item.complete_count_delta,
    "backfill outcome complete delta",
  );
  const blockedDelta = signedInteger(
    item.blocked_count_delta,
    "backfill outcome blocked delta",
  );
  if (typeof item.frontier_changed !== "boolean") {
    fail("backfill outcome frontier change is invalid");
  }
  const frontierChanged = item.frontier_changed;
  const selection = schedule.document.selection;
  const beforeStream = before.document.streams.find((stream) => (
    selection !== null && stream.provider === selection.provider &&
    stream.stream_key === selection.stream_key
  ));
  const afterStream = after.document.streams.find((stream) => (
    selection !== null && stream.provider === selection.provider &&
    stream.stream_key === selection.stream_key
  ));
  const expectedState: WalletCaseBackfillOutcomeState = afterState === "complete"
    ? "completed"
    : afterState === "blocked"
      ? "blocked"
      : successDelta > 0
        ? "advanced"
        : "no_progress";
  if (
    schedule.schedule.state !== "ready" || selection === null ||
    !beforeStream || !afterStream || beforeState !== "ready" ||
    beforeStream.resume_state !== beforeState || afterStream.resume_state !== afterState ||
    provider !== selection.provider || streamKey !== selection.stream_key ||
    inputCheckpointId !== selection.checkpoint_public_id ||
    outputCheckpointId !== afterStream.tip_checkpoint.public_id ||
    revisionDelta !== 1 || continuationRevisionDelta !== 1 ||
    pageDelta > 10 || successDelta > pageDelta ||
    continuationPageDelta !== pageDelta || continuationSuccessDelta !== successDelta ||
    readyDelta !== after.progress.ready_count - before.progress.ready_count ||
    completeDelta !== after.progress.complete_count - before.progress.complete_count ||
    blockedDelta !== after.progress.blocked_count - before.progress.blocked_count ||
    revisionDelta !== after.progress.revision_count - before.progress.revision_count ||
    pageDelta !== after.progress.page_count - before.progress.page_count ||
    successDelta !== after.progress.pages_succeeded - before.progress.pages_succeeded ||
    continuationRevisionDelta !== (
      after.progress.continuation_revision_count - before.progress.continuation_revision_count
    ) ||
    continuationPageDelta !== (
      after.progress.continuation_page_count - before.progress.continuation_page_count
    ) ||
    continuationSuccessDelta !== (
      after.progress.continuation_pages_succeeded -
      before.progress.continuation_pages_succeeded
    ) ||
    frontierChanged !== (
      JSON.stringify(beforeStream.current_frontier) !==
      JSON.stringify(afterStream.current_frontier)
    ) ||
    state !== expectedState || syncId !== descriptorSyncId ||
    caseId !== schedule.document.case_public_id ||
    caseId !== before.document.case_public_id || caseId !== after.document.case_public_id ||
    caseId !== receipt.document.case_public_id || syncId !== receipt.document.sync_public_id ||
    schedule.schedule.input_progress_public_id !== before.progress.public_id ||
    schedule.schedule.checkpoint_cutoff_public_id !== before.progress.checkpoint_cutoff_public_id ||
    schedule.schedule.public_id !== receipt.receipt.input_schedule_public_id ||
    receipt.receipt.output_checkpoint_public_id !== after.progress.checkpoint_cutoff_public_id ||
    receipt.receipt.page_count_delta !== pageDelta ||
    receipt.receipt.pages_succeeded_delta !== successDelta ||
    descriptorScheduleId !== schedule.schedule.public_id ||
    descriptorReceiptId !== receipt.receipt.public_id ||
    descriptorInputProgressId !== before.progress.public_id ||
    descriptorOutputProgressId !== after.progress.public_id ||
    descriptorInputProgressId === descriptorOutputProgressId ||
    descriptorProvider !== provider || descriptorStreamKey !== streamKey ||
    descriptorPageDelta !== pageDelta || descriptorSuccessDelta !== successDelta ||
    descriptorBeforeState !== beforeState || descriptorAfterState !== afterState ||
    descriptorState !== state
  ) fail("backfill outcome is inconsistent");
  if (
    readyDelta < -32 || readyDelta > 32 || completeDelta < -32 ||
    completeDelta > 32 || blockedDelta < -32 || blockedDelta > 32
  ) fail("backfill outcome state deltas are invalid");
  const transition: WalletCaseBackfillOutcomeTransition = {
    provider,
    stream_key: streamKey,
    input_checkpoint_public_id: inputCheckpointId,
    output_checkpoint_public_id: outputCheckpointId,
    before_resume_state: "ready",
    after_resume_state: afterState,
    revision_delta: 1,
    page_count_delta: pageDelta,
    pages_succeeded_delta: successDelta,
    continuation_revision_delta: 1,
    continuation_page_count_delta: continuationPageDelta,
    continuation_pages_succeeded_delta: continuationSuccessDelta,
    ready_count_delta: readyDelta,
    complete_count_delta: completeDelta,
    blocked_count_delta: blockedDelta,
    frontier_changed: frontierChanged,
  };
  return {
    outcome: {
      public_id: outcomeId,
      contract_version: "wallet_case_backfill_outcome_v1",
      content_hash_sha256: contentHash,
      sync_public_id: descriptorSyncId,
      outcome: descriptorState,
      input_schedule_public_id: descriptorScheduleId,
      continuation_receipt_public_id: descriptorReceiptId,
      input_progress_public_id: descriptorInputProgressId,
      output_progress_public_id: descriptorOutputProgressId,
      provider: descriptorProvider,
      stream_key: descriptorStreamKey,
      page_count_delta: descriptorPageDelta,
      pages_succeeded_delta: descriptorSuccessDelta,
      before_resume_state: "ready",
      after_resume_state: descriptorAfterState,
    },
    document: {
      contract_version: "wallet_case_backfill_outcome_v1",
      case_public_id: caseId,
      sync_public_id: syncId,
      input_schedule: schedule,
      input_progress: before,
      continuation_receipt: receipt,
      output_progress: after,
      outcome: state,
      transition,
      limitations: limitations(document.limitations, "backfill outcome limitations"),
    },
  };
}

export function serializeWalletCaseBackfillOutcome(value: unknown): string {
  return `${JSON.stringify(parseWalletCaseBackfillOutcome(value), null, 2)}\n`;
}

export function parseWalletCaseStreamCheckpointCatalog(
  value: unknown,
): WalletCaseStreamCheckpointCatalogResponse {
  const item = record(value, [
    "case_public_id", "checkpoint_count", "ready_count", "complete_count",
    "blocked_count", "checkpoints",
  ], "stream checkpoint catalog");
  if (!Array.isArray(item.checkpoints)) fail("stream checkpoint catalog is invalid");
  const checkpoints = item.checkpoints.map(parseCheckpoint);
  const caseId = publicId(item.case_public_id, "stream checkpoint catalog case id");
  const checkpointCount = integer(
    item.checkpoint_count,
    "stream checkpoint catalog count",
  );
  const readyCount = integer(item.ready_count, "stream checkpoint ready count");
  const completeCount = integer(
    item.complete_count,
    "stream checkpoint complete count",
  );
  const blockedCount = integer(
    item.blocked_count,
    "stream checkpoint blocked count",
  );
  const keys = checkpoints.map(
    ({ document }) => `${document.provider}\0${document.stream_key}`,
  );
  if (
    checkpointCount !== checkpoints.length ||
    checkpointCount !== readyCount + completeCount + blockedCount ||
    readyCount !== checkpoints.filter(
      ({ document }) => document.resume_state === "ready",
    ).length ||
    completeCount !== checkpoints.filter(
      ({ document }) => document.resume_state === "complete",
    ).length ||
    blockedCount !== checkpoints.filter(
      ({ document }) => document.resume_state === "blocked",
    ).length ||
    checkpoints.some(({ document }) => document.case_public_id !== caseId) ||
    new Set(keys).size !== keys.length ||
    JSON.stringify(keys) !== JSON.stringify([...keys].sort())
  ) fail("stream checkpoint catalog is inconsistent");
  return {
    case_public_id: caseId,
    checkpoint_count: checkpointCount,
    ready_count: readyCount,
    complete_count: completeCount,
    blocked_count: blockedCount,
    checkpoints,
  };
}
