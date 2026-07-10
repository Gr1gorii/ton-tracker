import { describe, expect, it } from "vitest";

import { validateWalletRunCatalogResponse } from "./walletRunCatalog";

function catalogItem(runId: string) {
  return {
    run_id: runId,
    wallet_hint: "EQwall…llet",
    time_window: "24h",
    created_at: "2026-07-10T00:00:00Z",
    status: "success",
    data_mode: "real",
  };
}

describe("validateWalletRunCatalogResponse", () => {
  it("accepts exact canonical string IDs through signed int64", () => {
    const response = validateWalletRunCatalogResponse(
      {
        runs: [
          catalogItem("9223372036854775807"),
          catalogItem("9007199254740991"),
        ],
        limit: 2,
        truncated: true,
      },
      2,
    );

    expect(response.runs.map((run) => run.run_id)).toEqual([
      "9223372036854775807",
      "9007199254740991",
    ]);
  });

  it.each([
    ["leading zero", { ...catalogItem("9"), run_id: "09" }],
    ["int64 overflow", catalogItem("9223372036854775808")],
    ["invalid date", { ...catalogItem("9"), created_at: "not-a-date" }],
    ["long wallet hint", { ...catalogItem("9"), wallet_hint: "x".repeat(12) }],
    ["unmasked short wallet", { ...catalogItem("9"), wallet_hint: "EQshort" }],
  ])("rejects %s metadata", (_label, item) => {
    expect(() =>
      validateWalletRunCatalogResponse(
        { runs: [item], limit: 1, truncated: false },
        1,
      ),
    ).toThrow();
  });

  it("rejects out-of-order, duplicate, and incomplete truncated pages", () => {
    expect(() =>
      validateWalletRunCatalogResponse(
        {
          runs: [catalogItem("8"), catalogItem("9")],
          limit: 2,
          truncated: true,
        },
        2,
      ),
    ).toThrow("newest-first");
    expect(() =>
      validateWalletRunCatalogResponse(
        {
          runs: [catalogItem("9"), catalogItem("9")],
          limit: 2,
          truncated: true,
        },
        2,
      ),
    ).toThrow("newest-first");
    expect(() =>
      validateWalletRunCatalogResponse(
        {
          runs: [catalogItem("9")],
          limit: 2,
          truncated: true,
        },
        2,
      ),
    ).toThrow("page metadata");
  });

  it("rejects unexpected privacy-expanding fields", () => {
    expect(() =>
      validateWalletRunCatalogResponse(
        {
          runs: [
            {
              ...catalogItem("9"),
              wallet_address: "EQfull-address-must-not-be-listed",
            },
          ],
          limit: 1,
          truncated: false,
        },
        1,
      ),
    ).toThrow("unexpected shape");
  });

  it("requires the server to echo the requested limit", () => {
    expect(() =>
      validateWalletRunCatalogResponse(
        { runs: [], limit: 7, truncated: false },
        8,
      ),
    ).toThrow("page metadata");
  });
});
