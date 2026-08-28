import type { WalletCaseStreamCheckpointCatalogResponse } from "../walletCaseStreamCheckpoint";
import { CASE_ID, MANIFEST_HASH, SYNC_ID } from "./walletCaseFixtures";

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
          public_id: `scp_${CHECKPOINT_HASH}`,
          contract_version: "wallet_case_stream_checkpoint_v1",
          checkpoint_hash_sha256: CHECKPOINT_HASH,
          provider: "tonapi_wallet_activity_live",
          stream_key: "account_transactions",
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
          provider: "tonapi_wallet_activity_live",
          stream_key: "account_transactions",
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
          continuation_cursor: "cursor-2",
          continuation_page_index: 2,
          last_successful_page: {
            page_index: 1,
            response_cursor: "cursor-2",
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
