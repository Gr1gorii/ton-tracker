import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE, getWalletCanonicalReportAvailability } from "./api";

describe("getWalletCanonicalReportAvailability", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("marks a canonical report as ready only after the endpoint succeeds", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ contract_version: "canonical_wallet_report_v1" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCanonicalReportAvailability(64)).resolves.toEqual({
      available: true,
      message: "Canonical ledger and report are ready for export.",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/64/canonical-report`,
      { cache: "no-store" },
    );
  });

  it("returns the backend reason when immutable ledger evidence is absent", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "No immutable native activity ledgers exist for this run." }), {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCanonicalReportAvailability(64)).resolves.toEqual({
      available: false,
      message: "No immutable native activity ledgers exist for this run.",
    });
  });
});
