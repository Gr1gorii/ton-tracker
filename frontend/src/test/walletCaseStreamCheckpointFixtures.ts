import type {
  WalletCaseBackfillOutcomeResponse,
  WalletCaseBackfillProgressResponse,
  WalletCaseBackfillScheduleResponse,
  WalletCaseCheckpointContinuationReceiptV1Response,
  WalletCaseCheckpointContinuationReceiptV2Response,
  WalletCaseCheckpointContinuationReceiptV3Response,
  WalletCaseCheckpointContinuationPlanResponse,
  WalletCaseStreamCheckpointCatalogResponse,
  WalletCaseStreamCheckpointChainResponse,
  WalletCaseStreamCheckpointDetailResponse,
  WalletCaseStreamCheckpointHistoryResponse,
} from "../walletCaseStreamCheckpoint";
import {
  CASE_ID,
  CHECKPOINT_ID,
  MANIFEST_HASH,
  OLDER_SYNC_ID,
  SYNC_ID,
} from "./walletCaseFixtures";

export const CHECKPOINT_HASH = "cd".repeat(32);

export function streamCheckpointCatalogFixture(): WalletCaseStreamCheckpointCatalogResponse {
  return {
    case_public_id: CASE_ID,
    checkpoint_count: 1,
    ready_count: 1,
    complete_count: 0,
    blocked_count: 0,
    checkpoints: [
      {
        checkpoint: {
          public_id: CHECKPOINT_ID,
          contract_version: "wallet_case_stream_checkpoint_v1",
          checkpoint_hash_sha256: CHECKPOINT_HASH,
          provider: "tonapi",
          stream_key: "transactions",
          provider_contract_version: "tonapi_account_transactions_v1",
          source_sync_public_id: SYNC_ID,
          resume_state: "ready",
          created_at: "2026-08-28T12:00:03Z",
        },
        document: {
          contract_version: "wallet_case_stream_checkpoint_v1",
          case_public_id: CASE_ID,
          source_sync_public_id: SYNC_ID,
          source_manifest_public_id: `smf_${MANIFEST_HASH}`,
          source_manifest_hash_sha256: MANIFEST_HASH,
          provider: "tonapi",
          stream_key: "transactions",
          provider_contract_version: "tonapi_account_transactions_v1",
          acquisition_mode: "bounded",
          requested_period: {
            start_at: "2026-08-08T12:00:00Z",
            end_at: "2026-08-09T12:00:00Z",
          },
          sort_order: "desc",
          page_size: 100,
          page_cap: 1,
          completion_state: "incomplete",
          termination_reason: "page_cap_reached",
          page_count: 1,
          pages_succeeded: 1,
          resume_state: "ready",
          resume_blocker: null,
          continuation_cursor: "10",
          continuation_page_index: 2,
          last_successful_page: {
            page_index: 1,
            response_cursor: "10",
            response_digest_sha256: "ab".repeat(32),
            min_logical_time: "10",
            max_logical_time: "20",
            min_timestamp: "2026-08-09T11:50:00Z",
            max_timestamp: "2026-08-09T11:55:00Z",
            fetched_at: "2026-08-09T12:00:00Z",
          },
        },
      },
    ],
  };
}

export function streamCheckpointDetailFixture(): WalletCaseStreamCheckpointDetailResponse {
  const checkpoint = streamCheckpointCatalogFixture().checkpoints[0];
  return {
    ...checkpoint,
    lineage: {
      acquisition_mode: "bounded",
      base_snapshot_public_id: null,
      parent_checkpoint_public_id: null,
      chain_depth: 0,
    },
  };
}

export function streamCheckpointHistoryFixture(
  { hasMore = true }: { hasMore?: boolean } = {},
): WalletCaseStreamCheckpointHistoryResponse {
  const { checkpoint, document } = streamCheckpointCatalogFixture().checkpoints[0];
  return {
    contract_version: "wallet_case_stream_checkpoint_history_v1",
    case_public_id: CASE_ID,
    revision_cutoff_public_id: checkpoint.public_id,
    items: [{
      checkpoint,
      lineage: {
        acquisition_mode: "bounded",
        base_snapshot_public_id: null,
        parent_checkpoint_public_id: null,
        chain_depth: 0,
      },
      continuation_page_index: document.continuation_page_index,
      page_count: document.page_count,
      pages_succeeded: document.pages_succeeded,
    }],
    aggregate: { total_revisions: hasMore ? 2 : 1, returned_count: 1 },
    page: {
      limit: 1,
      has_more: hasMore,
      next_cursor: hasMore ? "opaque-signed.cursor" : null,
    },
    limitations: [{
      code: "checkpoint_history_is_explicit_revisions",
      message: "Checkpoint revisions do not prove complete wallet history.",
    }],
  };
}

