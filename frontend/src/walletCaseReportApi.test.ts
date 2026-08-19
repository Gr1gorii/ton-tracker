import { afterEach, describe, expect, it, vi } from "vitest";

import { API_BASE } from "./apiBase";
import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";
import { walletCaseReportFixture } from "./test/walletCaseReportFixtures";
import {
  getWalletCaseReport,
  walletCaseReportExportUrl,
  WalletCaseReportApiError,
} from "./walletCaseReportApi";

afterEach(() => vi.unstubAllGlobals());

describe("Wallet Case report API", () => {
  it("loads a pinned no-store report and binds the response scope", async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(walletCaseReportFixture()));
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(getWalletCaseReport(CASE_ID, SYNC_ID, controller.signal)).resolves.toEqual(walletCaseReportFixture());
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/report?snapshot=${SYNC_ID}`,
      { cache: "no-store", signal: controller.signal },
    );
    expect(walletCaseReportExportUrl(CASE_ID, SYNC_ID)).toBe(
      `${API_BASE}/api/v1/cases/${CASE_ID}/report/export.json?snapshot=${SYNC_ID}`,
    );
  });

  it("rejects invalid IDs before fetch and scope drift after parsing", async () => {
    const drift = structuredClone(walletCaseReportFixture());
    drift.case_public_id = "550e8400-e29b-41d4-a716-446655440099";
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(drift));
    vi.stubGlobal("fetch", fetchMock);

    await expect(getWalletCaseReport("bad", SYNC_ID)).rejects.toThrow(/UUIDv4/);
    expect(fetchMock).not.toHaveBeenCalled();
    await expect(getWalletCaseReport(CASE_ID, SYNC_ID)).rejects.toThrow(/scope/);
  });

  it("preserves safe typed API errors", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: { code: "case_report_conflict", message_safe: "Report scope changed.", retryable: false },
    }, 409)));
    await expect(getWalletCaseReport(CASE_ID, SYNC_ID)).rejects.toEqual(expect.objectContaining<Partial<WalletCaseReportApiError>>({
      status: 409,
      code: "case_report_conflict",
      retryable: false,
      message: "Report scope changed.",
    }));
  });
});

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), { status, headers: { "Content-Type": "application/json" } });
}
