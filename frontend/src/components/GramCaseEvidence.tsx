import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  Check,
  CheckCircle,
  Clock,
  Database,
  FileText,
  Info,
  LockKey,
  ShieldCheck,
  SpinnerGap,
  StopCircle,
  WarningCircle,
  XCircle,
} from "@phosphor-icons/react";

import {
  caseEvidenceSearch,
  EMPTY_CASE_EVIDENCE_URL_STATE,
  readCaseEvidenceUrlState,
  type CaseEvidenceUrlState,
} from "../caseEvidenceQuery";
import { caseEvidencePath } from "../caseRouting";
import type { WalletCase } from "../walletCase";
import {
  isActiveWalletCaseEvidenceVerification,
  walletCaseEvidenceEligibility,
  type WalletCaseEvidenceLevel,
  type WalletCaseEvidenceVerification,
  type WalletCaseEvidenceStepCode,
} from "../walletCaseEvidence";
import { useWalletCaseEvidence } from "../useWalletCaseEvidence";
import type { WalletCaseReport } from "../walletCaseReport";
import { walletCaseReportExportUrl } from "../walletCaseReportApi";

export default function GramCaseEvidence({
  walletCase,
  onOpenActivity,
}: {
  walletCase: WalletCase;
  onOpenActivity: (snapshotId: string | null, activityId: string | null) => void;
}) {
  const initial = useMemo(readCaseEvidenceUrlState, []);
  const [urlState, setUrlState] = useState(initial.state);
  const [queryError, setQueryError] = useState(initial.error);
  const [confirmingCancel, setConfirmingCancel] = useState(false);
  const cancelTrigger = useRef<HTMLButtonElement>(null);
  const keepVerifying = useRef<HTMLButtonElement>(null);
  const restoreCancelFocus = useRef(false);
  const focusAfterVerificationStart = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const verificationHeadingRef = useRef<HTMLHeadingElement>(null);

  const commitUrlState = useCallback((next: CaseEvidenceUrlState, replace = false) => {
    const path = `${caseEvidencePath(walletCase.public_id)}${caseEvidenceSearch(next)}`;
    window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    setQueryError(null);
    setUrlState(next);
  }, [walletCase.public_id]);

  const controller = useWalletCaseEvidence({
    caseId: walletCase.public_id,
    urlState,
    enabled: queryError === null,
    onSnapshotPinned: useCallback((snapshotId: string) => {
      setUrlState((current) => {
        if (current.snapshot !== null) return current;
        const next = { ...current, snapshot: snapshotId };
        window.history.replaceState({}, "", `${caseEvidencePath(walletCase.public_id)}${caseEvidenceSearch(next)}`);
        return next;
      });
    }, [walletCase.public_id]),
    onVerificationPinned: useCallback((verificationId: string, replace: boolean) => {
      setUrlState((current) => {
        if (current.snapshot === null || current.activity === null || current.verification === verificationId) return current;
        const next = { ...current, verification: verificationId };
        window.history[replace ? "replaceState" : "pushState"]({}, "", `${caseEvidencePath(walletCase.public_id)}${caseEvidenceSearch(next)}`);
        return next;
      });
    }, [walletCase.public_id]),
  });

  useEffect(() => {
    function restore() {
      const next = readCaseEvidenceUrlState();
      setQueryError(next.error);
      setUrlState(next.state);
      setConfirmingCancel(false);
      window.setTimeout(() => headingRef.current?.focus(), 0);
    }
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    setConfirmingCancel((current) => {
      if (current) restoreCancelFocus.current = true;
      return false;
    });
  }, [controller.verification?.public_id, controller.verification?.state]);

  useEffect(() => {
    if (confirmingCancel) keepVerifying.current?.focus();
    else if (restoreCancelFocus.current) {
      restoreCancelFocus.current = false;
      (cancelTrigger.current ?? verificationHeadingRef.current)?.focus();
    }
  }, [confirmingCancel]);

  useEffect(() => {
    if (!focusAfterVerificationStart.current) return;
    if (controller.verification?.public_id) {
      focusAfterVerificationStart.current = false;
      verificationHeadingRef.current?.focus();
      return;
    }
    if (controller.transportState === "idle" && controller.transportError) {
      focusAfterVerificationStart.current = false;
    }
  }, [controller.transportError, controller.transportState, controller.verification?.public_id]);

  if (queryError) {
    return (
      <section className="case-state-panel is-error" role="alert">
        <WarningCircle size={27} weight="fill" />
        <div><h2>Evidence URL is invalid</h2><p>{queryError}</p></div>
        <button type="button" className="button-secondary" onClick={() => commitUrlState(EMPTY_CASE_EVIDENCE_URL_STATE, true)}>
          Reset Evidence view <ArrowClockwise size={17} />
        </button>
      </section>
    );
  }

  const snapshot = controller.catalog?.snapshot ?? null;
  const item = controller.activityDetail?.item ?? null;
  const eligibility = walletCaseEvidenceEligibility(item);
  const verificationAvailable = controller.catalog?.readiness.transaction_verification_available === true;
  const runtimeLimitation = controller.catalog?.limitations.find((entry) => entry.code === "evidence_runner_unavailable");
  const canVerify = eligibility.eligible && verificationAvailable && walletCase.data_environment === "live" && snapshot?.data_mode === "real";
  const verification = controller.verification;
  const active = isActiveWalletCaseEvidenceVerification(verification);
  const busy = controller.transportState === "starting" || controller.transportState === "cancelling";
  const existingForActivity = controller.catalog?.verifications.filter(
    (entry) => entry.activity_public_id === urlState.activity,
  ).length ?? 0;
  const caseReport = controller.report?.report ?? null;

  function selectVerification(entry: WalletCaseEvidenceVerification) {
    commitUrlState({ snapshot: entry.snapshot_public_id, activity: entry.activity_public_id, verification: entry.public_id });
  }

  return (
    <div className="case-evidence-page">
      <section className="case-evidence-toolbar" aria-labelledby="case-evidence-title">
        <div>
          <span className="eyebrow">Evidence workspace</span>
          <h2 ref={headingRef} tabIndex={-1} id="case-evidence-title">Verify one transaction without inflating trust</h2>
          <p>Trace capture, local BOC checks and block inclusion progress belong here. Activity stays focused on scanning the pinned snapshot.</p>
        </div>
        <button type="button" className="button-secondary" onClick={controller.reload} disabled={controller.catalogLoading}>
          <ArrowClockwise className={controller.catalogLoading ? "spin" : undefined} size={17} /> Refresh
        </button>
      </section>

      {controller.catalogError && <InlineError message={controller.catalogError} onRetry={controller.reload} />}
      {controller.reportError && <InlineError message={controller.reportError} onRetry={controller.reload} />}

      {controller.catalogLoading && !controller.catalog ? (
        <section className="case-state-panel" aria-live="polite"><SpinnerGap className="spin" size={25} /><div><h2>Loading Evidence</h2><p>Reading the pinned snapshot and durable verification catalog…</p></div></section>
      ) : (
        <>
          <section className="case-evidence-trust" aria-label="Evidence trust boundaries">
            <TrustFact label="Pinned snapshot" value={snapshot ? short(snapshot.public_id) : "Not available"} icon={<Database size={19} />} />
            <TrustFact label="Data origin" value={snapshot?.data_mode === "real" ? "Live provider" : snapshot?.data_mode === "mock" ? "Demo fixture" : "Not synchronized"} icon={<Info size={19} />} />
            <TrustFact label="Returned snapshot-history peak" value={levelLabel(controller.catalog?.readiness.highest_evidence_level ?? null)} icon={<ShieldCheck size={19} />} />
            <TrustFact
              label="Case report"
              value={controller.reportLoading ? "Building revision…" : caseReport ? reportAssuranceLabel(caseReport.assurance_level) : "Unavailable"}
              icon={<FileText size={19} />}
              warning={!caseReport || caseReport.assurance_level !== "canonical"}
            />
          </section>

          {!snapshot ? (
            <section className="case-evidence-empty">
              <Database size={29} />
              <h2>No usable snapshot yet</h2>
              <p>Run a bounded synchronization from Summary before selecting transaction evidence.</p>
            </section>
          ) : urlState.activity === null ? (
            <section className="case-evidence-empty">
              <ShieldCheck size={30} />
              <h2>Choose a transaction from Activity</h2>
              <p>Open a transaction detail and check verification availability. Transfers, swaps and demo fixtures cannot enter this proof pipeline.</p>
              <button type="button" className="button-primary" onClick={() => onOpenActivity(snapshot.public_id, null)}>
                Open Activity <ArrowRight size={17} />
              </button>
            </section>
          ) : (
            <section className={`case-evidence-selection ${canVerify ? "is-eligible" : "is-ineligible"}`} aria-labelledby="selected-evidence-activity">
              <header>
                <span className="case-evidence-selection-icon">{canVerify ? <ShieldCheck size={25} /> : <LockKey size={25} />}</span>
                <div>
                  <span className="eyebrow">Selected Activity</span>
                  <h2 id="selected-evidence-activity">{controller.activityLoading ? "Checking transaction eligibility…" : item ? activityTitle(item.kind, item.transaction.hash) : "Selected Activity unavailable"}</h2>
                  <p>{controller.activityLoading ? "Loading the sanitized, snapshot-pinned Activity detail." : controller.activityError ?? (
                    eligibility.eligible && (walletCase.data_environment !== "live" || snapshot?.data_mode !== "real")
                      ? "Demo fixtures cannot enter the live transaction proof pipeline."
                      : eligibility.eligible && !verificationAvailable
                        ? runtimeLimitation?.message ?? "Transaction verification is temporarily unavailable."
                        : eligibility.message
                  )}</p>
                </div>
                <span className={`case-evidence-eligibility ${canVerify ? "is-ready" : "is-locked"}`}>
                  {canVerify ? <CheckCircle size={15} weight="fill" /> : <LockKey size={15} />}
                  {canVerify ? "Eligible" : eligibility.eligible ? "Unavailable" : "Ineligible"}
                </span>
              </header>

              {item && (
                <dl className="case-evidence-activity-facts">
                  <div><dt>Activity type</dt><dd>{item.kind}</dd></div>
                  <div><dt>Origin</dt><dd>{item.provenance.data_origin === "provider_observed" ? "Provider observed" : "Demo fixture"}</dd></div>
                  <div><dt>Identity</dt><dd>{item.provenance.identity_assurance.replace(/_/g, " ")}</dd></div>
                  <div><dt>Transaction link</dt><dd>{item.transaction.linkage}</dd></div>
                </dl>
              )}

              <div className="case-evidence-selection-actions">
                <button type="button" className="button-secondary" onClick={() => onOpenActivity(snapshot.public_id, urlState.activity)}>
                  Back to Activity
                </button>
                {canVerify && !active && (
                  <button type="button" className="button-primary" disabled={busy || controller.verificationLoading} onClick={() => {
                    focusAfterVerificationStart.current = true;
                    void (verification ? controller.retry() : controller.start());
                  }}>
                    {controller.transportState === "starting" ? <SpinnerGap className="spin" size={17} /> : <ShieldCheck size={17} />}
                    {controller.transportState === "starting" ? "Starting safely…" : verification ? "Run a new verification" : existingForActivity ? "Resume or verify again" : "Verify transaction evidence"}
                  </button>
                )}
              </div>
            </section>
          )}

          {controller.activityError && <InlineError message={controller.activityError} onRetry={controller.reload} />}
          {controller.transportError && <InlineError message={controller.transportError} onRetry={active ? controller.checkNow : controller.reload} />}

          {(verification || controller.verificationLoading) && (
            <section className="case-evidence-progress" aria-labelledby="evidence-progress-title">
              {controller.verificationLoading && !verification ? (
                <div className="case-evidence-progress-loading" role="status"><SpinnerGap className="spin" size={22} /> Loading durable verification…</div>
              ) : verification ? (
                <>
                  <header>
                    <div>
                      <span className="eyebrow">Durable verification</span>
                      <h2 ref={verificationHeadingRef} tabIndex={-1} id="evidence-progress-title">{stageLabel(verification)}</h2>
                      <p>{verification.message}</p>
                    </div>
                    <EvidenceStateBadge verification={verification} transportState={controller.transportState} />
                  </header>

                  <div className="case-evidence-progress-meter" role="status" aria-live="polite">
                    <div><span>{verification.progress.current} of {verification.progress.total} evidence stages complete</span><strong>{levelLabel(verification.highest_evidence_level)}</strong></div>
                    <progress aria-label="Evidence verification progress" max={verification.progress.total} value={verification.progress.current} />
                  </div>

                  {verification.retry && (
                    <div className="case-sync-message is-waiting" role="status" aria-live="polite">
                      <Clock size={19} /><span><strong>Retry {verification.retry.attempt} of {verification.retry.max_attempts}</strong>{verification.retry.message_safe} Next attempt after {formatDate(verification.retry.retry_at)}.</span>
                    </div>
                  )}
                  {verification.error && (
                    <div className="case-sync-message is-error" role="alert"><WarningCircle size={19} /><span><strong>{humanize(verification.error.code)}</strong>{verification.error.message_safe}</span></div>
                  )}

                  <ol className="case-evidence-steps">
                    {verification.steps.map((step, index) => (
                      <li key={step.code} className={step.state === "succeeded" ? "is-complete" : verification.progress.current === index && active ? "is-current" : "is-pending"}>
                        <span>{step.state === "succeeded" ? <Check size={17} weight="bold" /> : index + 1}</span>
                        <div><strong>{stepLabel(step.code)}</strong><small>{step.state === "succeeded" ? levelLabel(step.evidence_level) : "Pending"}</small></div>
                        <code title={step.evidence_digest_sha256 ?? undefined}>{step.evidence_digest_sha256 ? short(step.evidence_digest_sha256) : "—"}</code>
                      </li>
                    ))}
                  </ol>

                  {verification.limitations.length > 0 && (
                    <div className="case-evidence-job-limitations"><strong>Verification boundaries</strong><ul>{verification.limitations.map((item) => <li key={item.code}>{item.message}</li>)}</ul></div>
                  )}

                  {verification.inclusion_provenance && (
                    <InclusionProvenancePanel verification={verification} />
                  )}
                  {verification.result && <EvidenceResult verification={verification} />}

                  {active && (
                    <div className="case-sync-actions">
                      {!verification.cancel_requested && !confirmingCancel && (
                        <button ref={cancelTrigger} type="button" className="button-secondary" disabled={busy} onClick={() => setConfirmingCancel(true)}><StopCircle size={17} /> Cancel verification</button>
                      )}
                      {confirmingCancel && (
                        <div className="case-cancel-confirm" role="group" aria-label="Confirm Evidence cancellation">
                          <p>Completed artifacts stay recorded; pending stages stop at the next safe boundary.</p>
                          <button ref={keepVerifying} type="button" className="button-secondary" onClick={() => { restoreCancelFocus.current = true; setConfirmingCancel(false); }}>Keep verifying</button>
                          <button type="button" className="button-danger" disabled={busy} onClick={() => {
                            void controller.cancel().finally(() => {
                              setConfirmingCancel(false);
                              window.setTimeout(() => verificationHeadingRef.current?.focus(), 0);
                            });
                          }}>{busy ? <SpinnerGap className="spin" size={17} /> : <StopCircle size={17} />} Confirm cancel</button>
                        </div>
                      )}
                      {verification.cancel_requested && <span className="case-evidence-cancel-pending" role="status"><StopCircle size={17} /> Cancellation requested</span>}
                    </div>
                  )}
                </>
              ) : null}
            </section>
          )}

          {controller.catalog && controller.catalog.verifications.length > 0 && (
            <section className="case-evidence-history" aria-labelledby="evidence-history-title">
              <header><div><span className="eyebrow">Snapshot history</span><h2 id="evidence-history-title">Stored verification attempts</h2></div><span>{controller.catalog.aggregate.total} total</span></header>
              <ul>{controller.catalog.verifications.map((entry) => (
                <li key={entry.public_id}>
                  <button type="button" aria-current={entry.public_id === urlState.verification ? "true" : undefined} onClick={() => selectVerification(entry)}>
                    <span className={`case-evidence-history-state is-${entry.state}`}>{stateIcon(entry.state)}</span>
                    <span><strong>{stageLabel(entry)}</strong><small>Activity {short(entry.activity_public_id)} · Attempt {short(entry.public_id)} · {formatDate(entry.updated_at)}</small></span>
                    <span>{levelLabel(entry.highest_evidence_level)}<ArrowRight size={16} /></span>
                  </button>
                </li>
              ))}</ul>
              {controller.catalog.truncated && <p>Showing and revalidating the latest {controller.catalog.aggregate.returned_count} of {controller.catalog.aggregate.total} attempts for this snapshot. State and trust-level counts cover this returned window only.</p>}
            </section>
          )}

          <CaseReportPanel
            report={caseReport}
            loading={controller.reportLoading}
            caseId={walletCase.public_id}
            snapshotId={snapshot?.public_id ?? null}
          />

          {controller.catalog && controller.catalog.limitations.length > 0 && (
            <section className="case-limitations">
              <header><WarningCircle size={22} weight="duotone" /><div><span className="eyebrow">Known limitations</span><h2>What this Evidence view does not prove</h2></div></header>
              <ul>{controller.catalog.limitations.map((item) => <li key={item.code}><strong>{humanize(item.code)}</strong><span>{item.message}</span></li>)}</ul>
            </section>
          )}
        </>
      )}
    </div>
  );
}