export function streamCheckpointChainFixture(): WalletCaseStreamCheckpointChainResponse {
  const tip = streamCheckpointCatalogFixture().checkpoints[0];
  const rootHash = "ef".repeat(32);
  const rootId = `scp_${rootHash}`;
  const rootManifestHash = "12".repeat(32);
  const chainHash = "34".repeat(32);
  const requestedPeriod = { ...tip.document.requested_period };
  return {
    chain: {
      public_id: `cch_${chainHash}`,
      contract_version: "wallet_case_stream_checkpoint_chain_v1",
      content_hash_sha256: chainHash,
      revision_count: 2,
      page_count: 2,
      pages_succeeded: 2,
    },
    document: {
      contract_version: "wallet_case_stream_checkpoint_chain_v1",
      case_public_id: CASE_ID,
      tip_checkpoint_public_id: tip.checkpoint.public_id,
      provider: tip.checkpoint.provider,
      stream_key: tip.checkpoint.stream_key,
      provider_contract_version: tip.checkpoint.provider_contract_version,
      root_acquisition_mode: "bounded",
      root_base_snapshot_public_id: null,
      current_resume_state: "ready",
      next_page_index: 3,
      aggregate: { revision_count: 2, page_count: 2, pages_succeeded: 2 },
      revisions: [
        {
          ordinal: 0,
          checkpoint: {
            ...tip.checkpoint,
            public_id: rootId,
            checkpoint_hash_sha256: rootHash,
            source_sync_public_id: OLDER_SYNC_ID,
            created_at: "2026-08-28T11:00:03Z",
          },
          acquisition_mode: "bounded",
          base_snapshot_public_id: null,
          parent_checkpoint_public_id: null,
          source_manifest_public_id: `smf_${rootManifestHash}`,
          source_manifest_hash_sha256: rootManifestHash,
          requested_period: requestedPeriod,
          continuation_page_index: 2,
          page_count: 1,
          pages_succeeded: 1,
          last_response_digest_sha256: "56".repeat(32),
        },
        {
          ordinal: 1,
          checkpoint: tip.checkpoint,
          acquisition_mode: "resume",
          base_snapshot_public_id: OLDER_SYNC_ID,
          parent_checkpoint_public_id: rootId,
          source_manifest_public_id: `smf_${MANIFEST_HASH}`,
          source_manifest_hash_sha256: MANIFEST_HASH,
          requested_period: requestedPeriod,
          continuation_page_index: 3,
          page_count: 1,
          pages_succeeded: 1,
          last_response_digest_sha256: "ab".repeat(32),
        },
      ],
      limitations: [{
        code: "checkpoint_chain_is_acquisition_progress",
        message: "Checkpoint pages do not prove complete wallet history.",
      }],
    },
  };
}

export function checkpointContinuationPlanFixture(): WalletCaseCheckpointContinuationPlanResponse {
  const chain = streamCheckpointChainFixture();
  const tip = chain.document.revisions[chain.document.revisions.length - 1].checkpoint;
  const planHash = "78".repeat(32);
  const aggregate = {
    stream_count: 1,
    ready_count: 1,
    complete_count: 0,
    blocked_count: 0,
    revision_count: chain.chain.revision_count,
    page_count: chain.chain.page_count,
    pages_succeeded: chain.chain.pages_succeeded,
  };
  return {
    plan: {
      public_id: `cpl_${planHash}`,
      contract_version: "wallet_case_checkpoint_continuation_plan_v1",
      content_hash_sha256: planHash,
      checkpoint_cutoff_public_id: tip.public_id,
      ...aggregate,
    },
    document: {
      contract_version: "wallet_case_checkpoint_continuation_plan_v1",
      case_public_id: CASE_ID,
      checkpoint_cutoff_public_id: tip.public_id,
      aggregate,
      streams: [{
        provider: tip.provider,
        stream_key: tip.stream_key,
        provider_contract_version: tip.provider_contract_version,
        tip_checkpoint: tip,
        chain_public_id: chain.chain.public_id,
        chain_content_hash_sha256: chain.chain.content_hash_sha256,
        revision_count: chain.chain.revision_count,
        page_count: chain.chain.page_count,
        pages_succeeded: chain.chain.pages_succeeded,
        resume_state: "ready",
        next_page_index: chain.document.next_page_index,
        resume_blocker: null,
      }],
      limitations: [{
        code: "continuation_plan_is_not_automatic_backfill",
        message: "The plan does not schedule provider requests or prove complete history.",
      }],
    },
  };
}

