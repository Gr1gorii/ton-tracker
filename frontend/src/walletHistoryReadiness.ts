import type {
  WalletHistoryIntervalCoverageLayerRecord,
  WalletHistoryReadinessResponse,
} from "./types";

const TOP_LEVEL_KEYS = [
  "analysis_version",
  "blockers",
  "bounded_interval_coverage",
  "coverage",
  "data_mode",
  "deduplication_applied",
  "eligible_for_cost_basis",
  "event_action_identity_groups",
  "event_action_identity_groups_total",
  "evidence_groups_truncated",
  "history_complete",
  "is_cost_basis",
  "note",
  "observed_activity_end",
  "observed_activity_start",
  "requested_bounds_verified",
  "run_ids",
  "runs",
  "swap_identity_groups",
  "swap_identity_groups_total",
  "target_run_id",
  "transaction_identity_groups",
  "transaction_identity_groups_total",
  "used_by_pnl",
  "wallet_address",
  "wallet_identity",
] as const;

const DIGITS = /^(?:0|[1-9][0-9]*)$/;
const POSITIVE_DIGITS = /^[1-9][0-9]*$/;
const COVERAGE_STATES = new Set(["not_observed", "complete", "incomplete"]);

export function validateWalletHistoryReadiness(
  value: unknown,
  targetRunId: number,
  selectedRunIds: number[],
): WalletHistoryReadinessResponse {
  const expectedIds = uniqueRunIds(selectedRunIds);
  if (
    !positiveInteger(targetRunId) ||
    expectedIds.length < 2 ||
    expectedIds.length > 50 ||
    !expectedIds.includes(targetRunId) ||
    !isRecord(value) ||
    !hasExactKeys(value, TOP_LEVEL_KEYS) ||
    value.analysis_version !== "wallet_history_readiness_v0.22.7" ||
    value.target_run_id !== targetRunId ||
    !sameIdSet(value.run_ids, expectedIds) ||
    (value.data_mode !== "mock" && value.data_mode !== "real") ||
    !validText(value.wallet_address, 256) ||
    !validIdentity(value.wallet_identity) ||
    value.requested_bounds_verified !== false ||
    value.history_complete !== false ||
    value.deduplication_applied !== false ||
    value.is_cost_basis !== false ||
    value.eligible_for_cost_basis !== false ||
    value.used_by_pnl !== false ||
    !nullableTimestamp(value.observed_activity_start) ||
    !nullableTimestamp(value.observed_activity_end) ||
    !validText(value.note, 4_000)
  ) {
    fail();
  }

  validateRuns(value.runs, expectedIds, targetRunId, value.wallet_address);
  validateIdentityGroups(value, expectedIds);
  validateCoverage(value.coverage);
  validateBoundedCoverage(value.bounded_interval_coverage, expectedIds);
  validateBlockers(value.blockers, expectedIds);

  return value as unknown as WalletHistoryReadinessResponse;
}

function validateRuns(
  value: unknown,
  expectedIds: number[],
  targetRunId: number,
  walletAddress: unknown,
) {
  if (!Array.isArray(value) || value.length !== expectedIds.length) fail();
  const ids: number[] = [];
  let targets = 0;
  for (const row of value) {
    if (
      !isRecord(row) ||
      !positiveInteger(row.run_id) ||
      typeof row.is_target !== "boolean" ||
      row.is_target !== (row.run_id === targetRunId) ||
      row.wallet_address !== walletAddress ||
      !validIdentity(row.wallet_identity) ||
      row.requested_bounds_verified !== false ||
      !nonnegativeInteger(row.transfer_count) ||
      !nonnegativeInteger(row.transaction_count) ||
      !nonnegativeInteger(row.swap_count) ||
      !nonnegativeInteger(row.timestamped_activity_count) ||
      !nonnegativeInteger(row.untimestamped_activity_count) ||
      !nonnegativeInteger(row.outside_requested_bounds_count)
    ) fail();
    ids.push(row.run_id);
    if (row.is_target) targets += 1;
  }
  if (targets !== 1 || !sameIdSet(ids, expectedIds)) fail();
}

