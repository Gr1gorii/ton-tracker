import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CaseEvidenceUrlState } from "./caseEvidenceQuery";
import { getWalletCaseActivityDetail } from "./walletCaseApi";
import type { WalletCaseActivityDetailResponse } from "./walletCaseActivity";
import {
  isActiveWalletCaseEvidenceVerification,
  type WalletCaseEvidenceCatalog,
  type WalletCaseEvidenceVerification,
  type WalletCaseEvidenceVerificationRequest,
} from "./walletCaseEvidence";
import {
  cancelWalletCaseEvidenceVerification,
  createWalletCaseEvidenceVerification,
  getWalletCaseEvidence,
  getWalletCaseEvidenceVerification,
  WalletCaseEvidenceApiError,
} from "./walletCaseEvidenceApi";

export type WalletCaseEvidenceTransportState =
  | "idle"
  | "starting"
  | "polling"
  | "reconnecting"
  | "cancelling";

export interface WalletCaseEvidenceController {
  catalog: WalletCaseEvidenceCatalog | null;
  catalogLoading: boolean;
  catalogError: string | null;
  activityDetail: WalletCaseActivityDetailResponse | null;
  activityLoading: boolean;
  activityError: string | null;
  verification: WalletCaseEvidenceVerification | null;
  verificationLoading: boolean;
  transportState: WalletCaseEvidenceTransportState;
  transportError: string | null;
  start: () => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => Promise<void>;
  checkNow: () => void;
  reload: () => void;
}

interface PendingStart {
  idempotencyKey: string;
  request: WalletCaseEvidenceVerificationRequest;
}

const MIN_POLL_MS = 750;
const MAX_POLL_MS = 15_000;