export function backfillProgressFixture(): WalletCaseBackfillProgressResponse {
  const chain = streamCheckpointChainFixture();
  const root = chain.document.revisions[0].checkpoint;
  const tip = chain.document.revisions[1].checkpoint;
  const rootPage = {
    page_index: 1,
    response_cursor: "10",
    response_digest_sha256: "56".repeat(32),
    min_logical_time: "10",
    max_logical_time: "20",
    min_timestamp: "2026-08-09T11:50:00Z",
    max_timestamp: "2026-08-09T11:55:00Z",
    fetched_at: "2026-08-09T12:00:00Z",
  };
  const currentPage = {
    ...rootPage,
    page_index: 2,
    response_cursor: "20",
    response_digest_sha256: "ab".repeat(32),
    min_logical_time: "1",
    max_logical_time: "9",
    min_timestamp: "2026-08-09T11:40:00Z",
    max_timestamp: "2026-08-09T11:49:00Z",
  };
  const aggregate = {
    stream_count: 1,
    ready_count: 1,
    complete_count: 0,
    blocked_count: 0,
    revision_count: 2,
    continuation_revision_count: 1,
    page_count: 2,
    pages_succeeded: 2,
    continuation_page_count: 1,
    continuation_pages_succeeded: 1,
    observed_frontier_count: 1,
    advanced_frontier_count: 1,
  };
  const progressHash = "9b".repeat(32);
  return {
    progress: {
      public_id: `bfp_${progressHash}`,
      contract_version: "wallet_case_backfill_progress_v1",
      content_hash_sha256: progressHash,
      checkpoint_cutoff_public_id: tip.public_id,
      ...aggregate,
    },
    document: {
      contract_version: "wallet_case_backfill_progress_v1",
      case_public_id: CASE_ID,
      checkpoint_cutoff_public_id: tip.public_id,
      aggregate,
      streams: [{
        provider: tip.provider,
        stream_key: tip.stream_key,
        provider_contract_version: tip.provider_contract_version,
        root_checkpoint_public_id: root.public_id,
        tip_checkpoint: tip,
        chain_public_id: chain.chain.public_id,
        chain_content_hash_sha256: chain.chain.content_hash_sha256,
        root_acquisition_mode: "bounded",
        requested_period: chain.document.revisions[0].requested_period,
        revision_count: 2,
        initial_page_count: 1,
        initial_pages_succeeded: 1,
        continuation_revision_count: 1,
        continuation_page_count: 1,
        continuation_pages_succeeded: 1,
        page_count: 2,
        pages_succeeded: 2,
        resume_state: "ready",
        requested_interval_complete: false,
        next_page_index: 3,
        termination_reason: "page_cap_reached",
        resume_blocker: null,
        root_frontier: {
          checkpoint_public_id: root.public_id,
          page: rootPage,
        },
        current_frontier: {
          checkpoint_public_id: tip.public_id,
          page: currentPage,
        },
        frontier_advanced: true,
      }],
      limitations: [{
        code: "backfill_remaining_work_is_unknown",
        message: "Provider cursors do not expose a reliable remaining-page count.",
      }],
    },
  };
}

