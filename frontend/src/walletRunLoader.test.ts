import { describe, expect, it } from "vitest";

import type { WalletIngestionRunResponse } from "./types";
import {
  parseStoredRunId,
  requestSignature,
  restoreStoredRunControls,
} from "./walletRunLoader";

function storedRun(
  overrides: Partial<WalletIngestionRunResponse> = {},
): WalletIngestionRunResponse {
  return {
    run_id: 25,
    wallet_address: "EQstored",
    wallet_identity: {
      status: "unavailable",
      version: "unavailable",
      network: "ton-unknown",
      canonical_address: null,
      workchain_id: null,
      account_id_hex: null,
      submitted_format: "unrecognized",
      bounceable: null,
      testnet_only: null,
      is_account_existence_proof: false,
      is_ownership_proof: false,
    },
    time_window: "24h",
    custom_start: null,
    custom_end: null,
    created_at: "2026-07-10T00:00:00Z",
    status: "success",
    data_mode: "real",
    requested_surfaces: ["transactions"],
    provider_evidence: [],
    unavailable_surfaces: [],
    incomplete_surfaces: [],
    acquisition_streams: [],
    transfers: [],
    transactions: [],
    swaps: [],
    balances: [],
    warnings: [],
    message: "Stored run",
    ...overrides,
  };
}

describe("parseStoredRunId", () => {
  it("accepts only positive safe decimal integers", () => {
    expect(parseStoredRunId("25")).toBe(25);
    expect(parseStoredRunId(" 25 ")).toBe(25);
    expect(parseStoredRunId(String(Number.MAX_SAFE_INTEGER))).toBe(
      Number.MAX_SAFE_INTEGER,
    );
  });

  it.each([
    "",
    "0",
    "-1",
    "+1",
    "01",
    "1.0",
    "1e3",
    "true",
    "9007199254740992",
  ])("rejects noncanonical or unsafe value %s", (value) => {
    expect(parseStoredRunId(value)).toBeNull();
  });
});

describe("restoreStoredRunControls", () => {
  it("restores rolling scope without inventing custom bounds", () => {
    expect(restoreStoredRunControls(storedRun(), 25)).toEqual({
      walletAddress: "EQstored",
      timeWindow: "24h",
      customStart: "",
      customEnd: "",
      canonicalCustomStart: "",
      canonicalCustomEnd: "",
      surfaces: ["transactions"],
    });
  });

  it("keeps a custom run instant-equivalent and fresh after hydration", () => {
    const result = storedRun({
      time_window: "custom",
      custom_start: "2026-06-01T00:00:00Z",
      custom_end: "2026-06-02T00:00:00Z",
      requested_surfaces: ["transactions", "swaps"],
    });
    const restored = restoreStoredRunControls(result, 25);

    expect(
      requestSignature(
        restored.walletAddress,
        restored.timeWindow,
        restored.canonicalCustomStart,
        restored.canonicalCustomEnd,
        restored.surfaces,
      ),
    ).toBe(
      requestSignature(
        result.wallet_address,
        "custom",
        result.custom_start ?? "",
        result.custom_end ?? "",
        result.requested_surfaces,
      ),
    );
  });

  it("preserves canonical DST-fold and microsecond bounds without rounding", () => {
    const result = storedRun({
      time_window: "custom",
      custom_start: "2026-10-25T01:30:00.123456Z",
      custom_end: "2026-10-25T02:30:00.654321Z",
    });

    const restored = restoreStoredRunControls(result, 25);

    expect(restored.canonicalCustomStart).toBe("2026-10-25T01:30:00.123456Z");
    expect(restored.canonicalCustomEnd).toBe("2026-10-25T02:30:00.654321Z");
    expect(
      requestSignature(
        restored.walletAddress,
        restored.timeWindow,
        restored.canonicalCustomStart,
        restored.canonicalCustomEnd,
        restored.surfaces,
      ),
    ).toContain("2026-10-25T01:30:00.123456Z");
  });

  it("rejects mismatched identity and malformed persisted scope", () => {
    expect(() => restoreStoredRunControls(storedRun(), 24)).toThrow(
      "did not match",
    );
    expect(() =>
      restoreStoredRunControls(
        storedRun({
          time_window: "custom",
          custom_start: null,
          custom_end: null,
        }),
        25,
      ),
    ).toThrow("missing its exact time bounds");
    expect(() =>
      restoreStoredRunControls(
        storedRun({ requested_surfaces: ["transactions", "transactions"] }),
        25,
      ),
    ).toThrow("invalid requested-surface metadata");
  });
});
