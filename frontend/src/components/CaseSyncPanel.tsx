import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  ClockCountdown,
  SpinnerGap,
  StopCircle,
  WarningCircle,
} from "@phosphor-icons/react";

import type { WalletCaseSync, WalletCaseSyncRequest } from "../walletCase";
import {
  isActiveWalletCaseSync,
  type WalletCaseSyncJobController,
} from "../useWalletCaseSyncJob";

interface CaseSyncPanelProps {
  controller: WalletCaseSyncJobController;
  hasSnapshot: boolean;
  defaultRequest: WalletCaseSyncRequest;
}

function stageLabel(sync: WalletCaseSync): string {
  if (sync.stage === "retry_wait") return "Waiting to retry";
  const labels: Record<string, string> = {
    queued: "Queued safely",
    validating: "Validating case scope",
    ingesting: sync.requested_scope.mode === "resume"
      ? "Continuing provider stream"
      : sync.requested_scope.mode === "incremental"
        ? "Acquiring forward overlap"
        : "Acquiring bounded evidence",
    finalizing: "Publishing the snapshot",
    cancelling: "Cancellation requested",
    starting: "Preparing bounded sync",
    fetching: "Requesting provider data",
    normalizing: "Normalizing evidence",
    persisting: "Saving the snapshot",
    completed: "Snapshot ready",
    completed_with_limitations: "Snapshot ready with limitations",
    failed: "Sync failed",
    cancelled: "Sync cancelled",
  };
  return labels[sync.stage] ?? sync.stage.replace(/_/g, " ");
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function isTerminalFailure(sync: WalletCaseSync | null): boolean {
  return sync?.state === "failed" || sync?.state === "cancelled";
}

function modeLabel(mode: WalletCaseSync["requested_scope"]["mode"]): string {
  if (mode === "resume") return "Checkpoint continuation";
  if (mode === "incremental") return "Incremental refresh";
  return "Bounded synchronization";
}

export default function CaseSyncPanel({
  controller,
  hasSnapshot,
  defaultRequest,
}: CaseSyncPanelProps) {
  const { sync, transportState, transportError } = controller;
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const cancelTriggerRef = useRef<HTMLButtonElement>(null);
  const keepSyncingRef = useRef<HTMLButtonElement>(null);
  const restoreCancelFocusRef = useRef(false);
  const active = isActiveWalletCaseSync(sync);
  const busy = transportState === "starting" || transportState === "cancelling";
  const nextIsIncremental = defaultRequest.mode === "incremental";
  const actionLabel = nextIsIncremental ? "Refresh incrementally" : "Sync last 24 hours";

  useEffect(() => {
    restoreCancelFocusRef.current = false;
    setConfirmingCancel(false);
  }, [sync?.public_id, sync?.cancel_requested, sync?.state]);

  useEffect(() => {
    if (confirmingCancel) {
      keepSyncingRef.current?.focus();
    } else if (restoreCancelFocusRef.current) {
      restoreCancelFocusRef.current = false;
      cancelTriggerRef.current?.focus();
    }
  }, [confirmingCancel]);

  if (!sync) {
    return (
      <section className="case-sync-panel" aria-labelledby="case-sync-title">
        <div className="case-sync-panel-heading">
          <div>
            <span className="eyebrow">{nextIsIncremental ? "Incremental refresh" : "Bounded synchronization"}</span>
            <h2 id="case-sync-title">Build the first usable snapshot</h2>
            <p>Fetch the selected 24-hour interval. This does not claim complete wallet history.</p>
          </div>
          <button
            className="button-primary case-sync-button"
            type="button"
            disabled={busy}
            onClick={() => void controller.start(defaultRequest)}
          >
            {transportState === "starting" ? (
              <SpinnerGap className="spin" size={18} />
            ) : (
              <ArrowClockwise size={18} />
            )}
            {transportState === "starting" ? "Starting safely…" : actionLabel}
          </button>
        </div>
        {transportError && (
          <div className="case-sync-message is-error" role="alert">
            <WarningCircle size={18} weight="fill" />
            <span>{transportError}</span>
            <button type="button" onClick={() => void controller.start(defaultRequest)}>
              Try again
            </button>
          </div>
        )}
      </section>
    );
  }

  const progressKnown = sync.progress.total !== null;
  const progressText = progressKnown
    ? `${sync.progress.current} of ${sync.progress.total}`
    : `${sync.progress.current} completed`;
  const failedMessage = sync.error?.message_safe ?? (
    sync.state === "cancelled" ? "This synchronization was cancelled safely." : null
  );
  const displayedMode = active || isTerminalFailure(sync)
    ? sync.requested_scope.mode
    : defaultRequest.mode;

  return (
    <section className={`case-sync-panel is-${sync.state}`} aria-labelledby="case-sync-title">
      <div className="case-sync-panel-heading">
        <div>
          <span className="eyebrow">{modeLabel(displayedMode)}</span>
          <h2 id="case-sync-title">{stageLabel(sync)}</h2>
          <p>{sync.message}</p>
        </div>
        {!active && !isTerminalFailure(sync) && (
          <button
            className="button-primary case-sync-button"
            type="button"
            disabled={busy}
            onClick={() => void controller.start(defaultRequest)}
          >
            {transportState === "starting" ? (
              <SpinnerGap className="spin" size={18} />
            ) : (
              <ArrowClockwise size={18} />
            )}
            {transportState === "starting" ? "Starting safely…" : actionLabel}
          </button>
        )}
      </div>

      {active && (
        <div className="case-sync-progress-block">
          <div className="case-sync-progress-copy" role="status" aria-live="polite">
            <span>
              {transportState === "reconnecting" ? "Reconnecting" : stageLabel(sync)}
            </span>
            <strong>{progressText}</strong>
          </div>
          {progressKnown ? (
            <progress
              aria-label="Synchronization progress"
              max={sync.progress.total ?? undefined}
              value={sync.progress.current}
            />
          ) : (
            <progress aria-label="Synchronization progress" />
          )}
        </div>
      )}

      {sync.retry && (
        <div className="case-sync-message is-waiting" role="status" aria-live="polite">
          <ClockCountdown size={19} />
          <span>
            <strong>Attempt {sync.retry.attempt} of {sync.retry.max_attempts} did not complete</strong>
            {sync.retry.message_safe} Retry scheduled after {formatDate(sync.retry.retry_at)}.
          </span>
        </div>
      )}

      {active && hasSnapshot && (
        <div className="case-sync-message is-snapshot" role="status">
          <CheckCircle size={19} />
          <span>The previous usable snapshot stays visible until this sync publishes a new one.</span>
        </div>
      )}

      {!active && !isTerminalFailure(sync) && hasSnapshot && nextIsIncremental && (
        <div className="case-sync-message is-snapshot">
          <ArrowClockwise size={19} />
          <span>The next refresh starts 15 minutes before this snapshot ends, then acquires only the forward interval. The composed snapshot still does not prove full wallet history.</span>
        </div>
      )}

      {transportError && (
        <div
          className={`case-sync-message ${active ? "is-waiting" : "is-error"}`}
          role={active ? "status" : "alert"}
          aria-live={active ? "polite" : undefined}
        >
          <WarningCircle size={19} />
          <span>{transportError}</span>
          <button
            type="button"
            onClick={active
              ? controller.checkNow
              : () => void controller.retryPending()}
          >
            {active ? "Check now" : "Try again"}
          </button>
        </div>
      )}

      {failedMessage && (
        <div className="case-sync-message is-error" role="alert">
          <WarningCircle size={19} weight="fill" />
          <span>{failedMessage}</span>
        </div>
      )}

      {active && sync.cancel_requested && (
        <div className="case-sync-message is-waiting" role="status" aria-live="polite">
          <StopCircle size={19} />
          <span>
            Cancellation requested. The server will stop safely after the current provider acquisition returns.
          </span>
        </div>
      )}

      <div className="case-sync-actions">
        {active && !sync.cancel_requested && !confirmingCancel && (
          <button
            ref={cancelTriggerRef}
            className="button-secondary"
            type="button"
            disabled={busy}
            onClick={() => setConfirmingCancel(true)}
          >
            <StopCircle size={17} /> Cancel sync
          </button>
        )}
        {active && !sync.cancel_requested && confirmingCancel && (
          <div className="case-cancel-confirm" role="group" aria-label="Confirm sync cancellation">
            <p>Stop this job? The current provider acquisition will return safely first.</p>
            <button
              ref={keepSyncingRef}
              type="button"
              className="button-secondary"
              onClick={() => {
                restoreCancelFocusRef.current = true;
                setConfirmingCancel(false);
              }}
            >
              Keep syncing
            </button>
            <button
              type="button"
              className="button-danger"
              disabled={transportState === "cancelling"}
              onClick={() => void controller.cancel()}
            >
              {transportState === "cancelling" ? "Requesting…" : "Confirm cancellation"}
            </button>
          </div>
        )}
        {isTerminalFailure(sync) && (
          <button
            type="button"
            className="button-primary"
            disabled={busy}
            onClick={() => void controller.retry()}
          >
            {transportState === "starting" ? (
              <SpinnerGap className="spin" size={17} />
            ) : (
              <ArrowClockwise size={17} />
            )}
            {transportState === "starting"
              ? "Starting safely…"
              : sync.requested_scope.mode === "incremental"
                ? "Retry refresh"
                : sync.requested_scope.mode === "resume"
                  ? "Retry continuation"
                : "Retry same scope"}
          </button>
        )}
      </div>
    </section>
  );
}
