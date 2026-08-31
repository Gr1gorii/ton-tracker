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

const PUBLIC_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const CHECKPOINT_ID = /^scp_([0-9a-f]{64})$/;
const CHECKPOINT_CHAIN_ID = /^cch_([0-9a-f]{64})$/;
const CHECKPOINT_CONTINUATION_PLAN_ID = /^cpl_([0-9a-f]{64})$/;
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
