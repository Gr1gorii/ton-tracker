import { describe, expect, it } from "vitest";

import type { WalletTransactionRecord } from "./types";
import {
  eligibleTraceTransactions,
  validatePersistedWalletTransactionTraceEvidenceResponse,
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

const PERSISTED_EXPECTED = {
  ...EXPECTED,
  network: "ton-mainnet" as const,
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

function persistedResponse(overrides: Record<string, unknown> = {}) {
  return {
    contract_version: "tonapi_low_level_trace_evidence_v1",
    capture_id: "9",
    run_id: "25",
    provider: "tonapi",
    source_status: "live",
    network: "ton-mainnet",
    trace_state: "finalized",
    captured_at: "2026-07-10T12:34:56.123456Z",
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
      message_count: 5,
      root_inbound_message_count: 1,
      child_internal_message_count: 2,
      remaining_out_message_count: 2,
      internal_message_count: 2,
      external_in_message_count: 1,
      external_out_message_count: 2,
      successful_transaction_count: 2,
      failed_transaction_count: 1,
      aborted_transaction_count: 1,
      unique_account_count: 2,
    },
    evidence_digest_sha256: "d".repeat(64),
    is_provider_indexed_low_level_trace: true,
    provider_structure_validated: true,
    persisted_graph_revalidated: true,
    is_immutable_record: true,
    raw_boc_persisted: false,
    message_body_persisted: false,
    is_blockchain_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: "Immutable sanitized low-level trace evidence.",
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
        network: "ton-mainnet",
        timestamp: "2026-07-10T01:00:00Z",
      },
    ]);
  });

  it("rejects an unknown-network identity before either trace endpoint", () => {
    expect(
      eligibleTraceTransactions([
        transaction({
          transaction_identity: {
            ...transaction().transaction_identity,
            network: "ton-unknown",
          },
        }),
      ]),
    ).toEqual([]);
  });
});

describe("validatePersistedWalletTransactionTraceEvidenceResponse", () => {
  it("accepts the exact immutable finalized graph contract", () => {
    const validated = validatePersistedWalletTransactionTraceEvidenceResponse(
      persistedResponse(),
      PERSISTED_EXPECTED,
    );

    expect(validated.capture_id).toBe("9");
    expect(validated.network).toBe("ton-mainnet");
    expect(validated.summary.message_count).toBe(5);
    expect(validated.persisted_graph_revalidated).toBe(true);
    expect(validated.is_blockchain_proof_verified).toBe(false);
    expect(validated.raw_boc_persisted).toBe(false);
  });

  it.each([
    ["extra raw field", { ...persistedResponse(), raw_trace: {} }],
    ["wrong network", persistedResponse({ network: "ton-testnet" })],
    ["noncanonical capture id", persistedResponse({ capture_id: "09" })],
    ["non-UTC capture time", persistedResponse({ captured_at: "2026-07-10T12:34:56+02:00" })],
    ["mutable record", persistedResponse({ is_immutable_record: false })],
    ["unvalidated provider structure", persistedResponse({ provider_structure_validated: false })],
    ["raw BOC promotion", persistedResponse({ raw_boc_persisted: true })],
    ["semantic promotion", persistedResponse({ semantic_reconstruction_applied: true })],
  ])("rejects %s fail closed", (_label, candidate) => {
    expect(() =>
      validatePersistedWalletTransactionTraceEvidenceResponse(
        candidate,
        PERSISTED_EXPECTED,
      ),
    ).toThrow();
  });

  it.each([
    [
      "child edge mismatch",
      { ...persistedResponse().summary, child_internal_message_count: 1 },
    ],
    [
      "message total mismatch",
      { ...persistedResponse().summary, message_count: 6 },
    ],
    [
      "message type mismatch",
      { ...persistedResponse().summary, external_out_message_count: 1 },
    ],
    [
      "message cap",
      {
        ...persistedResponse().summary,
        message_count: 2305,
        remaining_out_message_count: 2302,
        external_out_message_count: 2302,
      },
    ],
  ])("rejects an incoherent %s", (_label, summary) => {
    expect(() =>
      validatePersistedWalletTransactionTraceEvidenceResponse(
        persistedResponse({ summary }),
        PERSISTED_EXPECTED,
      ),
    ).toThrow("graph summary values");
  });
});
