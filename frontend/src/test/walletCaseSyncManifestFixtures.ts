import type { WalletCaseSyncManifestResponse } from "../walletCaseSyncManifest";
import {
  CASE_ID,
  MANIFEST_HASH,
  SYNC_ID,
  manifestDescriptorFixture,
} from "./walletCaseFixtures";

export function manifestResponseFixture(): WalletCaseSyncManifestResponse {
  return {
    manifest: manifestDescriptorFixture(),
    document: {
      contract_version: "wallet_case_sync_manifest_v1",
      case_public_id: CASE_ID,
      sync_public_id: SYNC_ID,
      network: "ton-mainnet",
      data_mode: "mock",
      provider: "mock_wallet_activity",
      sync_state: "succeeded",
      snapshot_period: {
        start_at: "2026-08-08T12:00:00Z",
        end_at: "2026-08-09T12:00:00Z",
      },
      acquisition_period: {
        start_at: "2026-08-08T12:00:00Z",
        end_at: "2026-08-09T12:00:00Z",
      },
      acquisition_mode: "bounded",
      overlap_seconds: 0,
      base_snapshot_public_id: null,
      requested_surfaces: [
        "balances", "jettons", "swaps", "transactions", "transfers",
      ],
      streams: [],
    },
  };
}

export { MANIFEST_HASH };
