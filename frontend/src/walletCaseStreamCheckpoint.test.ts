import { describe, expect, it } from "vitest";

import {
  backfillOutcomeHistoryFixture,
  backfillOutcomeFixture,
  backfillProgressFixture,
  backfillScheduleFixture,
  checkpointContinuationReceiptFixture,
  checkpointContinuationReceiptV2Fixture,
  checkpointContinuationReceiptV3Fixture,
  checkpointContinuationPlanFixture,
  completeHistoryGateFixture,
  earliestActivityAnchorFixture,
  observedHistoryFloorFixture,
  streamCheckpointCatalogFixture,
  streamCheckpointChainFixture,
  streamCheckpointDetailFixture,
  streamCheckpointHistoryFixture,
  verifiedEarliestActivityAnchorFixture,
} from "./test/walletCaseStreamCheckpointFixtures";
import {
  parseWalletCaseBackfillOutcomeHistory,
  parseWalletCaseBackfillOutcome,
  parseWalletCaseBackfillProgress,
  parseWalletCaseBackfillSchedule,
  parseWalletCaseCheckpointContinuationReceipt,
  parseWalletCaseCheckpointContinuationPlan,
  parseWalletCaseCompleteHistoryGate,
  parseWalletCaseEarliestActivityAnchor,
  parseWalletCaseObservedHistoryFloor,
  parseWalletCaseStreamCheckpointCatalog,
  parseWalletCaseStreamCheckpointChain,
  parseWalletCaseStreamCheckpointDetail,
  parseWalletCaseStreamCheckpointHistory,
  serializeWalletCaseBackfillProgress,
  serializeWalletCaseBackfillOutcomeHistory,
  serializeWalletCaseBackfillOutcome,
  serializeWalletCaseBackfillSchedule,
  serializeWalletCaseCheckpointContinuationReceipt,
  serializeWalletCaseCheckpointContinuationPlan,
  serializeWalletCaseCompleteHistoryGate,
  serializeWalletCaseEarliestActivityAnchor,
  serializeWalletCaseObservedHistoryFloor,
  serializeWalletCaseStreamCheckpointChain,
} from "./walletCaseStreamCheckpoint";

