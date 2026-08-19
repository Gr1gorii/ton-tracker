// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";
import { walletCaseReportFixture } from "./test/walletCaseReportFixtures";
import {
  walletCaseReportRevisionCatalogFixture,
  walletCaseReportRevisionDetailFixture,
  walletCaseReportRevisionSummaryFixture,
} from "./test/walletCaseReportRevisionFixtures";
import { useWalletCaseReports } from "./useWalletCaseReports";

const api = vi.hoisted(() => ({
  getWalletCaseReport: vi.fn(),
  listWalletCaseReportRevisions: vi.fn(),
  getWalletCaseReportRevision: vi.fn(),
  captureWalletCaseReportRevision: vi.fn(),
}));
vi.mock("./walletCaseReportApi", () => api);

beforeEach(() => {
  vi.clearAllMocks();
  api.getWalletCaseReport.mockResolvedValue(walletCaseReportFixture());
  api.listWalletCaseReportRevisions.mockResolvedValue(walletCaseReportRevisionCatalogFixture());
  api.getWalletCaseReportRevision.mockResolvedValue(walletCaseReportRevisionDetailFixture());
  api.captureWalletCaseReportRevision.mockResolvedValue({ case_public_id: CASE_ID, created: true, revision: walletCaseReportRevisionSummaryFixture() });
});
afterEach(() => cleanup());

describe("useWalletCaseReports", () => {
  it("pins latest snapshot, loads catalog and exposes selected detail", async () => {
    const onSnapshotPinned = vi.fn();
    const onRevisionCaptured = vi.fn();
    const revision = walletCaseReportRevisionSummaryFixture();
    const { result, rerender } = renderHook(
      ({ snapshot, selected }) => useWalletCaseReports({
        caseId: CASE_ID,
        urlState: { snapshot, revision: selected },
        enabled: true,
        onSnapshotPinned,
        onRevisionCaptured,
      }),
      { initialProps: { snapshot: null as string | null, selected: null as string | null } },
    );
    await waitFor(() => expect(result.current.current?.snapshot_public_id).toBe(SYNC_ID));
    expect(onSnapshotPinned).toHaveBeenCalledWith(SYNC_ID);
    await waitFor(() => expect(result.current.catalog?.items).toHaveLength(1));

    rerender({ snapshot: SYNC_ID, selected: revision.public_id });
    await waitFor(() => expect(result.current.detail?.revision.public_id).toBe(revision.public_id));
    expect(api.getWalletCaseReportRevision).toHaveBeenCalledWith(CASE_ID, revision.public_id, expect.any(AbortSignal));
  });

  it("clears stale detail scope while a new revision request is pending", async () => {
    const first = walletCaseReportRevisionSummaryFixture();
    const secondId = `rpt_${"cd".repeat(32)}`;
    let resolveSecond!: (value: unknown) => void;
    api.getWalletCaseReportRevision
      .mockResolvedValueOnce(walletCaseReportRevisionDetailFixture())
      .mockImplementationOnce(() => new Promise((resolve) => { resolveSecond = resolve; }));
    const stable = vi.fn();
    const { result, rerender } = renderHook(
      ({ selected }) => useWalletCaseReports({
        caseId: CASE_ID,
        urlState: { snapshot: SYNC_ID, revision: selected },
        enabled: true,
        onSnapshotPinned: stable,
        onRevisionCaptured: stable,
      }),
      { initialProps: { selected: first.public_id } },
    );
    await waitFor(() => expect(result.current.detail).not.toBeNull());
    rerender({ selected: secondId });
    expect(result.current.detail).toBeNull();
    await act(async () => resolveSecond(walletCaseReportRevisionDetailFixture({
      revision: walletCaseReportRevisionSummaryFixture({
        public_id: secondId,
        content_hash_sha256: "cd".repeat(32),
        snapshot_public_id: "550e8400-e29b-41d4-a716-446655440099",
      }),
    })));
    await waitFor(() => expect(result.current.detailError).not.toBeNull());
    expect(result.current.detail).toBeNull();
  });

  it("captures once and pins the returned immutable revision", async () => {
    const revision = walletCaseReportRevisionSummaryFixture();
    const onRevisionCaptured = vi.fn();
    const stable = vi.fn();
    const { result } = renderHook(() => useWalletCaseReports({
      caseId: CASE_ID,
      urlState: { snapshot: SYNC_ID, revision: null },
      enabled: true,
      onSnapshotPinned: stable,
      onRevisionCaptured,
    }));
    await waitFor(() => expect(result.current.current).not.toBeNull());
    await act(async () => result.current.capture());
    expect(api.captureWalletCaseReportRevision).toHaveBeenCalledTimes(1);
    expect(onRevisionCaptured).toHaveBeenCalledWith(revision);
  });

  it("rejects overlapping catalog pagination without appending duplicates", async () => {
    const revision = walletCaseReportRevisionSummaryFixture();
    const firstPage = walletCaseReportRevisionCatalogFixture({
      aggregate: { total_revisions: 2, returned_count: 1 },
      page: { limit: 1, has_more: true, next_cursor: "signed.cursor" },
      limitations: [
        { code: "report_revisions_are_explicit_captures", message: "Explicit captures only." },
        { code: "report_revision_cursor_local_process_scope", message: "Cursor is process scoped." },
      ],
    });
    api.listWalletCaseReportRevisions
      .mockResolvedValueOnce(firstPage)
      .mockResolvedValueOnce(walletCaseReportRevisionCatalogFixture({
        items: [revision],
        aggregate: { total_revisions: 2, returned_count: 1 },
      }));
    const stable = vi.fn();
    const { result } = renderHook(() => useWalletCaseReports({
      caseId: CASE_ID,
      urlState: { snapshot: SYNC_ID, revision: null },
      enabled: true,
      onSnapshotPinned: stable,
      onRevisionCaptured: stable,
    }));
    await waitFor(() => expect(result.current.catalog?.page.has_more).toBe(true));
    await act(async () => result.current.loadMore());
    await waitFor(() => expect(result.current.catalogError).toMatch(/repeated/));
    expect(result.current.catalog?.items).toHaveLength(1);
  });

  it("does not fetch when an invalid URL disables the controller", () => {
    renderHook(() => useWalletCaseReports({
      caseId: CASE_ID,
      urlState: { snapshot: null, revision: null },
      enabled: false,
      onSnapshotPinned: vi.fn(),
      onRevisionCaptured: vi.fn(),
    }));
    expect(api.getWalletCaseReport).not.toHaveBeenCalled();
    expect(api.listWalletCaseReportRevisions).not.toHaveBeenCalled();
  });
});