function validateIdentityGroups(value: Record<string, unknown>, selectedIds: number[]) {
  const groups = [
    [value.transaction_identity_groups, value.transaction_identity_groups_total],
    [value.swap_identity_groups, value.swap_identity_groups_total],
    [value.event_action_identity_groups, value.event_action_identity_groups_total],
  ] as const;
  if (typeof value.evidence_groups_truncated !== "boolean") fail();
  for (const [rows, total] of groups) {
    if (!Array.isArray(rows) || !nonnegativeInteger(total) || total < rows.length) fail();
    if (!value.evidence_groups_truncated && total !== rows.length) fail();
    for (const row of rows) {
      if (
        !isRecord(row) ||
        !validText(row.identity, 1_000) ||
        !Array.isArray(row.run_ids) ||
        new Set(row.run_ids).size !== row.run_ids.length ||
        !row.run_ids.every((id) => positiveInteger(id) && selectedIds.includes(id)) ||
        !nonnegativeInteger(row.observation_count) ||
        row.observation_count < 2 ||
        !nonnegativeInteger(row.distinct_payload_count) ||
        row.distinct_payload_count < 1 ||
        typeof row.has_conflict !== "boolean"
      ) fail();
    }
  }
}

function validateCoverage(value: unknown) {
  if (!isRecord(value)) fail();
  const integerKeys = [
    "activity_observations",
    "timestamped_activity_observations",
    "transaction_observations",
    "transaction_observations_with_hash",
    "transaction_observations_with_exact_identity",
    "transaction_observations_with_weak_identity",
    "transaction_observations_with_unavailable_identity",
    "transaction_observations_with_invalid_identity_contract",
    "overlapping_transaction_identity_groups",
    "conflicting_transaction_identity_groups",
    "event_action_observations",
    "event_action_observations_with_provider_scoped_identity",
    "event_action_observations_with_unavailable_identity",
    "event_action_observations_with_invalid_identity_contract",
    "overlapping_provider_scoped_event_action_identity_groups",
    "conflicting_provider_scoped_event_action_identity_groups",
    "swap_observations",
    "swap_observations_with_exact_identity",
    "swap_observations_with_provider_scoped_identity",
    "swap_observations_with_weak_identity",
    "overlapping_exact_swap_identity_groups",
    "overlapping_provider_scoped_swap_identity_groups",
    "overlapping_weak_swap_identity_groups",
    "conflicting_swap_identity_groups",
    "non_ton_swap_legs",
    "addressed_non_ton_swap_legs",
    "fee_link_candidate_swaps",
    "same_run_fee_hash_match_candidates",
  ];
  if (
    integerKeys.some((key) => !nonnegativeInteger(value[key])) ||
    !COVERAGE_STATES.has(String(value.transaction_identity_coverage_state)) ||
    !COVERAGE_STATES.has(String(value.event_action_identity_coverage_state)) ||
    !COVERAGE_STATES.has(String(value.asset_address_coverage_state)) ||
    !COVERAGE_STATES.has(String(value.fee_hash_match_coverage_state)) ||
    value.fee_linkage_contract_verified !== false ||
    Number(value.timestamped_activity_observations) > Number(value.activity_observations) ||
    Number(value.transaction_observations_with_exact_identity) + Number(value.transaction_observations_with_weak_identity) + Number(value.transaction_observations_with_unavailable_identity) + Number(value.transaction_observations_with_invalid_identity_contract) !== Number(value.transaction_observations) ||
    Number(value.transaction_observations_with_exact_identity) > Number(value.transaction_observations) ||
    Number(value.event_action_observations_with_provider_scoped_identity) + Number(value.event_action_observations_with_unavailable_identity) + Number(value.event_action_observations_with_invalid_identity_contract) !== Number(value.event_action_observations) ||
    Number(value.addressed_non_ton_swap_legs) > Number(value.non_ton_swap_legs) ||
    Number(value.same_run_fee_hash_match_candidates) > Number(value.fee_link_candidate_swaps) ||
    Number(value.fee_link_candidate_swaps) > Number(value.swap_observations)
  ) fail();
}