function CaseReportPanel({
  report,
  loading,
  caseId,
  snapshotId,
}: {
  report: WalletCaseReport | null;
  loading: boolean;
  caseId: string;
  snapshotId: string | null;
}) {
  if (loading && !report) {
    return (
      <section className="case-evidence-report-boundary" aria-labelledby="case-report-boundary-title" aria-live="polite">
        <SpinnerGap className="spin" size={24} />
        <div><span className="eyebrow">Case report</span><h2 id="case-report-boundary-title">Building the pinned report revision</h2><p>Activity and stored Evidence are being revalidated against one snapshot.</p></div>
        <span>Loading</span>
      </section>
    );
  }
  if (!report || snapshotId === null) {
    return (
      <section className="case-evidence-report-boundary" aria-labelledby="case-report-boundary-title">
        <FileText size={24} />
        <div><span className="eyebrow">Case report</span><h2 id="case-report-boundary-title">Report unavailable</h2><p>A synchronized snapshot is required before GRAM Scope can build a content-addressed report.</p></div>
        <span>Not synchronized</span>
      </section>
    );
  }
  return (
    <section className="case-evidence-report-boundary is-report-ready" aria-labelledby="case-report-boundary-title">
      <FileText size={24} />
      <div>
        <span className="eyebrow">Content-addressed Case Report</span>
        <h2 id="case-report-boundary-title">{reportAssuranceLabel(report.assurance_level)}</h2>
        <p>
          {report.activity_revision.aggregate.total_items} Activity records and {report.evidence_revision.returned_revalidated} revalidated Evidence attempts are bound to snapshot {short(report.snapshot_public_id)}. This revision does not establish complete wallet history, cost basis or PnL.
        </p>
        <dl className="case-definition-list">
          <div><dt>Report ID</dt><dd><code title={report.public_id}>{short(report.public_id)}</code></dd></div>
          <div><dt>Content hash</dt><dd><code title={report.content_hash_sha256}>{short(report.content_hash_sha256)}</code></dd></div>
          <div><dt>Canonical gate</dt><dd>{report.canonical_gate.eligible ? "All published gates met" : `${report.canonical_gate.unmet.length} gates remain`}</dd></div>
          <div><dt>Evidence coverage</dt><dd>{report.evidence_revision.selected_activity_count} selected activities · {report.evidence_revision.chain_inclusion_proven_activity_count} chain proven</dd></div>
        </dl>
        {report.unverified_claims.length > 0 && (
          <div className="case-evidence-job-limitations">
            <strong>Claims this revision does not verify</strong>
            <ul>{report.unverified_claims.map((claim) => <li key={claim.code}>{claim.message}{claim.affected_count === null ? "" : ` (${claim.affected_count})`}</li>)}</ul>
          </div>
        )}
      </div>
      <a className="button-secondary" href={walletCaseReportExportUrl(caseId, snapshotId)} download>Export JSON</a>
    </section>
  );
}

