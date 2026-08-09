import { describe, expect, it } from "vitest";

import type { WalletClusterCompareResponse, WalletSignalsRecord } from "./types";
import { validateWalletClusterComparison } from "./walletClusterComparison";

function wallet(runId: number, address: string): WalletSignalsRecord {
  return {
    run_id: runId,
    wallet_address: address,
    data_mode: "mock",
    ton_balance: "238.75",
    portfolio_value_usd: "950.42",
    distinct_tokens_touched: ["JETTON_ALPHA", "JETTON_BETA"],
    buy_swap_count: 1,
    sell_swap_count: 0,
    avg_ton_per_buy_swap: "15",
    first_buy_at: "2026-06-01T10:35:00Z",
    signal_basis: "legacy_mock_fixture",
    canonical_ledger_digest_sha256: null,
    canonical_activity_count: 0,
    incoming_activity_count: 0,
    outgoing_activity_count: 0,
    counterparties: [],
    warnings: [],
  };
}

function response(): WalletClusterCompareResponse {
  return {
    wallets: [wallet(1, "UQwallet-one"), wallet(2, "UQwallet-two")],
    comparison_window_seconds: 86_400,
    pairs: [{
      wallet_a_run_id: 1,
      wallet_b_run_id: 2,
      wallet_a_address: "UQwallet-one",
      wallet_b_address: "UQwallet-two",
      score: 100,
      band: "very high similarity, still not proof",
      shared_tokens: ["JETTON_ALPHA", "JETTON_BETA"],
      shared_counterparties: [],
      note: "Very similar behavior, but not proof of common ownership.",
    }],
    is_cluster_proof: false,
    signal_basis: "legacy_mock_fixture",
    note: "Probabilistic behavioral similarity only, not proof of common ownership.",
  };
}

describe("validateWalletClusterComparison", () => {
  it("accepts a complete pairwise mock comparison", () => {
    const value = response();
    expect(validateWalletClusterComparison(value, [1, 2])).toEqual(value);
  });

  it("accepts a canonical real comparison with signed net TON flow", () => {
    const value = response();
    value.signal_basis = "canonical_native_activity_ledger";
    value.wallets.forEach((row, index) => {
      row.data_mode = "real";
      row.signal_basis = "canonical_native_activity_ledger";
      row.ton_balance = index ? "-0.25" : "1.5";
      row.portfolio_value_usd = null;
      row.avg_ton_per_buy_swap = null;
      row.canonical_ledger_digest_sha256 = `${index + 1}`.repeat(64);
      row.canonical_activity_count = 3;
      row.incoming_activity_count = 1;
      row.outgoing_activity_count = 2;
      row.counterparties = [`0:${"a".repeat(64)}`];
    });
    value.pairs[0].shared_counterparties = [`0:${"a".repeat(64)}`];
    expect(validateWalletClusterComparison(value, [2, 1]).signal_basis).toBe(
      "canonical_native_activity_ledger",
    );
  });

  it("rejects proof claims, wrong score bands and incomplete pair sets", () => {
    const proof = response();
    proof.is_cluster_proof = true;
    expect(() => validateWalletClusterComparison(proof, [1, 2])).toThrow();

    const band = response();
    band.pairs[0].band = "weak similarity";
    expect(() => validateWalletClusterComparison(band, [1, 2])).toThrow();

    const missing = response();
    missing.pairs = [];
    expect(() => validateWalletClusterComparison(missing, [1, 2])).toThrow();
  });
});
