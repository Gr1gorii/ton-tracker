// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { useCallback, useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseEvidenceUrlState } from "./caseEvidenceQuery";
import { ACTIVITY_ID } from "./test/walletCaseActivityFixtures";
import { CASE_ID, IDEMPOTENCY_KEY, SYNC_ID } from "./test/walletCaseFixtures";
import {
  evidenceCatalogFixture,
  liveEvidenceActivityDetailFixture,
  queuedEvidenceVerificationFixture,
  retryWaitEvidenceVerificationFixture,
  runningEvidenceVerificationFixture,
  SECOND_VERIFICATION_ID,
  succeededEvidenceVerificationFixture,
  VERIFICATION_ID,
} from "./test/walletCaseEvidenceFixtures";

const evidenceApiMocks = vi.hoisted(() => ({
  getWalletCaseEvidence: vi.fn(),
  getWalletCaseEvidenceVerification: vi.fn(),
  createWalletCaseEvidenceVerification: vi.fn(),
  cancelWalletCaseEvidenceVerification: vi.fn(),
}));
const caseApiMocks = vi.hoisted(() => ({ getWalletCaseActivityDetail: vi.fn() }));

vi.mock("./walletCaseEvidenceApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./walletCaseEvidenceApi")>()),
  ...evidenceApiMocks,
}));
vi.mock("./walletCaseApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("./walletCaseApi")>()),
  ...caseApiMocks,
}));

import { useWalletCaseEvidence } from "./useWalletCaseEvidence";
import { WalletCaseEvidenceApiError } from "./walletCaseEvidenceApi";