function InlineError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="case-inline-error" role="alert"><WarningCircle size={18} weight="fill" /><span>{message}</span><button type="button" onClick={onRetry}>Try again</button></div>;
}

function TrustFact({ label, value, icon, warning = false }: { label: string; value: string; icon: ReactNode; warning?: boolean }) {
  return <div className={warning ? "is-warning" : undefined}>{icon}<span><small>{label}</small><strong title={value}>{value}</strong></span></div>;
}

function EvidenceStateBadge({ verification, transportState }: { verification: WalletCaseEvidenceVerification; transportState: string }) {
  const reconnecting = transportState === "reconnecting";
  return (
    <span className={`case-evidence-state is-${verification.state}`}>
      {reconnecting || isActiveWalletCaseEvidenceVerification(verification) ? <SpinnerGap className="spin" size={15} /> : stateIcon(verification.state)}
      {reconnecting ? "Reconnecting" : humanize(verification.state)}
    </span>
  );
}

function InclusionProvenancePanel({ verification }: { verification: WalletCaseEvidenceVerification }) {
  const inclusion = verification.inclusion_provenance;
  if (!inclusion) return null;
  return (
    <section className="case-evidence-result" aria-labelledby="evidence-inclusion-title">
      <header><ShieldCheck size={21} weight="fill" /><div><span className="eyebrow">Stored inclusion provenance</span><h3 id="evidence-inclusion-title">Pinned chain-verification boundary</h3></div></header>
      <dl className="case-definition-list">
        <div><dt>Pinned checkpoint</dt><dd>{inclusion.network} · #{inclusion.trusted_checkpoint.seqno}</dd></div>
        <div><dt>Checkpoint root</dt><dd><code>{inclusion.trusted_checkpoint.root_hash}</code></dd></div>
        <div><dt>Checkpoint file hash</dt><dd><code>{inclusion.trusted_checkpoint.file_hash}</code></dd></div>
        <div><dt>Verifier policy</dt><dd><code title={inclusion.verifier_policy_id}>{inclusion.verifier_policy_id}</code></dd></div>
      </dl>
      <div className="case-evidence-ledger-boundary" role="note"><Info size={18} /><p>Canonical block-chain inclusion was verified at capture against the pinned checkpoint above. The checkpoint-to-observed-head transcript was not persisted, so this result does not claim a replayable chain transcript.</p></div>
    </section>
  );
}

