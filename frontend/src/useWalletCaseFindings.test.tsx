// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID, SYNC_ID } from "./test/walletCaseFixtures";
import { walletCaseFindingsFixture } from "./test/walletCaseFindingsFixtures";
import { useWalletCaseFindings } from "./useWalletCaseFindings";

const api = vi.hoisted(() => ({ getWalletCaseFindings: vi.fn() }));
vi.mock("./walletCaseFindingsApi", () => api);

beforeEach(() => api.getWalletCaseFindings.mockReset());
afterEach(() => cleanup());

describe("useWalletCaseFindings", () => {
  it("pins the latest usable snapshot and exposes its revision", async () => {
    api.getWalletCaseFindings.mockResolvedValue(walletCaseFindingsFixture());
    const onSnapshotPinned = vi.fn();
    const { result } = renderHook(() => useWalletCaseFindings({
      caseId: CASE_ID,
      urlState: { snapshot: null },
      enabled: true,
      onSnapshotPinned,
    }));
    await waitFor(() => expect(result.current.response?.snapshot_public_id).toBe(SYNC_ID));
    expect(onSnapshotPinned).toHaveBeenCalledWith(SYNC_ID);
  });

  it("clears stale scope immediately and ignores an aborted response", async () => {
    let resolveA!: (value: unknown) => void;
    api.getWalletCaseFindings.mockImplementationOnce(() => new Promise((resolve) => { resolveA = resolve; }));
    api.getWalletCaseFindings.mockImplementationOnce(() => new Promise(() => undefined));
    const snapshotB = "00000000-0000-4000-8000-000000000099";
    const onSnapshotPinned = vi.fn();
    const { result, rerender } = renderHook(
      ({ snapshot }) => useWalletCaseFindings({ caseId: CASE_ID, urlState: { snapshot }, enabled: true, onSnapshotPinned }),
      { initialProps: { snapshot: SYNC_ID } },
    );
    rerender({ snapshot: snapshotB });
    expect(result.current.response).toBeNull();
    await act(async () => resolveA(walletCaseFindingsFixture()));
    await waitFor(() => expect(api.getWalletCaseFindings).toHaveBeenCalledTimes(2));
    expect(result.current.response).toBeNull();
  });

  it("does not fetch an invalid disabled URL and reloads once", async () => {
    const onSnapshotPinned = vi.fn();
    const { result, rerender } = renderHook(
      ({ enabled }) => useWalletCaseFindings({ caseId: CASE_ID, urlState: { snapshot: SYNC_ID }, enabled, onSnapshotPinned }),
      { initialProps: { enabled: false } },
    );
    expect(api.getWalletCaseFindings).not.toHaveBeenCalled();
    api.getWalletCaseFindings.mockResolvedValue(walletCaseFindingsFixture());
    rerender({ enabled: true });
    await waitFor(() => expect(result.current.response).not.toBeNull());
    act(() => result.current.reload());
    await waitFor(() => expect(api.getWalletCaseFindings).toHaveBeenCalledTimes(2));
  });
});
