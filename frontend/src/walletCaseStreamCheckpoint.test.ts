import { describe, expect, it } from "vitest";

import {
  backfillProgressFixture,
  checkpointContinuationReceiptFixture,
  checkpointContinuationReceiptV2Fixture,
  checkpointContinuationPlanFixture,
  streamCheckpointCatalogFixture,
  streamCheckpointChainFixture,
  streamCheckpointDetailFixture,
  streamCheckpointHistoryFixture,
} from "./test/walletCaseStreamCheckpointFixtures";
import {
  parseWalletCaseBackfillProgress,
  parseWalletCaseCheckpointContinuationReceipt,
  parseWalletCaseCheckpointContinuationPlan,
  parseWalletCaseStreamCheckpointCatalog,
  parseWalletCaseStreamCheckpointChain,
  parseWalletCaseStreamCheckpointDetail,
  parseWalletCaseStreamCheckpointHistory,
  serializeWalletCaseBackfillProgress,
  serializeWalletCaseCheckpointContinuationReceipt,
  serializeWalletCaseCheckpointContinuationPlan,
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
});