function EvidenceResult({ verification }: { verification: WalletCaseEvidenceVerification }) {
  const result = verification.result;
  if (!result) return null;
  return (
    <section className="case-evidence-result" aria-labelledby="evidence-artifact-title">
      <header><CheckCircle size={21} weight="fill" /><div><span className="eyebrow">Stored artifacts</span><h3 id="evidence-artifact-title">{verification.state === "succeeded" ? "Selected transaction proof completed" : "Partial evidence preserved"}</h3></div></header>
      <dl className="case-definition-list">
        <div><dt>Verification digest</dt><dd><code title={result.verification_digest_sha256}>{short(result.verification_digest_sha256)}</code></dd></div>
        <div><dt>Evidence level</dt><dd>{levelLabel(verification.highest_evidence_level)}</dd></div>
        <div><dt>Native ledger artifact</dt><dd>{result.native_ledger ? `${result.native_ledger.activity_count} selected native TON rows` : "Not available"}</dd></div>
        {result.native_ledger && <div><dt>Observed native flow</dt><dd>{formatNanoton(result.native_ledger.incoming_nanoton)} in · {formatNanoton(result.native_ledger.outgoing_nanoton)} out</dd></div>}
      </dl>
      {result.native_ledger && (
        <div className="case-evidence-ledger-boundary" role="note"><Info size={18} /><p>{result.native_ledger.message} This selected-evidence native TON artifact is not an authoritative all-activity ledger and does not establish complete wallet history, cost basis or PnL.</p></div>
      )}
    </section>
  );
}

