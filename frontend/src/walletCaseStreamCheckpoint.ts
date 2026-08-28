import type { WalletCaseSyncMode } from "./walletCase";
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

const PUBLIC_ID =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const CHECKPOINT_ID = /^scp_([0-9a-f]{64})$/;
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

function parseCheckpoint(value: unknown): WalletCaseStreamCheckpointResponse {
  const envelope = record(value, ["checkpoint", "document"], "stream checkpoint");
  const descriptor = record(envelope.checkpoint, [
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
  const parsedDescriptor: WalletCaseStreamCheckpointDescriptor = {
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
