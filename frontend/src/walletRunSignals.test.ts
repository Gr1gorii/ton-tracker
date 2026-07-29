import { describe, expect, it } from "vitest";

import type { WalletRunSignalsResponse } from "./types";
import {
  validateWalletRunSignalsResponse,
  WALLET_SIGNAL_CODES,
} from "./walletRunSignals";

const WALLET = "UQwallet-under-test";

function response(): WalletRunSignalsResponse {
  return {
    run_id: 25,
    wallet_address: WALLET,
    is_risk_score: false,
    evaluated: [...WALLET_SIGNAL_CODES],
    signals: [{
      code: "failed_transaction_ratio",
      title: "Elevated failed-transaction ratio",
      confidence: "medium",
      observation: "3 of 10 transactions failed (30%).",
      evidence: { failed: 3, total: 10, share: 0.3 },
      note: "A heuristic indicator, not evidence of malicious activity.",
    }],
    insufficient_evidence: [{
      code: "burst_transaction_activity",
      reason: "Only 2 timestamped transactions were available.",
    }],
    note: "Evidence signals are heuristic indicators, not a risk score or verdict.",
  };
}

describe("validateWalletRunSignalsResponse", () => {
  it("accepts an exact run-bound explainable signal contract", () => {
    const value = response();
    expect(validateWalletRunSignalsResponse(value, 25, WALLET)).toEqual(value);
  });

  it("rejects a risk score or a mismatched run identity", () => {
    const scored = response();
    scored.is_risk_score = true;
    expect(() => validateWalletRunSignalsResponse(scored, 25, WALLET)).toThrow(
      "Wallet insight response is incoherent.",
    );
    expect(() => validateWalletRunSignalsResponse(response(), 26, WALLET)).toThrow(
      "Wallet insight response is incoherent.",
    );
    expect(() => validateWalletRunSignalsResponse(response(), 25, "UQother")).toThrow(
      "Wallet insight response is incoherent.",
    );
  });

  it("rejects duplicate, unknown and malformed evidence records", () => {
    const duplicate = response();
    duplicate.insufficient_evidence[0].code = "failed_transaction_ratio";
    expect(() => validateWalletRunSignalsResponse(duplicate, 25, WALLET)).toThrow();

    const unknown = response();
    unknown.signals[0].code = "opaque_wallet_score";
    expect(() => validateWalletRunSignalsResponse(unknown, 25, WALLET)).toThrow();

    const extra = response() as unknown as Record<string, unknown>;
    extra.score = 91;
    expect(() => validateWalletRunSignalsResponse(extra, 25, WALLET)).toThrow();
  });
});