function stateIcon(state: WalletCaseEvidenceVerification["state"]) {
  if (state === "succeeded") return <CheckCircle size={16} weight="fill" />;
  if (state === "partial") return <WarningCircle size={16} weight="fill" />;
  if (state === "failed" || state === "cancelled") return <XCircle size={16} weight="fill" />;
  return <Clock size={16} />;
}

function stageLabel(verification: WalletCaseEvidenceVerification): string {
  if (verification.state === "succeeded") return "Verification complete";
  if (verification.state === "partial") return "Partial evidence preserved";
  if (verification.state === "failed") return "Verification stopped";
  if (verification.state === "cancelled") return "Verification cancelled";
  const labels: Record<string, string> = {
    queued: "Queued safely",
    validating: "Validating transaction scope",
    capturing_trace: "Capturing transaction trace",
    verifying_bocs: "Verifying transaction BOCs locally",
    proving_inclusion: "Proving block inclusion",
    building_native_ledger: "Building selected native TON artifact",
    finalizing: "Finalizing evidence digests",
    retry_wait: "Waiting for a bounded retry",
  };
  return labels[verification.stage] ?? humanize(verification.stage);
}

function stepLabel(code: WalletCaseEvidenceStepCode): string {
  return {
    trace_capture: "Trace capture",
    boc_verification: "Local BOC verification",
    block_inclusion: "Block inclusion proof",
    native_ledger: "Selected native TON ledger artifact",
  }[code];
}

function levelLabel(level: WalletCaseEvidenceLevel | null): string {
  if (level === "chain_inclusion_proven") return "Chain inclusion proven";
  if (level === "locally_verified") return "Locally verified";
  if (level === "normalized") return "Normalized observation";
  return "No verification yet";
}

function reportAssuranceLabel(level: WalletCaseReport["assurance_level"]): string {
  if (level === "canonical") return "Canonical report";
  if (level === "partially_verified") return "Partially verified report";
  if (level === "normalized") return "Normalized report";
  return "Observed report";
}

function activityTitle(kind: string, hash: string | null): string {
  return kind === "transaction" && hash ? `Transaction ${short(hash)}` : `${humanize(kind)} Activity`;
}

function short(value: string): string {
  return value.length > 22 ? `${value.slice(0, 11)}…${value.slice(-8)}` : value;
}

function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/^./, (letter) => letter.toUpperCase());
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function formatNanoton(value: string): string {
  const units = BigInt(value);
  const whole = units / 1_000_000_000n;
  const fraction = (units % 1_000_000_000n).toString().padStart(9, "0").replace(/0+$/, "");
  return `${whole}${fraction ? `.${fraction}` : ""} TON`;
}
