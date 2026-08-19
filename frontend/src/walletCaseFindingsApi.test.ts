import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "./apiBase";
import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";
import { walletCaseFindingsFixture } from "./test/walletCaseFindingsFixtures";
import { getWalletCaseFindings, WalletCaseFindingsApiError } from "./walletCaseFindingsApi";

afterEach(() => vi.unstubAllGlobals());

describe("Wallet Case Findings API", () => {
  it("sends an exact no-store pinned request", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(walletCaseFindingsFixture()), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();
    const result = await getWalletCaseFindings(CASE_ID, SYNC_ID, controller.signal);
    expect(result.snapshot_public_id).toBe(SYNC_ID);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/findings?snapshot=${SYNC_ID}`,
      { cache: "no-store", signal: controller.signal },
    );
  });

  it("requests the latest usable snapshot when no pin exists", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(walletCaseFindingsFixture()), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await getWalletCaseFindings(CASE_ID, null);
    expect(fetchMock.mock.calls[0][0]).toBe(`${API_BASE}/api/v1/cases/${CASE_ID}/findings`);
  });

  it("rejects invalid scope before fetch and response scope drift after fetch", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(getWalletCaseFindings("bad", null)).rejects.toThrow(/canonical UUIDv4/);
    expect(fetchMock).not.toHaveBeenCalled();

    const drift = walletCaseFindingsFixture();
    drift.case_public_id = "00000000-0000-4000-8000-000000000099";
    fetchMock.mockResolvedValue(new Response(JSON.stringify(drift), { status: 200 }));
    await expect(getWalletCaseFindings(CASE_ID, SYNC_ID)).rejects.toThrow(/scope/);
  });

  it("parses typed safe errors and ignores untrusted extras", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: {
        code: "case_findings_storage_unavailable",
        message_safe: "Findings storage is unavailable.",
        retryable: true,
        raw_sql: "secret",
      },
    }), { status: 503 })));
    const error = await getWalletCaseFindings(CASE_ID, SYNC_ID).catch((caught) => caught);
    expect(error).toBeInstanceOf(WalletCaseFindingsApiError);
    expect(error).toMatchObject({ status: 503, code: "case_findings_storage_unavailable", retryable: true });
    expect((error as Error).message).toBe("Findings storage is unavailable.");
  });
});