export function backfillScheduleFixture(): WalletCaseBackfillScheduleResponse {
  const progress = backfillProgressFixture();
  const plan = checkpointContinuationPlanFixture();
  const selected = progress.document.streams[0];
  const scheduleHash = "8c".repeat(32);
  return {
    schedule: {
      public_id: `bfs_${scheduleHash}`,
      contract_version: "wallet_case_backfill_schedule_v1",
      content_hash_sha256: scheduleHash,
      state: "ready",
      input_progress_public_id: progress.progress.public_id,
      input_plan_public_id: plan.plan.public_id,
      checkpoint_cutoff_public_id: progress.progress.checkpoint_cutoff_public_id,
      page_budget: 3,
      selected_checkpoint_public_id: selected.tip_checkpoint.public_id,
      active_sync_public_id: null,
    },
    document: {
      contract_version: "wallet_case_backfill_schedule_v1",
      case_public_id: CASE_ID,
      input_progress_public_id: progress.progress.public_id,
      input_plan_public_id: plan.plan.public_id,
      checkpoint_cutoff_public_id: progress.progress.checkpoint_cutoff_public_id,
      page_budget: 3,
      selection_policy: "least_continuation_pages_then_revisions_then_provider_stream_v1",
      state: "ready",
      stream_count: 1,
      ready_count: 1,
      complete_count: 0,
      blocked_count: 0,
      active_sync_public_id: null,
      selection: {
        provider: selected.provider,
        stream_key: selected.stream_key,
        checkpoint_public_id: selected.tip_checkpoint.public_id,
        continuation_revision_count: selected.continuation_revision_count,
        continuation_page_count: selected.continuation_page_count,
        next_page_index: selected.next_page_index as number,
      },
      limitations: [{
        code: "backfill_schedule_is_one_finite_step",
        message: "This schedule selects one finite provider continuation.",
      }],
    },
  };
}

export function checkpointContinuationReceiptFixture(): WalletCaseCheckpointContinuationReceiptV1Response {
  const outputChain = streamCheckpointChainFixture();
  const afterPlan = checkpointContinuationPlanFixture();
  const inputCheckpoint = outputChain.document.revisions[0].checkpoint;
  const outputCheckpoint = outputChain.document.revisions[1].checkpoint;
  const inputPlanHash = "9a".repeat(32);
  const inputChainHash = "bc".repeat(32);
  const receiptHash = "de".repeat(32);
  const transition = {
    checkpoint_changed: true as const,
    plan_changed: true as const,
    revision_delta: 1 as const,
    page_count_delta: 1,
    pages_succeeded_delta: 1,
  };
  return {
    receipt: {
      public_id: `ctr_${receiptHash}`,
      contract_version: "wallet_case_checkpoint_continuation_receipt_v1",
      content_hash_sha256: receiptHash,
      sync_public_id: SYNC_ID,
      input_plan_public_id: `cpl_${inputPlanHash}`,
      input_checkpoint_public_id: inputCheckpoint.public_id,
      output_checkpoint_public_id: outputCheckpoint.public_id,
      after_plan_public_id: afterPlan.plan.public_id,
      revision_delta: 1,
      page_count_delta: 1,
      pages_succeeded_delta: 1,
    },
    document: {
      contract_version: "wallet_case_checkpoint_continuation_receipt_v1",
      case_public_id: CASE_ID,
      sync_public_id: SYNC_ID,
      input: {
        continuation_plan_public_id: `cpl_${inputPlanHash}`,
        checkpoint: inputCheckpoint,
        chain_public_id: `cch_${inputChainHash}`,
        chain_content_hash_sha256: inputChainHash,
        revision_count: 1,
        page_count: 1,
        pages_succeeded: 1,
        next_page_index: 2,
      },
      output: {
        checkpoint: outputCheckpoint,
        chain_public_id: outputChain.chain.public_id,
        chain_content_hash_sha256: outputChain.chain.content_hash_sha256,
        revision_count: outputChain.chain.revision_count,
        page_count: outputChain.chain.page_count,
        pages_succeeded: outputChain.chain.pages_succeeded,
        resume_state: outputChain.document.current_resume_state,
        next_page_index: outputChain.document.next_page_index,
        resume_blocker: null,
      },
      after_plan: afterPlan,
      transition,
      limitations: [{
        code: "continuation_receipt_is_provider_progress",
        message: "The receipt proves one checkpoint transition, not complete history.",
      }],
    },
  };
}

export function checkpointContinuationReceiptV2Fixture(): WalletCaseCheckpointContinuationReceiptV2Response {
  const legacy = checkpointContinuationReceiptFixture();
  return {
    receipt: {
      ...legacy.receipt,
      contract_version: "wallet_case_checkpoint_continuation_receipt_v2",
      page_budget: 3,
      page_budget_consumed: 1,
      page_budget_remaining: 2,
    },
    document: {
      ...legacy.document,
      contract_version: "wallet_case_checkpoint_continuation_receipt_v2",
      input: {
        ...legacy.document.input,
        page_budget: 3,
      },
      transition: {
        ...legacy.document.transition,
        page_budget_consumed: 1,
        page_budget_remaining: 2,
      },
    },
  };
}

