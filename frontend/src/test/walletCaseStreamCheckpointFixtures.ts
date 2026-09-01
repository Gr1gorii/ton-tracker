import type {
  WalletCaseCheckpointContinuationReceiptV1Response,
  WalletCaseCheckpointContinuationReceiptV2Response,
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