function validateBoundedCoverage(value: unknown, expectedIds: number[]) {
  if (
    !isRecord(value) ||
    value.contract_version !== "wallet_multi_run_interval_coverage_v1" ||
    !sameIdSet(value.selected_run_ids, expectedIds) ||
    value.interval_semantics !== "[start,end)" ||
    value.coverage_scope !== "selected_validated_run_intervals_only" ||
    value.gap_scope !== "inside_validated_selected_span_only" ||
    value.cross_stream_union_applied !== false ||
    value.full_pre_run_history_established !== false ||
    value.complete_wallet_history_established !== false ||
    value.is_global_history_coverage !== false ||
    value.is_authoritative_activity_coverage !== false ||
    value.activity_rows_merged !== false ||
    value.deduplication_applied !== false ||
    value.is_cost_basis !== false ||
    value.eligible_for_cost_basis !== false ||
    value.used_by_pnl !== false ||
    !validText(value.note, 4_000)
  ) fail();
  validateLayer(value.low_level_transactions, expectedIds, "transactions");
  validateLayer(value.provider_display_events, expectedIds, "account_events");
}

function validateLayer(value: unknown, expectedIds: number[], stream: "transactions" | "account_events") {
  if (!isRecord(value)) fail();
  const included = idArray(value.included_run_ids, expectedIds);
  const excluded = idArray(value.excluded_run_ids, expectedIds);
  const notRequested = idArray(value.not_requested_run_ids, expectedIds);
  const partition = [...included, ...excluded, ...notRequested];
  if (
    value.stream_key !== stream ||
    value.state !== "no_validated_intervals" && value.state !== "contiguous_selected_span" && value.state !== "gapped_selected_span" ||
    value.selected_run_count !== expectedIds.length ||
    !nonnegativeInteger(value.requested_run_count) ||
    value.requested_run_count !== included.length + excluded.length ||
    !nonnegativeInteger(value.included_run_count) ||
    value.included_run_count !== included.length ||
    !sameIdSet(partition, expectedIds) ||
    (value.selected_run_coverage_state !== "none" && value.selected_run_coverage_state !== "partial" && value.selected_run_coverage_state !== "complete") ||
    value.outside_selected_span_coverage !== "unknown" ||
    value.establishes_full_history !== false ||
    value.is_authoritative_activity_coverage !== false ||
    !decimalInteger(value.span_duration_microseconds) ||
    !decimalInteger(value.covered_duration_microseconds) ||
    !decimalInteger(value.gap_duration_microseconds) ||
    !decimalInteger(value.overlapped_duration_microseconds) ||
    !nonnegativeInteger(value.max_coverage_depth) ||
    value.max_coverage_depth > expectedIds.length ||
    typeof value.is_contiguous_within_selected_span !== "boolean" ||
    !Array.isArray(value.run_evidence) ||
    value.run_evidence.length !== expectedIds.length ||
    !sameIdSet(value.run_evidence.map((row) => isRecord(row) ? row.run_id : null), expectedIds) ||
    !Array.isArray(value.accepted_intervals) ||
    !Array.isArray(value.union_intervals) ||
    !Array.isArray(value.overlap_intervals) ||
    !Array.isArray(value.gap_intervals)
  ) fail();

  value.run_evidence.forEach((row) => validateRunEvidence(row, expectedIds, included, excluded, notRequested));
  value.accepted_intervals.forEach((row) => validateInterval(row, true, expectedIds));
  value.union_intervals.forEach((row) => validateInterval(row, false, expectedIds));
  value.overlap_intervals.forEach((row) => validateInterval(row, false, expectedIds));
  value.gap_intervals.forEach((row) => validateInterval(row, false, expectedIds));

  const hasSpan = value.selected_span !== null && value.selected_span !== undefined;
  if (hasSpan) validateInterval(value.selected_span, false, expectedIds);
  if (
    (value.state === "no_validated_intervals" && (included.length !== 0 || hasSpan || value.union_intervals.length !== 0)) ||
    (value.state === "contiguous_selected_span" && (!hasSpan || value.gap_intervals.length !== 0 || !value.is_contiguous_within_selected_span)) ||
    (value.state === "gapped_selected_span" && (!hasSpan || value.gap_intervals.length === 0 || value.is_contiguous_within_selected_span))
  ) fail();
}