describe("Wallet Case stream checkpoint contracts", () => {
  it("accepts a content-addressed resume-ready checkpoint catalog", () => {
    const fixture = streamCheckpointCatalogFixture();

    expect(parseWalletCaseStreamCheckpointCatalog(fixture)).toEqual(fixture);
  });

  it("accepts a checkpoint emitted by a prior resume acquisition", () => {
    const fixture = streamCheckpointCatalogFixture();
    const resumed = {
      ...fixture,
      checkpoints: [{
        ...fixture.checkpoints[0],
        document: {
          ...fixture.checkpoints[0].document,
          acquisition_mode: "resume" as const,
        },
      }],
    };

    expect(parseWalletCaseStreamCheckpointCatalog(resumed)).toEqual(resumed);
  });

  it("rejects identity, state, count, and shape contradictions", () => {
    const fixture = streamCheckpointCatalogFixture();
    expect(() => parseWalletCaseStreamCheckpointCatalog({
      ...fixture,
      checkpoints: [{
        ...fixture.checkpoints[0],
        checkpoint: {
          ...fixture.checkpoints[0].checkpoint,
          public_id: `scp_${"0".repeat(64)}`,
        },
      }],
    })).toThrow(/identity/);
    expect(() => parseWalletCaseStreamCheckpointCatalog({
      ...fixture,
      ready_count: 0,
      complete_count: 1,
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseStreamCheckpointCatalog({
      ...fixture,
      checkpoints: [{
        ...fixture.checkpoints[0],
        document: {
          ...fixture.checkpoints[0].document,
          continuation_cursor: null,
        },
      }],
    })).toThrow(/continuation state/);
    expect(() => parseWalletCaseStreamCheckpointCatalog({
      ...fixture,
      unexpected: true,
    })).toThrow(/shape/);
  });

  it("accepts exact detail and a strictly coherent frozen history page", () => {
    const detail = streamCheckpointDetailFixture();
    const history = streamCheckpointHistoryFixture();

    expect(parseWalletCaseStreamCheckpointDetail(detail)).toEqual(detail);
    expect(parseWalletCaseStreamCheckpointHistory(history)).toEqual(history);
  });

  it("rejects contradictory lineage and history pagination", () => {
    const detail = streamCheckpointDetailFixture();
    expect(() => parseWalletCaseStreamCheckpointDetail({
      ...detail,
      lineage: {
        ...detail.lineage,
        acquisition_mode: "resume",
        base_snapshot_public_id: detail.document.source_sync_public_id,
        parent_checkpoint_public_id: detail.checkpoint.public_id,
        chain_depth: 1,
      },
    })).toThrow(/does not match/);

    const history = streamCheckpointHistoryFixture();
    expect(() => parseWalletCaseStreamCheckpointHistory({
      ...history,
      aggregate: { ...history.aggregate, returned_count: 0 },
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseStreamCheckpointHistory({
      ...history,
      page: { ...history.page, next_cursor: null },
    })).toThrow(/inconsistent/);
  });

  it("accepts and exports a strictly linked checkpoint chain", () => {
    const chain = streamCheckpointChainFixture();

    expect(parseWalletCaseStreamCheckpointChain(chain)).toEqual(chain);
    expect(JSON.parse(serializeWalletCaseStreamCheckpointChain(chain))).toEqual(chain);
  });

  it("rejects checkpoint chain identity, aggregates, and parent drift", () => {
    const chain = streamCheckpointChainFixture();
    expect(() => parseWalletCaseStreamCheckpointChain({
      ...chain,
      chain: { ...chain.chain, public_id: `cch_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseStreamCheckpointChain({
      ...chain,
      document: {
        ...chain.document,
        aggregate: { ...chain.document.aggregate, page_count: 3 },
      },
    })).toThrow(/aggregate/);
    expect(() => parseWalletCaseStreamCheckpointChain({
      ...chain,
      document: {
        ...chain.document,
        revisions: chain.document.revisions.map((revision, index) => (
          index === 1
            ? { ...revision, parent_checkpoint_public_id: revision.checkpoint.public_id }
            : revision
        )),
      },
    })).toThrow(/parent lineage/);
  });

  it("accepts and exports verified backfill progress", () => {
    const progress = backfillProgressFixture();

    expect(parseWalletCaseBackfillProgress(progress)).toEqual(progress);
    expect(JSON.parse(serializeWalletCaseBackfillProgress(progress))).toEqual(progress);
  });

  it("rejects backfill identity, aggregate, and frontier drift", () => {
    const progress = backfillProgressFixture();
    expect(() => parseWalletCaseBackfillProgress({
      ...progress,
      progress: { ...progress.progress, public_id: `bfp_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseBackfillProgress({
      ...progress,
      document: {
        ...progress.document,
        aggregate: { ...progress.document.aggregate, page_count: 1 },
      },
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseBackfillProgress({
      ...progress,
      document: {
        ...progress.document,
        streams: progress.document.streams.map((stream) => ({
          ...stream,
          frontier_advanced: false,
        })),
      },
    })).toThrow(/stream 0 is inconsistent/);
  });

  it("accepts and exports a verified observed history floor", () => {
    const floor = observedHistoryFloorFixture();

    expect(parseWalletCaseObservedHistoryFloor(floor)).toEqual(floor);
    expect(JSON.parse(serializeWalletCaseObservedHistoryFloor(floor))).toEqual(floor);
  });

  it("rejects observed floor identity, page, state, and summary drift", () => {
    const floor = observedHistoryFloorFixture();
    expect(() => parseWalletCaseObservedHistoryFloor({
      ...floor,
      floor: { ...floor.floor, public_id: `ohf_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseObservedHistoryFloor({
      ...floor,
      document: {
        ...floor.document,
        streams: floor.document.streams.map((stream) => ({
          ...stream,
          floor_page: { ...stream.floor_page!, page_index: 99 },
        })),
      },
    })).toThrow(/stream 0 is inconsistent/);
    expect(() => parseWalletCaseObservedHistoryFloor({
      ...floor,
      document: { ...floor.document, state: "provider_terminal_observed" },
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseObservedHistoryFloor({
      ...floor,
      document: {
        ...floor.document,
        summary: { ...floor.document.summary, timestamped_stream_count: 0 },
      },
    })).toThrow(/inconsistent/);
  });

  it("accepts an empty observed history floor without inventing time", () => {
    const fixture = observedHistoryFloorFixture();
    const progress = backfillProgressFixture();
    const emptyProgress = {
      progress: {
        ...progress.progress,
        public_id: `bfp_${"6a".repeat(32)}`,
        content_hash_sha256: "6a".repeat(32),
        checkpoint_cutoff_public_id: null,
        stream_count: 0,
        ready_count: 0,
        revision_count: 0,
        continuation_revision_count: 0,
        page_count: 0,
        pages_succeeded: 0,
        continuation_page_count: 0,
        continuation_pages_succeeded: 0,
        observed_frontier_count: 0,
        advanced_frontier_count: 0,
      },
      document: {
        ...progress.document,
        checkpoint_cutoff_public_id: null,
        aggregate: {
          stream_count: 0,
          ready_count: 0,
          complete_count: 0,
          blocked_count: 0,
          revision_count: 0,
          continuation_revision_count: 0,
          page_count: 0,
          pages_succeeded: 0,
          continuation_page_count: 0,
          continuation_pages_succeeded: 0,
          observed_frontier_count: 0,
          advanced_frontier_count: 0,
        },
        streams: [],
      },
    };
    const emptySummary = {
      stream_count: 0,
      observed_stream_count: 0,
      timestamped_stream_count: 0,
      provider_terminal_stream_count: 0,
      earliest_observed_timestamp: null,
      state: "empty" as const,
      earliest_wallet_activity_established: false as const,
    };
    const empty = {
      floor: {
        ...fixture.floor,
        public_id: `ohf_${"6b".repeat(32)}`,
        content_hash_sha256: "6b".repeat(32),
        input_progress_public_id: emptyProgress.progress.public_id,
        checkpoint_cutoff_public_id: null,
        ...emptySummary,
      },
      document: {
        ...fixture.document,
        input_progress: emptyProgress,
        state: "empty" as const,
        streams: [],
        summary: emptySummary,
      },
    };

    expect(parseWalletCaseObservedHistoryFloor(empty)).toEqual(empty);
  });

  it("accepts and exports a fail-closed earliest activity anchor", () => {
    const anchor = earliestActivityAnchorFixture();

    expect(parseWalletCaseEarliestActivityAnchor(anchor)).toEqual(anchor);
    expect(JSON.parse(serializeWalletCaseEarliestActivityAnchor(anchor))).toEqual(anchor);
  });

  it("accepts a canonical zero-predecessor earliest activity proof", () => {
    const anchor = verifiedEarliestActivityAnchorFixture();

    expect(parseWalletCaseEarliestActivityAnchor(anchor)).toEqual(anchor);
  });

  it("rejects earliest anchor identity, trust, predecessor, and summary drift", () => {
    const anchor = earliestActivityAnchorFixture();
    expect(() => parseWalletCaseEarliestActivityAnchor({
      ...anchor,
      anchor: { ...anchor.anchor, public_id: `eaa_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseEarliestActivityAnchor({
      ...anchor,
      document: {
        ...anchor.document,
        summary: {
          ...anchor.document.summary,
          earliest_wallet_activity_established: true,
        },
      },
    })).toThrow(/inconsistent/);
    const candidate = {
      snapshot_public_id: "550e8400-e29b-41d4-a716-446655440001",
      activity_public_id: `act_${"12".repeat(32)}`,
      occurred_at: "2026-09-06T12:00:00Z",
      logical_time: "20",
      transaction_hash: "ab".repeat(32),
      provider: "tonapi",
    };
    const proof = {
      evidence_public_id: "550e8400-e29b-41d4-a716-446655440002",
      verification_digest_sha256: "21".repeat(32),
      inclusion_catalog_digest_sha256: "22".repeat(32),
      selected_proof_digest_sha256: "23".repeat(32),
      network: "ton-mainnet",
      verifier_policy_id: "ton_liteserver_checkpoint_strict_2026_08_v2",
      trust_level: 0,
      trusted_checkpoint: {
        workchain: -1,
        shard: "-9223372036854775808",
        seqno: 1,
        root_hash: "31".repeat(32),
        file_hash: "32".repeat(32),
      },
      block: {
        workchain: 0,
        shard: "-9223372036854775808",
        seqno: 2,
        root_hash: "33".repeat(32),
        file_hash: "34".repeat(32),
      },
      transaction_boc_sha256: "35".repeat(32),
      account_address_canonical: anchor.document.wallet_account_canonical,
      logical_time: "20",
      transaction_hash: "ab".repeat(32),
      predecessor: {
        logical_time: "0",
        transaction_hash: "0".repeat(64),
        absent: false,
      },
      block_merkle_proof_verified: true,
      canonical_block_chain_verified_at_capture: true,
      provider_free_revalidated: true,
    };
    expect(() => parseWalletCaseEarliestActivityAnchor({
      ...anchor,
      document: {
        ...anchor.document,
        data_environment: "live",
        candidate,
        proof,
      },
    })).toThrow(/predecessor/);
  });

  it("accepts and exports a fail-closed complete-history gate", () => {
    const gate = completeHistoryGateFixture();

    expect(parseWalletCaseCompleteHistoryGate(gate)).toEqual(gate);
    expect(JSON.parse(serializeWalletCaseCompleteHistoryGate(gate))).toEqual(gate);
  });

  it("rejects complete-history identity, status, summary, and case drift", () => {
    const gate = completeHistoryGateFixture();
    expect(() => parseWalletCaseCompleteHistoryGate({
      ...gate,
      gate: { ...gate.gate, public_id: `chg_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseCompleteHistoryGate({
      ...gate,
      document: {
        ...gate.document,
        checks: gate.document.checks.map((check, index) => (
          index === 1 ? { ...check, status: "unmet" } : check
        )),
      },
    })).toThrow(/check 1 is inconsistent/);
    expect(() => parseWalletCaseCompleteHistoryGate({
      ...gate,
      document: {
        ...gate.document,
        summary: { ...gate.document.summary, satisfied_check_count: 2 },
      },
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseCompleteHistoryGate({
      ...gate,
      document: {
        ...gate.document,
        case_public_id: "550e8400-e29b-41d4-b716-446655440002",
      },
    })).toThrow(/inconsistent/);
  });

  it("accepts and exports a finite content-addressed backfill schedule", () => {
    const schedule = backfillScheduleFixture();

    expect(parseWalletCaseBackfillSchedule(schedule)).toEqual(schedule);
    expect(JSON.parse(serializeWalletCaseBackfillSchedule(schedule))).toEqual(schedule);
  });

  it("rejects backfill schedule identity, budget, selection, and state drift", () => {
    const schedule = backfillScheduleFixture();
    expect(() => parseWalletCaseBackfillSchedule({
      ...schedule,
      schedule: { ...schedule.schedule, public_id: `bfs_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseBackfillSchedule({
      ...schedule,
      document: { ...schedule.document, page_budget: 11 },
    })).toThrow(/page budget/);
    expect(() => parseWalletCaseBackfillSchedule({
      ...schedule,
      document: { ...schedule.document, selection: null },
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseBackfillSchedule({
      ...schedule,
      document: {
        ...schedule.document,
        state: "backpressured",
        active_sync_public_id: null,
        selection: null,
      },
    })).toThrow(/inconsistent/);
  });

  it("accepts and exports a verified scheduled backfill outcome", () => {
    const outcome = backfillOutcomeFixture();

    expect(parseWalletCaseBackfillOutcome(outcome)).toEqual(outcome);
    expect(JSON.parse(serializeWalletCaseBackfillOutcome(outcome))).toEqual(outcome);
  });

  it("rejects backfill outcome identity, receipt, progress, and delta drift", () => {
    const outcome = backfillOutcomeFixture();
    expect(() => parseWalletCaseBackfillOutcome({
      ...outcome,
      outcome: { ...outcome.outcome, public_id: `bfo_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseBackfillOutcome({
      ...outcome,
      document: {
        ...outcome.document,
        continuation_receipt: {
          ...outcome.document.continuation_receipt,
          receipt: {
            ...outcome.document.continuation_receipt.receipt,
            input_schedule_public_id: `bfs_${"0".repeat(64)}`,
          },
        },
      },
    })).toThrow(/transition is inconsistent/);
    expect(() => parseWalletCaseBackfillOutcome({
      ...outcome,
      document: {
        ...outcome.document,
        output_progress: {
          ...outcome.document.output_progress,
          progress: {
            ...outcome.document.output_progress.progress,
            pages_succeeded: 2,
          },
        },
      },
    })).toThrow(/backfill progress is inconsistent/);
    expect(() => parseWalletCaseBackfillOutcome({
      ...outcome,
      document: {
        ...outcome.document,
        transition: {
          ...outcome.document.transition,
          page_count_delta: 0,
        },
      },
    })).toThrow(/inconsistent/);
  });

  it("accepts and exports a frozen Backfill Outcome history page", () => {
    const history = backfillOutcomeHistoryFixture();

    expect(parseWalletCaseBackfillOutcomeHistory(history)).toEqual(history);
    expect(JSON.parse(serializeWalletCaseBackfillOutcomeHistory(history))).toEqual(history);
  });

  it("rejects Backfill Outcome history scope, duplicates, and delta drift", () => {
    const history = backfillOutcomeHistoryFixture();
    expect(() => parseWalletCaseBackfillOutcomeHistory({
      ...history,
      sync_cutoff_public_id: null,
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseBackfillOutcomeHistory({
      ...history,
      items: [history.items[0], history.items[0]],
      aggregate: { total_outcomes: 2, returned_count: 2 },
      page: { limit: 2, has_more: false, next_cursor: null },
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseBackfillOutcomeHistory({
      ...history,
      items: [{
        ...history.items[0],
        after_continuation_pages_succeeded: 3,
      }],
    })).toThrow(/item 0 is inconsistent/);
    expect(() => parseWalletCaseBackfillOutcomeHistory({
      ...history,
      aggregate: { total_outcomes: 2, returned_count: 1 },
      page: { limit: 1, has_more: false, next_cursor: "unsigned" },
    })).toThrow(/inconsistent/);
  });

  it("accepts and exports a strictly aggregated continuation plan", () => {
    const plan = checkpointContinuationPlanFixture();

    expect(parseWalletCaseCheckpointContinuationPlan(plan)).toEqual(plan);
    expect(JSON.parse(serializeWalletCaseCheckpointContinuationPlan(plan))).toEqual(plan);
  });

  it("rejects continuation plan identity, totals, state, and chain drift", () => {
    const plan = checkpointContinuationPlanFixture();
    expect(() => parseWalletCaseCheckpointContinuationPlan({
      ...plan,
      plan: { ...plan.plan, public_id: `cpl_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseCheckpointContinuationPlan({
      ...plan,
      document: {
        ...plan.document,
        aggregate: { ...plan.document.aggregate, revision_count: 1 },
      },
    })).toThrow(/inconsistent/);
    expect(() => parseWalletCaseCheckpointContinuationPlan({
      ...plan,
      document: {
        ...plan.document,
        streams: plan.document.streams.map((stream) => ({
          ...stream,
          next_page_index: null,
        })),
      },
    })).toThrow(/stream 0 is inconsistent/);
    expect(() => parseWalletCaseCheckpointContinuationPlan({
      ...plan,
      document: {
        ...plan.document,
        streams: plan.document.streams.map((stream) => ({
          ...stream,
          chain_public_id: `cch_${"0".repeat(64)}`,
        })),
      },
    })).toThrow(/stream 0 is inconsistent/);
  });

  it("accepts and exports a strictly linked continuation receipt", () => {
    const receipt = checkpointContinuationReceiptFixture();

    expect(parseWalletCaseCheckpointContinuationReceipt(receipt)).toEqual(receipt);
    expect(JSON.parse(
      serializeWalletCaseCheckpointContinuationReceipt(receipt),
    )).toEqual(receipt);
  });

  it("rejects continuation receipt identity, deltas, and plan drift", () => {
    const receipt = checkpointContinuationReceiptFixture();
    expect(() => parseWalletCaseCheckpointContinuationReceipt({
      ...receipt,
      receipt: { ...receipt.receipt, public_id: `ctr_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseCheckpointContinuationReceipt({
      ...receipt,
      document: {
        ...receipt.document,
        transition: { ...receipt.document.transition, page_count_delta: 0 },
      },
    })).toThrow(/transition is inconsistent/);
    expect(() => parseWalletCaseCheckpointContinuationReceipt({
      ...receipt,
      document: {
        ...receipt.document,
        after_plan: {
          ...receipt.document.after_plan,
          document: {
            ...receipt.document.after_plan.document,
            streams: receipt.document.after_plan.document.streams.map((stream) => ({
              ...stream,
              tip_checkpoint: receipt.document.input.checkpoint,
            })),
          },
        },
      },
    })).toThrow(/continuation plan is inconsistent/);
  });

  it("accepts budget accounting and rejects a forged v2 remainder", () => {
    const receipt = checkpointContinuationReceiptV2Fixture();

    expect(parseWalletCaseCheckpointContinuationReceipt(receipt)).toEqual(receipt);
    expect(JSON.parse(
      serializeWalletCaseCheckpointContinuationReceipt(receipt),
    )).toEqual(receipt);
    expect(() => parseWalletCaseCheckpointContinuationReceipt({
      ...receipt,
      document: {
        ...receipt.document,
        transition: {
          ...receipt.document.transition,
          page_budget_remaining: 1,
        },
      },
    })).toThrow(/transition is inconsistent/);
  });

  it("binds a scheduled receipt v3 to its exact backfill schedule", () => {
    const receipt = checkpointContinuationReceiptV3Fixture();

    expect(parseWalletCaseCheckpointContinuationReceipt(receipt)).toEqual(receipt);
    expect(JSON.parse(
      serializeWalletCaseCheckpointContinuationReceipt(receipt),
    )).toEqual(receipt);
    expect(() => parseWalletCaseCheckpointContinuationReceipt({
      ...receipt,
      receipt: {
        ...receipt.receipt,
        input_schedule_public_id: `bfs_${"0".repeat(64)}`,
      },
    })).toThrow(/transition is inconsistent/);
  });
});
