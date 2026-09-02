import { useCallback, useEffect, useRef, useState } from "react";

import {
  WalletCaseApiError,
  cancelWalletCaseSync,
  createWalletCaseSync,
  getWalletCaseSync,
  resumeWalletCaseContinuationPlan,
  resumeWalletCaseStreamCheckpoint,
  runWalletCaseBackfillSchedule,
} from "./walletCaseApi";
import type { WalletCaseSync, WalletCaseSyncRequest } from "./walletCase";
import type { WalletCaseBackfillScheduleResponse } from "./walletCaseStreamCheckpoint";

export type WalletCaseSyncTransportState =
  | "idle"
  | "starting"
  | "polling"
  | "reconnecting"
  | "cancelling";

export interface WalletCaseSyncJobController {
  sync: WalletCaseSync | null;
  transportState: WalletCaseSyncTransportState;
  transportError: string | null;
  start: (request: WalletCaseSyncRequest) => Promise<void>;
  resume: (checkpointPublicId: string) => Promise<void>;
  resumePlanned: (
    continuationPlanPublicId: string,
    checkpointPublicId: string,
    pageBudget?: number,
  ) => Promise<void>;
  runSchedule: (schedule: WalletCaseBackfillScheduleResponse) => Promise<void>;
  retryPending: () => Promise<void>;
  retry: () => Promise<void>;
  cancel: () => Promise<void>;
  checkNow: () => void;
}

interface UseWalletCaseSyncJobOptions {
  caseId: string;
  initialSync: WalletCaseSync | null;
  onTerminal: (sync: WalletCaseSync) => void | Promise<void>;
}

type PendingStart = {
  idempotencyKey: string;
} & (
  | { kind: "sync"; request: WalletCaseSyncRequest }
  | {
      kind: "resume";
      continuationPlanPublicId: string | null;
      checkpointPublicId: string;
      pageBudget: number | null;
    }
  | { kind: "schedule"; schedule: WalletCaseBackfillScheduleResponse }
);

type RequestedStart =
  | { kind: "sync"; request: WalletCaseSyncRequest }
  | {
      kind: "resume";
      continuationPlanPublicId: string | null;
      checkpointPublicId: string;
      pageBudget: number | null;
    }
  | { kind: "schedule"; schedule: WalletCaseBackfillScheduleResponse };

const TERMINAL_STATES = new Set(["partial", "succeeded", "failed", "cancelled"]);
const MIN_POLL_MS = 500;
const MAX_POLL_MS = 15_000;

export function isActiveWalletCaseSync(sync: WalletCaseSync | null): boolean {
  return sync !== null && (sync.state === "queued" || sync.state === "running");
}