function validateRunEvidence(value: unknown, expectedIds: number[], included: number[], excluded: number[], notRequested: number[]) {
  if (
    !isRecord(value) ||
    !positiveInteger(value.run_id) ||
    !expectedIds.includes(value.run_id) ||
    (value.classification !== "included" && value.classification !== "excluded" && value.classification !== "not_requested") ||
    value.classification !== (included.includes(value.run_id) ? "included" : excluded.includes(value.run_id) ? "excluded" : notRequested.includes(value.run_id) ? "not_requested" : null) ||
    typeof value.included_in_union !== "boolean" ||
    value.included_in_union !== (value.classification === "included") ||
    !Array.isArray(value.candidate_states) ||
    !Array.isArray(value.source_reason_codes) ||
    !(value.duration_microseconds === null || value.duration_microseconds === undefined || POSITIVE_DIGITS.test(String(value.duration_microseconds)))
  ) fail();
}

function validateInterval(value: unknown, requireRunId: boolean, expectedIds: number[]) {
  if (
    !isRecord(value) ||
    !timestamp(value.start) ||
    !timestamp(value.end) ||
    Date.parse(value.start) >= Date.parse(value.end) ||
    !POSITIVE_DIGITS.test(String(value.duration_microseconds)) ||
    (requireRunId && (!positiveInteger(value.run_id) || !expectedIds.includes(value.run_id)))
  ) fail();
}

function validateBlockers(value: unknown, selectedIds: number[]) {
  if (!Array.isArray(value) || value.length > 500) fail();
  const codes = new Set<string>();
  for (const blocker of value) {
    if (
      !isRecord(blocker) ||
      !validText(blocker.code, 160) ||
      codes.has(blocker.code) ||
      !validText(blocker.reason, 4_000) ||
      !Array.isArray(blocker.run_ids) ||
      !blocker.run_ids.every((id) => positiveInteger(id) && selectedIds.includes(id)) ||
      !isRecord(blocker.evidence)
    ) fail();
    codes.add(blocker.code);
  }
}

export function historyCoveragePercent(layer: WalletHistoryIntervalCoverageLayerRecord): number {
  if (!layer.selected_run_count) return 0;
  return Math.round((layer.included_run_count / layer.selected_run_count) * 100);
}

function validIdentity(value: unknown): boolean {
  return isRecord(value) &&
    (value.status === "network_scoped" || value.status === "unscoped" || value.status === "unavailable") &&
    (value.network === "ton-mainnet" || value.network === "ton-testnet" || value.network === "ton-unknown") &&
    value.is_account_existence_proof === false &&
    value.is_ownership_proof === false;
}

function uniqueRunIds(value: unknown): number[] {
  if (!Array.isArray(value) || !value.every(positiveInteger)) fail();
  const ids = [...new Set(value)];
  if (ids.length !== value.length) fail();
  return ids;
}

function idArray(value: unknown, allowed: number[]): number[] {
  const ids = uniqueRunIds(value);
  if (!ids.every((id) => allowed.includes(id))) fail();
  return ids;
}

function sameIdSet(value: unknown, expected: number[]): boolean {
  return Array.isArray(value) && value.length === expected.length && new Set(value).size === expected.length && value.every((id) => positiveInteger(id) && expected.includes(id));
}

function decimalInteger(value: unknown): boolean {
  return typeof value === "string" && DIGITS.test(value);
}

function nullableTimestamp(value: unknown): boolean {
  return value === null || value === undefined || timestamp(value);
}

function timestamp(value: unknown): value is string {
  return typeof value === "string" && Number.isFinite(Date.parse(value));
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) > 0;
}

function nonnegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && (value as number) >= 0;
}

function validText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maximum;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const keys = [...expected].sort();
  return actual.length === keys.length && actual.every((key, index) => key === keys[index]);
}

function fail(): never {
  throw new Error("History readiness response is incoherent.");
}
