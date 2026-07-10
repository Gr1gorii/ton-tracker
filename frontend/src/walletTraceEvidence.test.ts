import { describe, expect, it } from "vitest";

import type { WalletTransactionRecord } from "./types";
import {
  eligibleTraceTransactions,
  validateWalletTransactionTraceEvidenceResponse,
} from "./walletTraceEvidence";

const HASH = "a".repeat(64);
const ROOT_HASH = "b".repeat(64);
const ACCOUNT = `0:${"c".repeat(64)}`;
const EXPECTED = {
  runId: 25,
  transactionHash: HASH,
  logicalTime: "46000000000001",
  accountCanonical: ACCOUNT,
};

function response(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "tonapi_transaction_trace_preview_v1",
    run_id: "25",
    provider: "tonapi",
    source_status: "live",
    trace_state: "finalized",
    anchor: {
      transaction_hash: HASH,
      logical_time: "46000000000001",
      account_canonical: ACCOUNT,
      matches_stored_transaction: true,
    },
    summary: {
      root_transaction_hash: ROOT_HASH,
      transaction_count: 3,
      max_depth: 2,
      out_message_count: 4,
      pending_internal_message_count: 0,
      successful_transaction_count: 2,
      failed_transaction_count: 1,
      aborted_transaction_count: 1,
      unique_account_count: 2,
    },
    is_provider_indexed_low_level_trace: true,
    is_blockchain_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: "Sanitized provider trace summary.",
    ...overrides,
  };
}

function transaction(overrides: Partial<WalletTransactionRecord> = {}) {
  return {
    tx_hash: HASH.toUpperCase(),
    logical_time: "46000000000001",
    timestamp: "2026-07-10T01:00:00Z",
    fee_ton: "0.01",
    success: "success" as const,
    provider: "tonapi",
    source_status: "live" as const,
    transaction_identity: {
      status: "network_scoped" as const,
      version: "ton_account_tx_v1",
      network: "ton-mainnet" as const,
      account_canonical: ACCOUNT,
      logical_time_canonical: "46000000000001",
      hash_canonical: HASH,
      key: `ton_account_tx_v1|ton-mainnet|${ACCOUNT}|46000000000001|${HASH}`,
      is_deduplication_identity: true,
      is_blockchain_proof_verified: false as const,
      is_ownership_proof: false as const,
      deduplication_applied: false as const,
      used_by_pnl: false as const,
    },
    raw: null,
    ...overrides,
  } satisfies WalletTransactionRecord;
}

describe("validateWalletTransactionTraceEvidenceResponse", () => {
  it("accepts the exact finalized provider contract and stored anchor", () => {
    const validated = validateWalletTransactionTraceEvidenceResponse(
      response(),
      EXPECTED,
    );

    expect(validated.run_id).toBe("25");
    expect(validated.anchor.transaction_hash).toBe(HASH);
    expect(validated.summary.transaction_count).toBe(3);
    expect(validated.is_authoritative_activity_identity).toBe(false);
    expect(validated.used_by_pnl).toBe(false);
  });

  it("accepts a coherent pending trace without promoting its semantics", () => {
    const validated = validateWalletTransactionTraceEvidenceResponse(
      response({
        trace_state: "pending",
        summary: {
          ...response().summary,
          pending_internal_message_count: 2,
        },
      }),
      EXPECTED,
    );

    expect(validated.trace_state).toBe("pending");
    expect(validated.semantic_reconstruction_applied).toBe(false);
  });

  it.each([
    ["unexpected field", { ...response(), raw_trace: { secret: true } }],
    ["wrong run", response({ run_id: "26" })],
    [
      "wrong anchor hash",
      response({
        anchor: {
          ...response().anchor,
          transaction_hash: "d".repeat(64),
        },
      }),
    ],
    [
      "wrong logical time",
      response({
        anchor: { ...response().anchor, logical_time: "46000000000002" },
      }),
    ],
    [
      "wrong account",
      response({
        anchor: {
          ...response().anchor,
          account_canonical: `0:${"d".repeat(64)}`,
        },
      }),
    ],
    ["authority promotion", response({ is_authoritative_activity_identity: true })],
    ["PnL promotion", response({ used_by_pnl: true })],
    ["provider trace demotion", response({ is_provider_indexed_low_level_trace: false })],
  ])("rejects %s fail closed", (_label, candidate) => {
    expect(() =>
      validateWalletTransactionTraceEvidenceResponse(candidate, EXPECTED),
    ).toThrow();
  });

  it("rejects incoherent state, counts, hashes, and false-flag shapes", () => {
    expect(() =>
      validateWalletTransactionTraceEvidenceResponse(
        response({
          summary: {
            ...response().summary,
            transaction_count: -1,
          },
        }),
        EXPECTED,
      ),
    ).toThrow("summary values");
    expect(() =>
      validateWalletTransactionTraceEvidenceResponse(
        response({
          summary: {
            ...response().summary,
            successful_transaction_count: 3,
            failed_transaction_count: 1,
          },
        }),
        EXPECTED,
      ),
    ).toThrow("summary values");
    expect(() =>
      validateWalletTransactionTraceEvidenceResponse(
        response({
          trace_state: "pending",
          summary: {
            ...response().summary,
            pending_internal_message_count: 0,
          },
        }),
        EXPECTED,
      ),
    ).toThrow("incoherent trace state");
    expect(() =>
      validateWalletTransactionTraceEvidenceResponse(
        response({
          summary: {
            ...response().summary,
            root_transaction_hash: HASH.toUpperCase(),
          },
        }),
        EXPECTED,
      ),
    ).toThrow("summary values");
  });
});

describe("eligibleTraceTransactions", () => {
  it("selects only coherent live TonAPI transaction identities and deduplicates hashes", () => {
    const eligible = eligibleTraceTransactions([
      transaction(),
      transaction(),
      transaction({ source_status: "mock" }),
      transaction({
        provider: "other",
      }),
      transaction({
        transaction_identity: {
          ...transaction().transaction_identity,
          hash_canonical: "not-a-hash",
        },
      }),
    ]);

    expect(eligible).toEqual([
      {
        transactionHash: HASH,
        logicalTime: "46000000000001",
        accountCanonical: ACCOUNT,
        timestamp: "2026-07-10T01:00:00Z",
      },
    ]);
  });
});