export function useWalletCaseEvidence({
  caseId,
  urlState,
  onSnapshotPinned,
  onVerificationPinned,
  enabled = true,
}: {
  caseId: string;
  urlState: CaseEvidenceUrlState;
  onSnapshotPinned: (snapshotId: string) => void;
  onVerificationPinned: (verificationId: string, replace: boolean) => void;
  enabled?: boolean;
}): WalletCaseEvidenceController {
  const [catalog, setCatalog] = useState<WalletCaseEvidenceCatalog | null>(null);
  const [catalogScope, setCatalogScope] = useState<string | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [activityDetail, setActivityDetail] = useState<WalletCaseActivityDetailResponse | null>(null);
  const [activityScope, setActivityScope] = useState<string | null>(null);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityError, setActivityError] = useState<string | null>(null);
  const [verification, setVerification] = useState<WalletCaseEvidenceVerification | null>(null);
  const [verificationLoading, setVerificationLoading] = useState(false);
  const [transportState, setTransportState] = useState<WalletCaseEvidenceTransportState>("idle");
  const [transportError, setTransportError] = useState<string | null>(null);
  const [catalogVersion, setCatalogVersion] = useState(0);
  const [detailVersion, setDetailVersion] = useState(0);
  const [verificationVersion, setVerificationVersion] = useState(0);
  const [pollEpoch, setPollEpoch] = useState(0);
  const catalogController = useRef<AbortController | null>(null);
  const activityController = useRef<AbortController | null>(null);
  const verificationController = useRef<AbortController | null>(null);
  const actionController = useRef<AbortController | null>(null);
  const catalogGeneration = useRef(0);
  const activityGeneration = useRef(0);
  const verificationGeneration = useRef(0);
  const verificationRef = useRef<WalletCaseEvidenceVerification | null>(null);
  const pendingStart = useRef<PendingStart | null>(null);
  const forceImmediatePoll = useRef(false);
  const terminalRefreshes = useRef(new Set<string>());

  const selectedScopeKey = useMemo(
    () => `${urlState.snapshot ?? ""}:${urlState.activity ?? ""}:${urlState.verification ?? ""}`,
    [urlState.activity, urlState.snapshot, urlState.verification],
  );
  const catalogRequestKey = `${caseId}:${urlState.snapshot ?? "latest"}`;
  const activityRequestKey = `${caseId}:${urlState.snapshot ?? ""}:${urlState.activity ?? ""}`;
  const scopeRef = useRef(selectedScopeKey);
  scopeRef.current = selectedScopeKey;

  const matchesSelectedScope = useCallback((next: WalletCaseEvidenceVerification, allowUnpinned = false): boolean => (
    next.case_public_id === caseId &&
    next.snapshot_public_id === urlState.snapshot &&
    next.activity_public_id === urlState.activity &&
    (next.public_id === urlState.verification || (allowUnpinned && urlState.verification === null))
  ), [caseId, urlState.activity, urlState.snapshot, urlState.verification]);

  const acceptVerification = useCallback((next: WalletCaseEvidenceVerification, allowUnpinned = false): boolean => {
    if (!matchesSelectedScope(next, allowUnpinned)) return false;
    const current = verificationRef.current;
    if (current?.public_id === next.public_id && current.status_version >= next.status_version) return false;
    verificationRef.current = next;
    setVerification(next);
    if (isActiveWalletCaseEvidenceVerification(next)) {
      setTransportState("polling");
    } else {
      setTransportState("idle");
      const terminalKey = `${next.public_id}:${next.status_version}`;
      if (!terminalRefreshes.current.has(terminalKey)) {
        terminalRefreshes.current.add(terminalKey);
        setCatalogVersion((value) => value + 1);
      }
    }
    return true;
  }, [matchesSelectedScope]);

  useEffect(() => {
    actionController.current?.abort();
    actionController.current = null;
    pendingStart.current = null;
  }, [selectedScopeKey]);

  useEffect(() => {
    catalogController.current?.abort();
    if (!enabled) {
      catalogGeneration.current += 1;
      setCatalog(null);
      setCatalogScope(null);
      setCatalogLoading(false);
      setCatalogError(null);
      return;
    }
    const controller = new AbortController();
    catalogController.current = controller;
    const generation = ++catalogGeneration.current;
    setCatalogLoading(true);
    setCatalogError(null);
    void getWalletCaseEvidence(caseId, urlState.snapshot, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || generation !== catalogGeneration.current) return;
        setCatalog(result);
        setCatalogScope(catalogRequestKey);
        if (urlState.snapshot === null && result.snapshot !== null) {
          onSnapshotPinned(result.snapshot.public_id);
          return;
        }
        if (urlState.verification === null && urlState.activity !== null) {
          const matching = result.verifications
            .filter((item) => item.activity_public_id === urlState.activity)
            .sort((left, right) => {
              const activeDifference = Number(isActiveWalletCaseEvidenceVerification(right)) - Number(isActiveWalletCaseEvidenceVerification(left));
              return activeDifference || Date.parse(right.updated_at) - Date.parse(left.updated_at);
            });
          if (matching[0]) {
            verificationRef.current = matching[0];
            setVerification(matching[0]);
            onVerificationPinned(matching[0].public_id, true);
          }
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted && generation === catalogGeneration.current) {
          setCatalogError(message(error, "Wallet Case Evidence is unavailable."));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && generation === catalogGeneration.current) setCatalogLoading(false);
      });
    return () => controller.abort();
  }, [caseId, catalogRequestKey, catalogVersion, enabled, onSnapshotPinned, onVerificationPinned, urlState.activity, urlState.snapshot, urlState.verification]);

  useEffect(() => {
    activityController.current?.abort();
    setActivityDetail(null);
    setActivityScope(null);
    setActivityError(null);
    if (!enabled || urlState.snapshot === null || urlState.activity === null) {
      setActivityLoading(false);
      return;
    }
    const controller = new AbortController();
    activityController.current = controller;
    const generation = ++activityGeneration.current;
    setActivityLoading(true);
    void getWalletCaseActivityDetail(caseId, urlState.snapshot, urlState.activity, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted && generation === activityGeneration.current) {
          setActivityDetail(result);
          setActivityScope(activityRequestKey);
        }
      })
      .catch((error) => {
        if (!controller.signal.aborted && generation === activityGeneration.current) setActivityError(message(error, "Selected Activity is unavailable."));
      })
      .finally(() => {
        if (!controller.signal.aborted && generation === activityGeneration.current) setActivityLoading(false);
      });
    return () => controller.abort();
  }, [activityRequestKey, caseId, detailVersion, enabled, urlState.activity, urlState.snapshot]);

  useEffect(() => {
    verificationController.current?.abort();
    verificationGeneration.current += 1;
    const accepted = verificationRef.current;
    const preserveAccepted = Boolean(
      enabled &&
      urlState.verification !== null &&
      accepted?.case_public_id === caseId &&
      accepted.snapshot_public_id === urlState.snapshot &&
      accepted.activity_public_id === urlState.activity &&
      accepted.public_id === urlState.verification,
    );
    if (!preserveAccepted) {
      verificationRef.current = null;
      setVerification(null);
      setTransportState("idle");
    }
    setTransportError(null);
    if (!enabled || urlState.verification === null) {
      setVerificationLoading(false);
      return;
    }
    const controller = new AbortController();
    verificationController.current = controller;
    const generation = ++verificationGeneration.current;
    setVerificationLoading(true);
    void getWalletCaseEvidenceVerification(caseId, urlState.verification, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || generation !== verificationGeneration.current) return;
        if (result.snapshot_public_id !== urlState.snapshot || result.activity_public_id !== urlState.activity) {
          throw new Error("Evidence verification does not belong to the selected snapshot and Activity.");
        }
        acceptVerification(result);
      })
      .catch((error) => {
        if (!controller.signal.aborted && generation === verificationGeneration.current) setTransportError(message(error, "Evidence verification is unavailable."));
      })
      .finally(() => {
        if (verificationController.current === controller) verificationController.current = null;
        if (!controller.signal.aborted && generation === verificationGeneration.current) setVerificationLoading(false);
      });
    return () => controller.abort();
  }, [acceptVerification, caseId, enabled, selectedScopeKey, verificationVersion]);

  const scopedVerification = verification && matchesSelectedScope(verification)
    ? verification
    : null;
  const scopedCatalog = catalogScope === catalogRequestKey ? catalog : null;
  const scopedActivityDetail = activityScope === activityRequestKey ? activityDetail : null;
  const activeVerificationId = scopedVerification && isActiveWalletCaseEvidenceVerification(scopedVerification)
    ? scopedVerification.public_id
    : null;

  useEffect(() => {
    if (!activeVerificationId) return;
    let stopped = false;
    let inFlight = false;
    let timer: number | undefined;
    let currentPollController: AbortController | null = null;
    let failures = 0;
    const verificationId = activeVerificationId;

    function clearTimer() {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
    }
    function schedule(delay: number) {
      if (stopped || !isActiveWalletCaseEvidenceVerification(verificationRef.current)) return;
      clearTimer();
      const bounded = Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, delay));
      const visibleDelay = document.visibilityState === "hidden" ? MAX_POLL_MS : bounded;
      timer = window.setTimeout(() => void poll(), visibleDelay);
    }
    async function poll() {
      if (stopped || inFlight || !isActiveWalletCaseEvidenceVerification(verificationRef.current)) return;
      if (typeof navigator !== "undefined" && navigator.onLine === false) {
        setTransportState("reconnecting");
        setTransportError("Connection lost. Evidence verification remains durable on the server.");
        return;
      }
      inFlight = true;
      setTransportState(failures ? "reconnecting" : "polling");
      const controller = new AbortController();
      currentPollController = controller;
      verificationController.current = controller;
      try {
        const next = await getWalletCaseEvidenceVerification(caseId, verificationId, controller.signal);
        if (stopped || controller.signal.aborted) return;
        failures = 0;
        setTransportError(null);
        acceptVerification(next);
        if (isActiveWalletCaseEvidenceVerification(verificationRef.current)) schedule(MIN_POLL_MS);
      } catch (error) {
        if (stopped || controller.signal.aborted) return;
        failures += 1;
        setTransportState("reconnecting");
        setTransportError("Connection interrupted. The server verification is still safe; GRAM Scope will retry.");
        const apiDelay = error instanceof WalletCaseEvidenceApiError ? error.retryAfterMs : null;
        schedule(apiDelay ?? Math.min(MAX_POLL_MS, 1_000 * 2 ** (failures - 1)));
      } finally {
        inFlight = false;
        if (currentPollController === controller) currentPollController = null;
        if (verificationController.current === controller) verificationController.current = null;
        if (!stopped && controller.signal.aborted && forceImmediatePoll.current) {
          forceImmediatePoll.current = false;
          clearTimer();
          timer = window.setTimeout(() => void poll(), 0);
        }
      }
    }
    function wake() {
      if (stopped || inFlight || document.visibilityState === "hidden") return;
      clearTimer();
      void poll();
    }
    function visibilityChanged() {
      if (document.visibilityState === "visible") wake();
      else schedule(MAX_POLL_MS);
    }
    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", visibilityChanged);
    if (forceImmediatePoll.current) {
      forceImmediatePoll.current = false;
      timer = window.setTimeout(() => void poll(), 0);
    } else {
      schedule(MIN_POLL_MS);
    }
    return () => {
      stopped = true;
      clearTimer();
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", visibilityChanged);
      const controller = currentPollController;
      currentPollController = null;
      controller?.abort();
      if (verificationController.current === controller) verificationController.current = null;
    };
  }, [acceptVerification, activeVerificationId, caseId, pollEpoch]);

  useEffect(() => () => {
    catalogController.current?.abort();
    activityController.current?.abort();
    verificationController.current?.abort();
    actionController.current?.abort();
  }, []);

  const start = useCallback(async () => {
    if (
      !enabled || urlState.snapshot === null || urlState.activity === null ||
      scopedCatalog?.readiness.transaction_verification_available !== true ||
      isActiveWalletCaseEvidenceVerification(verificationRef.current) || actionController.current
    ) return;
    const request: WalletCaseEvidenceVerificationRequest = {
      snapshot_public_id: urlState.snapshot,
      activity_public_id: urlState.activity,
      policy: "transaction_inclusion_v1",
    };
    const pending = pendingStart.current && sameRequest(pendingStart.current.request, request)
      ? pendingStart.current
      : { idempotencyKey: crypto.randomUUID(), request };
    pendingStart.current = pending;
    const controller = new AbortController();
    const actionScope = selectedScopeKey;
    actionController.current = controller;
    setTransportState("starting");
    setTransportError(null);
    try {
      const next = await createWalletCaseEvidenceVerification(caseId, pending.request, pending.idempotencyKey, controller.signal);
      if (controller.signal.aborted || scopeRef.current !== actionScope) return;
      pendingStart.current = null;
      acceptVerification(next, true);
      onVerificationPinned(next.public_id, false);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof WalletCaseEvidenceApiError && !error.retryable) pendingStart.current = null;
      if (error instanceof WalletCaseEvidenceApiError && error.code === "evidence_verification_already_active") {
        pendingStart.current = null;
        if (error.activeVerificationPublicId) {
          setTransportError(null);
          setTransportState("idle");
          onVerificationPinned(error.activeVerificationPublicId, false);
          return;
        }
        setCatalogVersion((value) => value + 1);
      }
      setTransportError(message(error, "Evidence verification could not start."));
      setTransportState("idle");
    } finally {
      if (actionController.current === controller) actionController.current = null;
    }
  }, [acceptVerification, caseId, enabled, onVerificationPinned, scopedCatalog?.readiness.transaction_verification_available, selectedScopeKey, urlState.activity, urlState.snapshot]);

  const retry = useCallback(async () => {
    pendingStart.current = null;
    verificationRef.current = null;
    setVerification(null);
    await start();
  }, [start]);

  const cancel = useCallback(async () => {
    const current = verificationRef.current;
    if (!isActiveWalletCaseEvidenceVerification(current) || !current || actionController.current) return;
    verificationController.current?.abort();
    const controller = new AbortController();
    const actionScope = selectedScopeKey;
    actionController.current = controller;
    setTransportState("cancelling");
    setTransportError(null);
    try {
      const next = await cancelWalletCaseEvidenceVerification(caseId, current.public_id, controller.signal);
      if (!controller.signal.aborted && scopeRef.current === actionScope) acceptVerification(next);
    } catch (error) {
      if (!controller.signal.aborted) {
        setTransportError(message(error, "Evidence cancellation could not be requested."));
        setTransportState("reconnecting");
      }
    } finally {
      if (actionController.current === controller) actionController.current = null;
      if (!controller.signal.aborted) setPollEpoch((value) => value + 1);
    }
  }, [acceptVerification, caseId, selectedScopeKey]);

  const checkNow = useCallback(() => {
    if (!isActiveWalletCaseEvidenceVerification(verificationRef.current)) return;
    forceImmediatePoll.current = true;
    if (verificationController.current) verificationController.current.abort();
    else setPollEpoch((value) => value + 1);
  }, []);

  return {
    catalog: scopedCatalog,
    catalogLoading,
    catalogError,
    activityDetail: scopedActivityDetail,
    activityLoading,
    activityError,
    verification: scopedVerification,
    verificationLoading,
    transportState,
    transportError,
    start,
    retry,
    cancel,
    checkNow,
    reload: () => {
      setCatalogVersion((value) => value + 1);
      setDetailVersion((value) => value + 1);
      setVerificationVersion((value) => value + 1);
    },
  };
}

function sameRequest(left: WalletCaseEvidenceVerificationRequest, right: WalletCaseEvidenceVerificationRequest): boolean {
  return left.snapshot_public_id === right.snapshot_public_id && left.activity_public_id === right.activity_public_id && left.policy === right.policy;
}

function message(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}
