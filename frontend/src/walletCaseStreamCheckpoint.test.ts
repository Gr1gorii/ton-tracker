import { describe, expect, it } from "vitest";

import {
  streamCheckpointCatalogFixture,
  streamCheckpointDetailFixture,
  streamCheckpointHistoryFixture,
} from "./test/walletCaseStreamCheckpointFixtures";
import {
  parseWalletCaseStreamCheckpointCatalog,
  parseWalletCaseStreamCheckpointDetail,
  parseWalletCaseStreamCheckpointHistory,
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
});