export function checkpointContinuationReceiptV3Fixture(): WalletCaseCheckpointContinuationReceiptV3Response {
  const budgeted = checkpointContinuationReceiptV2Fixture();
  const scheduleId = backfillScheduleFixture().schedule.public_id;
  return {
    receipt: {
      ...budgeted.receipt,
      contract_version: "wallet_case_checkpoint_continuation_receipt_v3",
      input_schedule_public_id: scheduleId,
    },
    document: {
      ...budgeted.document,
      contract_version: "wallet_case_checkpoint_continuation_receipt_v3",
      input: {
        ...budgeted.document.input,
        backfill_schedule_public_id: scheduleId,
      },
    },
  };
}

export function backfillOutcomeFixture(): WalletCaseBackfillOutcomeResponse {
  const inputSchedule = backfillScheduleFixture();
  const inputProgress = backfillProgressFixture();
  const inputStream = inputProgress.document.streams[0];
  const outputHash = "67".repeat(32);
  const outputCheckpoint = {
    ...inputStream.tip_checkpoint,
    public_id: `scp_${outputHash}`,
    checkpoint_hash_sha256: outputHash,
    source_sync_public_id: SYNC_ID,
    created_at: "2026-08-28T13:00:03Z",
  };
  const outputChainHash = "68".repeat(32);
  const outputPlanHash = "69".repeat(32);
  const outputProgressHash = "6a".repeat(32);
  const receiptHash = "6b".repeat(32);
  const outcomeHash = "6c".repeat(32);
  const outputAggregate = {
    ...inputProgress.document.aggregate,
    revision_count: 3,
    continuation_revision_count: 2,
    page_count: 3,
    pages_succeeded: 3,
    continuation_page_count: 2,
    continuation_pages_succeeded: 2,
  };
  const outputPage = {
    ...(inputStream.current_frontier?.page as NonNullable<
      typeof inputStream.current_frontier
    >["page"]),
    page_index: 3,
    response_cursor: "30",
    response_digest_sha256: "6d".repeat(32),
    min_logical_time: "1",
    max_logical_time: "8",
  };
  const outputProgress: WalletCaseBackfillProgressResponse = {
    progress: {
      public_id: `bfp_${outputProgressHash}`,
      contract_version: "wallet_case_backfill_progress_v1",
      content_hash_sha256: outputProgressHash,
      checkpoint_cutoff_public_id: outputCheckpoint.public_id,
      ...outputAggregate,
    },
    document: {
      ...inputProgress.document,
      checkpoint_cutoff_public_id: outputCheckpoint.public_id,
      aggregate: outputAggregate,
      streams: [{
        ...inputStream,
        tip_checkpoint: outputCheckpoint,
        chain_public_id: `cch_${outputChainHash}`,
        chain_content_hash_sha256: outputChainHash,
        revision_count: 3,
        continuation_revision_count: 2,
        continuation_page_count: 2,
        continuation_pages_succeeded: 2,
        page_count: 3,
        pages_succeeded: 3,
        next_page_index: 4,
        current_frontier: {
          checkpoint_public_id: outputCheckpoint.public_id,
          page: outputPage,
        },
      }],
    },
  };
  const afterPlan: WalletCaseCheckpointContinuationPlanResponse = {
    plan: {
      public_id: `cpl_${outputPlanHash}`,
      contract_version: "wallet_case_checkpoint_continuation_plan_v1",
      content_hash_sha256: outputPlanHash,
      checkpoint_cutoff_public_id: outputCheckpoint.public_id,
      stream_count: 1,
      ready_count: 1,
      complete_count: 0,
      blocked_count: 0,
      revision_count: 3,
      page_count: 3,
      pages_succeeded: 3,
    },
    document: {
      contract_version: "wallet_case_checkpoint_continuation_plan_v1",
      case_public_id: CASE_ID,
      checkpoint_cutoff_public_id: outputCheckpoint.public_id,
      aggregate: {
        stream_count: 1,
        ready_count: 1,
        complete_count: 0,
        blocked_count: 0,
        revision_count: 3,
        page_count: 3,
        pages_succeeded: 3,
      },
      streams: [{
        provider: outputCheckpoint.provider,
        stream_key: outputCheckpoint.stream_key,
        provider_contract_version: outputCheckpoint.provider_contract_version,
        tip_checkpoint: outputCheckpoint,
        chain_public_id: `cch_${outputChainHash}`,
        chain_content_hash_sha256: outputChainHash,
        revision_count: 3,
        page_count: 3,
        pages_succeeded: 3,
        resume_state: "ready",
        next_page_index: 4,
        resume_blocker: null,
      }],
      limitations: [{
        code: "continuation_plan_is_not_automatic_backfill",
        message: "The after-plan does not start another provider request.",
      }],
    },
  };
  const receipt: WalletCaseCheckpointContinuationReceiptV3Response = {
    receipt: {
      public_id: `ctr_${receiptHash}`,
      contract_version: "wallet_case_checkpoint_continuation_receipt_v3",
      content_hash_sha256: receiptHash,
      sync_public_id: SYNC_ID,
      input_plan_public_id: inputSchedule.schedule.input_plan_public_id,
      input_checkpoint_public_id: inputStream.tip_checkpoint.public_id,
      output_checkpoint_public_id: outputCheckpoint.public_id,
      after_plan_public_id: afterPlan.plan.public_id,
      revision_delta: 1,
      page_count_delta: 1,
      pages_succeeded_delta: 1,
      page_budget: 3,
      page_budget_consumed: 1,
      page_budget_remaining: 2,
      input_schedule_public_id: inputSchedule.schedule.public_id,
    },
    document: {
      contract_version: "wallet_case_checkpoint_continuation_receipt_v3",
      case_public_id: CASE_ID,
      sync_public_id: SYNC_ID,
      input: {
        continuation_plan_public_id: inputSchedule.schedule.input_plan_public_id,
        checkpoint: inputStream.tip_checkpoint,
        chain_public_id: inputStream.chain_public_id,
        chain_content_hash_sha256: inputStream.chain_content_hash_sha256,
        revision_count: 2,
        page_count: 2,
        pages_succeeded: 2,
        next_page_index: 3,
        page_budget: 3,
        backfill_schedule_public_id: inputSchedule.schedule.public_id,
      },
      output: {
        checkpoint: outputCheckpoint,
        chain_public_id: `cch_${outputChainHash}`,
        chain_content_hash_sha256: outputChainHash,
        revision_count: 3,
        page_count: 3,
        pages_succeeded: 3,
        resume_state: "ready",
        next_page_index: 4,
        resume_blocker: null,
      },
      after_plan: afterPlan,
      transition: {
        checkpoint_changed: true,
        plan_changed: true,
        revision_delta: 1,
        page_count_delta: 1,
        pages_succeeded_delta: 1,
        page_budget_consumed: 1,
        page_budget_remaining: 2,
      },
      limitations: [{
        code: "continuation_receipt_is_provider_progress",
        message: "The receipt proves one checkpoint transition.",
      }],
    },
  };
  const transition = {
    provider: inputStream.provider,
    stream_key: inputStream.stream_key,
    input_checkpoint_public_id: inputStream.tip_checkpoint.public_id,
    output_checkpoint_public_id: outputCheckpoint.public_id,
    before_resume_state: "ready" as const,
    after_resume_state: "ready" as const,
    revision_delta: 1 as const,
    page_count_delta: 1,
    pages_succeeded_delta: 1,
    continuation_revision_delta: 1 as const,
    continuation_page_count_delta: 1,
    continuation_pages_succeeded_delta: 1,
    ready_count_delta: 0,
    complete_count_delta: 0,
    blocked_count_delta: 0,
    frontier_changed: true,
  };
  return {
    outcome: {
      public_id: `bfo_${outcomeHash}`,
      contract_version: "wallet_case_backfill_outcome_v1",
      content_hash_sha256: outcomeHash,
      sync_public_id: SYNC_ID,
      outcome: "advanced",
      input_schedule_public_id: inputSchedule.schedule.public_id,
      continuation_receipt_public_id: receipt.receipt.public_id,
      input_progress_public_id: inputProgress.progress.public_id,
      output_progress_public_id: outputProgress.progress.public_id,
      provider: transition.provider,
      stream_key: transition.stream_key,
      page_count_delta: 1,
      pages_succeeded_delta: 1,
      before_resume_state: "ready",
      after_resume_state: "ready",
    },
    document: {
      contract_version: "wallet_case_backfill_outcome_v1",
      case_public_id: CASE_ID,
      sync_public_id: SYNC_ID,
      input_schedule: inputSchedule,
      input_progress: inputProgress,
      continuation_receipt: receipt,
      output_progress: outputProgress,
      outcome: "advanced",
      transition,
      limitations: [{
        code: "backfill_outcome_is_not_full_history_proof",
        message: "The outcome does not prove complete wallet history.",
      }],
    },
  };
}