const SELECTED: CaseEvidenceUrlState = {
  snapshot: SYNC_ID,
  activity: ACTIVITY_ID,
  verification: null,
};
const onSnapshotPinned = vi.fn();
const onVerificationPinned = vi.fn();

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.clearAllMocks();
  evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture());
  caseApiMocks.getWalletCaseActivityDetail.mockResolvedValue(liveEvidenceActivityDetailFixture());
  evidenceApiMocks.createWalletCaseEvidenceVerification.mockResolvedValue(queuedEvidenceVerificationFixture());
  evidenceApiMocks.cancelWalletCaseEvidenceVerification.mockResolvedValue(queuedEvidenceVerificationFixture({
    state: "cancelled",
    stage: "terminal",
    status_version: 2,
    cancel_requested: true,
    message: "Evidence verification was cancelled before execution.",
    updated_at: "2026-08-10T12:00:01Z",
    completed_at: "2026-08-10T12:00:01Z",
  }));
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("useWalletCaseEvidence", () => {
  it("pins the latest usable Evidence snapshot before doing selected work", async () => {
    const { result } = renderHook(() => useWalletCaseEvidence({
      caseId: CASE_ID,
      urlState: { snapshot: null, activity: null, verification: null },
      onSnapshotPinned,
      onVerificationPinned,
    }));

    await waitFor(() => expect(onSnapshotPinned).toHaveBeenCalledWith(SYNC_ID));
    expect(caseApiMocks.getWalletCaseActivityDetail).not.toHaveBeenCalled();
    expect(evidenceApiMocks.getWalletCaseEvidence.mock.calls[0][1]).toBeNull();
    expect(result.current.verification).toBeNull();
  });

  it("will not enqueue when catalog readiness says the runner is unavailable", async () => {
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({
      transactionVerificationAvailable: false,
      limitations: [
        { code: "evidence_runner_unavailable", message: "The local evidence runner is unavailable." },
        { code: "report_not_built", message: "A Wallet Case report is not built yet." },
      ],
    }));
    const { result } = renderHook(() => useWalletCaseEvidence({
      caseId: CASE_ID,
      urlState: SELECTED,
      onSnapshotPinned,
      onVerificationPinned,
    }));
    await waitFor(() => expect(result.current.catalogLoading).toBe(false));

    await act(async () => { await result.current.start(); });

    expect(evidenceApiMocks.createWalletCaseEvidenceVerification).not.toHaveBeenCalled();
    expect(onVerificationPinned).not.toHaveBeenCalled();
  });

  it("reuses one UUIDv4 idempotency key after a transient enqueue failure", async () => {
    const uuid = vi.spyOn(crypto, "randomUUID").mockReturnValue(IDEMPOTENCY_KEY);
    evidenceApiMocks.createWalletCaseEvidenceVerification
      .mockRejectedValueOnce(new Error("Connection interrupted"))
      .mockResolvedValueOnce(queuedEvidenceVerificationFixture());
    const { result } = renderHook(() => useWalletCaseEvidence({
      caseId: CASE_ID,
      urlState: SELECTED,
      onSnapshotPinned,
      onVerificationPinned,
    }));
    await waitFor(() => expect(result.current.catalogLoading).toBe(false));

    await act(async () => { await result.current.start(); });
    await act(async () => { await result.current.start(); });

    expect(uuid).toHaveBeenCalledTimes(1);
    expect(evidenceApiMocks.createWalletCaseEvidenceVerification).toHaveBeenCalledTimes(2);
    expect(evidenceApiMocks.createWalletCaseEvidenceVerification.mock.calls.map((call) => call[2])).toEqual([
      IDEMPOTENCY_KEY,
      IDEMPOTENCY_KEY,
    ]);
    expect(onVerificationPinned).toHaveBeenCalledWith(VERIFICATION_ID, false);
  });

  it("preserves the accepted enqueue state while the newly pinned GET is deferred", async () => {
    const pinnedGet = deferred<ReturnType<typeof runningEvidenceVerificationFixture>>();
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockReturnValue(pinnedGet.promise);
    const { result } = renderHook(() => {
      const [urlState, setUrlState] = useState<CaseEvidenceUrlState>(SELECTED);
      const pin = useCallback((verificationId: string) => {
        setUrlState((current) => ({ ...current, verification: verificationId }));
      }, []);
      return {
        urlState,
        controller: useWalletCaseEvidence({
          caseId: CASE_ID,
          urlState,
          onSnapshotPinned,
          onVerificationPinned: pin,
        }),
      };
    });
    await waitFor(() => expect(result.current.controller.catalogLoading).toBe(false));

    await act(async () => { await result.current.controller.start(); });

    await waitFor(() => expect(result.current.urlState.verification).toBe(VERIFICATION_ID));
    await waitFor(() => expect(result.current.controller.verificationLoading).toBe(true));
    expect(result.current.controller.verification?.public_id).toBe(VERIFICATION_ID);
    expect(result.current.controller.verification?.state).toBe("queued");

    act(() => pinnedGet.resolve(runningEvidenceVerificationFixture(0)));
    await waitFor(() => expect(result.current.controller.verification?.state).toBe("running"));
  });

  it("resumes an omitted active verification from a truncated catalog conflict", async () => {
    const unrelatedActivity = `act_${"2".repeat(64)}`;
    const visibleTerminal = succeededEvidenceVerificationFixture({ activity_public_id: unrelatedActivity });
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({
      verifications: [visibleTerminal],
      total: 51,
    }));
    evidenceApiMocks.createWalletCaseEvidenceVerification.mockRejectedValue(new WalletCaseEvidenceApiError({
      message: "This selection already has active verification.",
      status: 409,
      code: "evidence_verification_already_active",
      retryable: false,
      retryAfterMs: null,
      activeVerificationPublicId: SECOND_VERIFICATION_ID,
    }));
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockResolvedValue(queuedEvidenceVerificationFixture({
      public_id: SECOND_VERIFICATION_ID,
    }));
    const { result } = renderHook(() => {
      const [urlState, setUrlState] = useState<CaseEvidenceUrlState>(SELECTED);
      const pin = useCallback((verificationId: string) => {
        setUrlState((current) => ({ ...current, verification: verificationId }));
      }, []);
      return {
        urlState,
        controller: useWalletCaseEvidence({
          caseId: CASE_ID,
          urlState,
          onSnapshotPinned,
          onVerificationPinned: pin,
        }),
      };
    });
    await waitFor(() => expect(result.current.controller.catalog?.truncated).toBe(true));

    await act(async () => { await result.current.controller.start(); });

    await waitFor(() => expect(result.current.urlState.verification).toBe(SECOND_VERIFICATION_ID));
    await waitFor(() => expect(evidenceApiMocks.getWalletCaseEvidenceVerification).toHaveBeenCalledWith(
      CASE_ID,
      SECOND_VERIFICATION_ID,
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(result.current.controller.verification?.public_id).toBe(SECOND_VERIFICATION_ID));
    expect(result.current.controller.transportError).toBeNull();
  });

  it("resumes a durable retry_wait deep link and polls it to terminal state", async () => {
    evidenceApiMocks.getWalletCaseEvidenceVerification
      .mockResolvedValueOnce(retryWaitEvidenceVerificationFixture())
      .mockResolvedValueOnce(succeededEvidenceVerificationFixture());
    const { result } = renderHook(() => useWalletCaseEvidence({
      caseId: CASE_ID,
      urlState: { ...SELECTED, verification: VERIFICATION_ID },
      onSnapshotPinned,
      onVerificationPinned,
    }));

    await waitFor(() => expect(result.current.verification?.stage).toBe("retry_wait"));
    await waitFor(() => expect(result.current.verification?.state).toBe("succeeded"), { timeout: 2_500 });
    expect(evidenceApiMocks.getWalletCaseEvidenceVerification).toHaveBeenCalledTimes(2);
    expect(result.current.transportState).toBe("idle");
    expect(evidenceApiMocks.createWalletCaseEvidenceVerification).not.toHaveBeenCalled();
  });

  it("clears scope A immediately while a new scope B is pending and rejected", async () => {
    const pendingB = deferred<ReturnType<typeof succeededEvidenceVerificationFixture>>();
    evidenceApiMocks.getWalletCaseEvidenceVerification
      .mockResolvedValueOnce(succeededEvidenceVerificationFixture())
      .mockReturnValueOnce(pendingB.promise);
    const { result, rerender } = renderHook(
      ({ state }) => useWalletCaseEvidence({
        caseId: CASE_ID,
        urlState: state,
        onSnapshotPinned,
        onVerificationPinned,
      }),
      { initialProps: { state: { ...SELECTED, verification: VERIFICATION_ID } } },
    );
    await waitFor(() => expect(result.current.verification?.public_id).toBe(VERIFICATION_ID));

    rerender({ state: { ...SELECTED, verification: SECOND_VERIFICATION_ID } });
    expect(result.current.verification).toBeNull();
    expect(result.current.verificationLoading).toBe(true);

    act(() => pendingB.reject(new Error("Evidence verification not found")));
    await waitFor(() => expect(result.current.verificationLoading).toBe(false));
    expect(result.current.verification).toBeNull();
    expect(result.current.transportError).toMatch(/not found/);
  });

  it("does not let scope A polling cleanup abort scope B direct GET", async () => {
    const pendingB = deferred<ReturnType<typeof succeededEvidenceVerificationFixture>>();
    evidenceApiMocks.getWalletCaseEvidenceVerification
      .mockResolvedValueOnce(queuedEvidenceVerificationFixture())
      .mockReturnValueOnce(pendingB.promise);
    const { result, rerender } = renderHook(
      ({ state }) => useWalletCaseEvidence({
        caseId: CASE_ID,
        urlState: state,
        onSnapshotPinned,
        onVerificationPinned,
      }),
      { initialProps: { state: { ...SELECTED, verification: VERIFICATION_ID } } },
    );
    await waitFor(() => expect(result.current.verification?.state).toBe("queued"));

    rerender({ state: { ...SELECTED, verification: SECOND_VERIFICATION_ID } });
    await waitFor(() => expect(evidenceApiMocks.getWalletCaseEvidenceVerification).toHaveBeenCalledTimes(2));
    const scopeBSignal = evidenceApiMocks.getWalletCaseEvidenceVerification.mock.calls[1][2] as AbortSignal;
    expect(scopeBSignal.aborted).toBe(false);

    act(() => pendingB.resolve(succeededEvidenceVerificationFixture({ public_id: SECOND_VERIFICATION_ID })));
    await waitFor(() => expect(result.current.verification?.public_id).toBe(SECOND_VERIFICATION_ID));
    expect(scopeBSignal.aborted).toBe(false);
  });

  it("never renders snapshot A catalog readiness or history while snapshot B is pending or rejected", async () => {
    const SNAPSHOT_B = "550e8400-e29b-41d4-b716-446655440022";
    const pendingB = deferred<ReturnType<typeof evidenceCatalogFixture>>();
    evidenceApiMocks.getWalletCaseEvidence
      .mockResolvedValueOnce(evidenceCatalogFixture({ verifications: [succeededEvidenceVerificationFixture()] }))
      .mockReturnValueOnce(pendingB.promise);
    const { result, rerender } = renderHook(
      ({ state }) => useWalletCaseEvidence({
        caseId: CASE_ID,
        urlState: state,
        onSnapshotPinned,
        onVerificationPinned,
      }),
      { initialProps: { state: { snapshot: SYNC_ID, activity: null, verification: null } } },
    );
    await waitFor(() => expect(result.current.catalog?.snapshot?.public_id).toBe(SYNC_ID));

    rerender({ state: { snapshot: SNAPSHOT_B, activity: null, verification: null } });
    expect(result.current.catalog).toBeNull();

    act(() => pendingB.reject(new Error("Snapshot B was not found")));
    await waitFor(() => expect(result.current.catalogLoading).toBe(false));
    expect(result.current.catalog).toBeNull();
    expect(result.current.catalogError).toMatch(/Snapshot B/);
  });

  it("Check now starts exactly one immediate request after a completed failed poll", async () => {
    evidenceApiMocks.getWalletCaseEvidenceVerification
      .mockResolvedValueOnce(queuedEvidenceVerificationFixture())
      .mockRejectedValueOnce(new Error("Network interrupted"))
      .mockResolvedValueOnce(succeededEvidenceVerificationFixture());
    const { result } = renderHook(() => useWalletCaseEvidence({
      caseId: CASE_ID,
      urlState: { ...SELECTED, verification: VERIFICATION_ID },
      onSnapshotPinned,
      onVerificationPinned,
    }));
    await waitFor(() => expect(result.current.verification?.state).toBe("queued"));
    await waitFor(() => expect(result.current.transportError).toMatch(/Connection interrupted/), { timeout: 1_500 });
    expect(evidenceApiMocks.getWalletCaseEvidenceVerification).toHaveBeenCalledTimes(2);

    act(() => result.current.checkNow());

    await waitFor(() => expect(evidenceApiMocks.getWalletCaseEvidenceVerification).toHaveBeenCalledTimes(3), { timeout: 500 });
    await waitFor(() => expect(result.current.verification?.state).toBe("succeeded"));
  });

  it("does not pin an enqueue response after the selected scope changes", async () => {
    const pending = deferred<ReturnType<typeof queuedEvidenceVerificationFixture>>();
    evidenceApiMocks.createWalletCaseEvidenceVerification.mockReturnValue(pending.promise);
    const { result, rerender } = renderHook(
      ({ state }) => useWalletCaseEvidence({
        caseId: CASE_ID,
        urlState: state,
        onSnapshotPinned,
        onVerificationPinned,
      }),
      { initialProps: { state: SELECTED } },
    );
    await waitFor(() => expect(result.current.catalogLoading).toBe(false));

    let startPromise!: Promise<void>;
    act(() => { startPromise = result.current.start(); });
    rerender({ state: { snapshot: SYNC_ID, activity: `act_${"2".repeat(64)}`, verification: null } });
    act(() => pending.resolve(queuedEvidenceVerificationFixture()));
    await act(async () => { await startPromise; });

    expect(onVerificationPinned).not.toHaveBeenCalled();
    expect(result.current.verification).toBeNull();
  });
});