function pollDelay(milliseconds: number): number {
  const bounded = Math.min(MAX_POLL_MS, Math.max(MIN_POLL_MS, milliseconds));
  return typeof document !== "undefined" && document.visibilityState === "hidden"
    ? Math.max(MAX_POLL_MS, bounded)
    : bounded;
}

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export function useWalletCaseSyncJob({
  caseId,
  initialSync,
  onTerminal,
}: UseWalletCaseSyncJobOptions): WalletCaseSyncJobController {
  const [sync, setSync] = useState<WalletCaseSync | null>(initialSync);
  const [transportState, setTransportState] = useState<WalletCaseSyncTransportState>(
    isActiveWalletCaseSync(initialSync) ? "polling" : "idle",
  );
  const [transportError, setTransportError] = useState<string | null>(null);
  const [pollEpoch, setPollEpoch] = useState(0);
  const syncRef = useRef<WalletCaseSync | null>(initialSync);
  const pendingStartRef = useRef<PendingStart | null>(null);
  const actionControllerRef = useRef<AbortController | null>(null);
  const pollControllerRef = useRef<AbortController | null>(null);
  const forceImmediatePollRef = useRef(false);
  const notifiedTerminalIdsRef = useRef(new Set<string>());
  const onTerminalRef = useRef(onTerminal);
  const caseIdRef = useRef(caseId);

  useEffect(() => {
    onTerminalRef.current = onTerminal;
  }, [onTerminal]);

  const notifyTerminal = useCallback((next: WalletCaseSync) => {
    if (!TERMINAL_STATES.has(next.state)) return;
    const notificationKey = `${next.public_id}:${next.status_version}`;
    if (notifiedTerminalIdsRef.current.has(notificationKey)) return;
    notifiedTerminalIdsRef.current.add(notificationKey);
    void onTerminalRef.current(next);
  }, []);

  const acceptSync = useCallback((next: WalletCaseSync): boolean => {
    if (next.case_public_id !== caseIdRef.current) return false;
    const current = syncRef.current;
    if (current?.public_id === next.public_id) {
      if (current.status_version > next.status_version) return false;
      if (current.status_version === next.status_version) {
        // poll_after_ms is a response-time scheduling hint and may legitimately
        // change while the persisted status_version remains stable.
        syncRef.current = { ...current, poll_after_ms: next.poll_after_ms };
        return false;
      }
    }
    syncRef.current = next;
    setSync(next);
    if (TERMINAL_STATES.has(next.state)) {
      setTransportState("idle");
      setTransportError(null);
      notifyTerminal(next);
    }
    return true;
  }, [notifyTerminal]);

  useEffect(() => {
    if (caseIdRef.current !== caseId) {
      caseIdRef.current = caseId;
      pendingStartRef.current = null;
      actionControllerRef.current?.abort();
      pollControllerRef.current?.abort();
      syncRef.current = initialSync;
      setSync(initialSync);
      setTransportError(null);
      setTransportState(isActiveWalletCaseSync(initialSync) ? "polling" : "idle");
      return;
    }
    const current = syncRef.current;
    if (!initialSync) {
      if (!isActiveWalletCaseSync(current)) {
        syncRef.current = null;
        setSync(null);
      }
      return;
    }
    if (
      current?.public_id !== initialSync.public_id ||
      initialSync.status_version > current.status_version
    ) {
      syncRef.current = initialSync;
      setSync(initialSync);
    }
  }, [caseId, initialSync]);

  useEffect(() => {
    return () => {
      actionControllerRef.current?.abort();
      pollControllerRef.current?.abort();
    };
  }, []);

  const activeJobId = sync && sync.case_public_id === caseId && isActiveWalletCaseSync(sync)
    ? sync.public_id
    : null;

  useEffect(() => {
    if (!activeJobId) return;
    const jobId = activeJobId;
    let stopped = false;
    let inFlight = false;
    let timer: number | undefined;
    let consecutiveFailures = 0;

    function clearTimer() {
      if (timer !== undefined) window.clearTimeout(timer);
      timer = undefined;
    }

    function schedule(delay: number) {
      if (stopped || !isActiveWalletCaseSync(syncRef.current)) return;
      clearTimer();
      timer = window.setTimeout(() => void poll(), pollDelay(delay));
    }

    async function poll() {
      if (stopped || inFlight || !isActiveWalletCaseSync(syncRef.current)) return;
      if (typeof navigator !== "undefined" && navigator.onLine === false) {
        setTransportState("reconnecting");
        setTransportError("Connection lost. Synchronization continues on the server.");
        return;
      }
      inFlight = true;
      setTransportState(consecutiveFailures > 0 ? "reconnecting" : "polling");
      const controller = new AbortController();
      pollControllerRef.current = controller;
      try {
        const next = await getWalletCaseSync(caseId, jobId, controller.signal);
        if (stopped || controller.signal.aborted) return;
        consecutiveFailures = 0;
        setTransportError(null);
        acceptSync(next);
        if (isActiveWalletCaseSync(syncRef.current)) {
          schedule(syncRef.current?.poll_after_ms ?? MAX_POLL_MS);
        }
      } catch (error) {
        if (stopped || controller.signal.aborted) return;
        consecutiveFailures += 1;
        setTransportState("reconnecting");
        setTransportError(
          "Connection interrupted. The server job is still safe; GRAM Scope will retry.",
        );
        const apiDelay = error instanceof WalletCaseApiError ? error.retryAfterMs : null;
        const backoff = Math.min(MAX_POLL_MS, 1_000 * 2 ** (consecutiveFailures - 1));
        schedule(apiDelay ?? backoff);
      } finally {
        inFlight = false;
        if (pollControllerRef.current === controller) pollControllerRef.current = null;
        if (!stopped && controller.signal.aborted && forceImmediatePollRef.current) {
          forceImmediatePollRef.current = false;
          clearTimer();
          timer = window.setTimeout(() => void poll(), 0);
        }
      }
    }

    function wake() {
      if (document.visibilityState === "hidden" || stopped || inFlight) return;
      clearTimer();
      void poll();
    }

    function handleVisibility() {
      if (document.visibilityState === "visible") wake();
      else schedule(syncRef.current?.poll_after_ms ?? MAX_POLL_MS);
    }

    window.addEventListener("online", wake);
    document.addEventListener("visibilitychange", handleVisibility);
    if (forceImmediatePollRef.current) {
      forceImmediatePollRef.current = false;
      timer = window.setTimeout(() => void poll(), 0);
    } else {
      schedule(syncRef.current?.poll_after_ms ?? MIN_POLL_MS);
    }

    return () => {
      stopped = true;
      clearTimer();
      window.removeEventListener("online", wake);
      document.removeEventListener("visibilitychange", handleVisibility);
      pollControllerRef.current?.abort();
      pollControllerRef.current = null;
    };
  }, [acceptSync, activeJobId, caseId, pollEpoch]);

  const begin = useCallback(async (requested: RequestedStart) => {
    if (isActiveWalletCaseSync(syncRef.current) || actionControllerRef.current) return;
    const existing = pendingStartRef.current;
    const matchesPending = existing === null || (
      existing.kind === requested.kind && (
        (existing.kind === "sync" && requested.kind === "sync" &&
          JSON.stringify(existing.request) === JSON.stringify(requested.request)) ||
        (existing.kind === "resume" && requested.kind === "resume" &&
          existing.continuationPlanPublicId === requested.continuationPlanPublicId &&
          existing.checkpointPublicId === requested.checkpointPublicId &&
          existing.pageBudget === requested.pageBudget) ||
        (existing.kind === "schedule" && requested.kind === "schedule" &&
          existing.schedule.schedule.public_id === requested.schedule.schedule.public_id)
      )
    );
    if (!matchesPending) {
      setTransportError(
        "A previous start request has an unknown outcome. Retry that action before starting another.",
      );
      return;
    }
    const pending: PendingStart = existing ?? {
      ...requested,
      idempotencyKey: crypto.randomUUID(),
    };
    pendingStartRef.current = pending;
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setTransportState("starting");
    setTransportError(null);
    try {
      const next = pending.kind === "sync"
        ? await createWalletCaseSync(
            caseId,
            pending.request,
            pending.idempotencyKey,
            controller.signal,
          )
        : pending.kind === "schedule"
          ? await runWalletCaseBackfillSchedule(
              caseId,
              pending.schedule,
              pending.idempotencyKey,
              controller.signal,
            )
        : pending.continuationPlanPublicId === null
          ? await resumeWalletCaseStreamCheckpoint(
              caseId,
              pending.checkpointPublicId,
              pending.idempotencyKey,
              controller.signal,
            )
          : await resumeWalletCaseContinuationPlan(
              caseId,
              pending.continuationPlanPublicId,
              pending.checkpointPublicId,
              pending.pageBudget ?? 1,
              pending.idempotencyKey,
              controller.signal,
            );
      pendingStartRef.current = null;
      acceptSync(next);
      if (isActiveWalletCaseSync(next)) setTransportState("polling");
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof WalletCaseApiError && error.activeSyncPublicId) {
        try {
          const active = await getWalletCaseSync(
            caseId,
            error.activeSyncPublicId,
            controller.signal,
          );
          pendingStartRef.current = null;
          acceptSync(active);
          if (isActiveWalletCaseSync(active)) setTransportState("polling");
          return;
        } catch (recoveryError) {
          if (controller.signal.aborted) return;
          setTransportError(errorMessage(recoveryError, "Could not resume the active sync."));
        }
      } else {
        if (error instanceof WalletCaseApiError && !error.retryable) {
          pendingStartRef.current = null;
        }
        setTransportError(errorMessage(error, "Could not start synchronization."));
      }
      setTransportState("idle");
    } finally {
      if (actionControllerRef.current === controller) actionControllerRef.current = null;
    }
  }, [acceptSync, caseId]);

  const start = useCallback(async (request: WalletCaseSyncRequest) => {
    await begin({ kind: "sync", request });
  }, [begin]);

  const resume = useCallback(async (checkpointPublicId: string) => {
    await begin({
      kind: "resume",
      continuationPlanPublicId: null,
      checkpointPublicId,
      pageBudget: null,
    });
  }, [begin]);

  const resumePlanned = useCallback(async (
    continuationPlanPublicId: string,
    checkpointPublicId: string,
    pageBudget = 1,
  ) => {
    await begin({
      kind: "resume",
      continuationPlanPublicId,
      checkpointPublicId,
      pageBudget,
    });
  }, [begin]);

  const runSchedule = useCallback(async (
    schedule: WalletCaseBackfillScheduleResponse,
  ) => {
    await begin({ kind: "schedule", schedule });
  }, [begin]);

  const retryPending = useCallback(async () => {
    const pending = pendingStartRef.current;
    if (!pending) return;
    if (pending.kind === "sync") {
      await begin({ kind: "sync", request: pending.request });
    } else if (pending.kind === "schedule") {
      await begin({ kind: "schedule", schedule: pending.schedule });
    } else {
      await begin({
        kind: "resume",
        continuationPlanPublicId: pending.continuationPlanPublicId,
        checkpointPublicId: pending.checkpointPublicId,
        pageBudget: pending.pageBudget,
      });
    }
  }, [begin]);

  const retry = useCallback(async () => {
    const current = syncRef.current;
    if (!current || isActiveWalletCaseSync(current)) return;
    pendingStartRef.current = null;
    if (
      current.requested_scope.mode === "resume" &&
      current.requested_scope.source_checkpoint_public_id
    ) {
      await begin({
        kind: "resume",
        continuationPlanPublicId: current.requested_scope.continuation_plan_public_id,
        checkpointPublicId: current.requested_scope.source_checkpoint_public_id,
        pageBudget: current.requested_scope.continuation_plan_public_id === null
          ? null
          : current.requested_scope.resume_page_budget ?? 1,
      });
      return;
    }
    const incremental = current.requested_scope.mode === "incremental";
    await start({
      mode: incremental ? "incremental" : "bounded",
      time_window: incremental ? "24h" : current.requested_scope.time_window,
      ...(!incremental && current.requested_scope.time_window === "custom"
        ? {
            custom_start: current.requested_scope.start_at,
            custom_end: current.requested_scope.end_at,
          }
        : {}),
      surfaces: [...current.requested_scope.surfaces],
    });
  }, [begin, start]);

  const cancel = useCallback(async () => {
    const current = syncRef.current;
    if (!isActiveWalletCaseSync(current) || !current || actionControllerRef.current) return;
    pollControllerRef.current?.abort();
    const controller = new AbortController();
    actionControllerRef.current = controller;
    setTransportState("cancelling");
    setTransportError(null);
    try {
      const next = await cancelWalletCaseSync(
        caseId,
        current.public_id,
        controller.signal,
      );
      acceptSync(next);
      if (isActiveWalletCaseSync(next)) setTransportState("polling");
    } catch (error) {
      if (!controller.signal.aborted) {
        setTransportError(errorMessage(error, "Could not request cancellation."));
        setTransportState("reconnecting");
      }
    } finally {
      if (actionControllerRef.current === controller) actionControllerRef.current = null;
      if (!controller.signal.aborted) setPollEpoch((value) => value + 1);
    }
  }, [acceptSync, caseId]);

  const checkNow = useCallback(() => {
    if (!isActiveWalletCaseSync(syncRef.current)) return;
    forceImmediatePollRef.current = true;
    if (pollControllerRef.current) pollControllerRef.current.abort();
    else setPollEpoch((value) => value + 1);
  }, []);

  return {
    sync,
    transportState,
    transportError,
    start,
    resume,
    resumePlanned,
    runSchedule,
    retryPending,
    retry,
    cancel,
    checkNow,
  };
}
