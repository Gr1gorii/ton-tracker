import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import {
  ArrowClockwise,
  ClockCounterClockwise,
  Database,
  DownloadSimple,
  FileText,
  FloppyDisk,
  ShieldCheck,
  SpinnerGap,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

import {
  caseReportsSearch,
  EMPTY_CASE_REPORTS_URL_STATE,
  readCaseReportsUrlState,
  type CaseReportsUrlState,
} from "../caseReportsQuery";
import { caseReportsPath } from "../caseRouting";
import type { WalletCase } from "../walletCase";
import type { WalletCaseReport } from "../walletCaseReport";
import {
  walletCaseReportExportUrl,
  walletCaseReportRevisionExportUrl,
} from "../walletCaseReportApi";
import type { WalletCaseReportRevisionSummary } from "../walletCaseReportRevisions";
import { useWalletCaseReports } from "../useWalletCaseReports";

export default function GramCaseReports({ walletCase }: { walletCase: WalletCase }) {
  const initial = useMemo(readCaseReportsUrlState, []);
  const [urlState, setUrlState] = useState(initial.state);
  const [queryError, setQueryError] = useState(initial.error);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const detailHeadingRef = useRef<HTMLHeadingElement>(null);
  const focusedRevision = useRef<string | null>(null);

  const commitUrlState = useCallback((next: CaseReportsUrlState, replace = false) => {
    window.history[replace ? "replaceState" : "pushState"]({}, "", `${caseReportsPath(walletCase.public_id)}${caseReportsSearch(next)}`);
    setQueryError(null);
    setUrlState(next);
  }, [walletCase.public_id]);

  const controller = useWalletCaseReports({
    caseId: walletCase.public_id,
    urlState,
    enabled: queryError === null,
    onSnapshotPinned: useCallback((snapshotId: string) => {
      setUrlState((current) => {
        if (current.snapshot !== null) return current;
        const next = { snapshot: snapshotId, revision: null };
        window.history.replaceState({}, "", `${caseReportsPath(walletCase.public_id)}${caseReportsSearch(next)}`);
        return next;
      });
    }, [walletCase.public_id]),
    onRevisionCaptured: useCallback((revision: WalletCaseReportRevisionSummary) => {
      commitUrlState({ snapshot: revision.snapshot_public_id, revision: revision.public_id });
    }, [commitUrlState]),
  });

  useEffect(() => {
    function restore() {
      const next = readCaseReportsUrlState();
      setQueryError(next.error);
      setUrlState(next.state);
      window.setTimeout(() => headingRef.current?.focus(), 0);
    }
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    const revision = controller.detail?.revision.public_id ?? null;
    if (revision === null) {
      focusedRevision.current = null;
      return;
    }
    if (focusedRevision.current === revision) return;
    focusedRevision.current = revision;
    detailHeadingRef.current?.focus();
  }, [controller.detail]);

  if (queryError) {
    return (
      <section className="case-state-panel is-error" role="alert">
        <WarningCircle size={27} weight="fill" />
        <div><h2>Reports URL is invalid</h2><p>{queryError}</p></div>
        <button type="button" className="button-secondary" onClick={() => commitUrlState(EMPTY_CASE_REPORTS_URL_STATE, true)}>
          Reset Reports view <ArrowClockwise size={17} />
        </button>
      </section>
    );
  }

  const currentReport = controller.current?.report ?? null;
  const currentScopeError = currentReport && (
    currentReport.subject.network !== walletCase.network
    || currentReport.subject.data_environment !== walletCase.data_environment
    || currentReport.subject.wallet_account_canonical !== walletCase.canonical_wallet_key
  ) ? "Current Case Report does not match the open Wallet Case identity." : null;
  const detailReport = controller.detail?.report.report ?? null;
  const detailScopeError = detailReport && (
    detailReport.subject.network !== walletCase.network
    || detailReport.subject.data_environment !== walletCase.data_environment
    || detailReport.subject.wallet_account_canonical !== walletCase.canonical_wallet_key
  ) ? "Saved Case Report does not match the open Wallet Case identity." : null;

  function selectRevision(event: MouseEvent<HTMLAnchorElement>, revision: WalletCaseReportRevisionSummary) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    commitUrlState({ snapshot: revision.snapshot_public_id, revision: revision.public_id });
  }

  return (
    <div className="case-reports-page">
      <section className="case-findings-toolbar" aria-labelledby="case-reports-title">
        <div>
          <span className="eyebrow">Case Report history</span>
          <h2 ref={headingRef} tabIndex={-1} id="case-reports-title">Capture reproducible report revisions without rewriting history</h2>
          <p>Each saved revision preserves the exact validated public report for one pinned snapshot. Evidence may evolve later, so new states require an explicit new capture.</p>
        </div>
        <button type="button" className="button-secondary" onClick={() => { controller.reloadCurrent(); controller.reloadCatalog(); }} disabled={controller.currentLoading || controller.catalogLoading}>
          <ArrowClockwise className={controller.currentLoading || controller.catalogLoading ? "spin" : undefined} size={17} /> Refresh
        </button>
      </section>

      {(controller.currentError || currentScopeError) && <InlineError message={currentScopeError ?? controller.currentError!} onRetry={controller.reloadCurrent} />}
      {controller.captureError && <InlineError message={controller.captureError} onRetry={() => void controller.capture()} />}
      {controller.catalogError && <InlineError message={controller.catalogError} onRetry={controller.reloadCatalog} />}

      <section className="case-report-current" aria-labelledby="case-report-current-title">
        <header>
          <FileText size={23} />
          <div><span className="eyebrow">Current reproducible view</span><h2 id="case-report-current-title">Report at the pinned snapshot</h2></div>
        </header>
        {controller.currentLoading && !controller.current ? (
          <div className="case-reports-loading" role="status"><SpinnerGap className="spin" size={22} /><span>Revalidating current Activity and Evidence…</span></div>
        ) : !currentReport || currentScopeError ? (
          <div className="case-reports-empty"><Database size={27} /><strong>No report is ready</strong><p>Run a bounded synchronization before saving a Case Report revision.</p></div>
        ) : (
          <div className="case-report-current-body">
            <ReportFacts report={currentReport} />
            <div className="case-report-current-actions">
              <button type="button" className="button-primary" onClick={() => void controller.capture()} disabled={controller.capturing}>
                {controller.capturing ? <SpinnerGap className="spin" size={17} /> : <FloppyDisk size={17} />}
                {controller.capturing ? "Saving revision…" : "Save this revision"}
              </button>
              <a className="button-secondary" href={walletCaseReportExportUrl(walletCase.public_id, currentReport.snapshot_public_id)} download>
                <DownloadSimple size={17} /> Export current JSON
              </a>
            </div>
            <p className="case-report-boundary-copy">Saving is idempotent by the report content hash. This report does not establish complete wallet history, cost basis or PnL.</p>
          </div>
        )}
      </section>

      <section className="case-report-history" aria-labelledby="case-report-history-title">
        <header>
          <ClockCounterClockwise size={23} />
          <div><span className="eyebrow">Immutable captures</span><h2 id="case-report-history-title">Saved report revisions</h2></div>
          {controller.catalog && <strong>{controller.catalog.aggregate.total_revisions} saved</strong>}
        </header>
        {controller.catalogLoading && !controller.catalog ? (
          <div className="case-reports-loading" role="status"><SpinnerGap className="spin" size={22} /><span>Loading saved report history…</span></div>
        ) : !controller.catalog || controller.catalog.items.length === 0 ? (
          <div className="case-reports-empty"><ClockCounterClockwise size={27} /><strong>No saved revisions yet</strong><p>Use “Save this revision” to preserve the current content-addressed report.</p></div>
        ) : (
          <>
            <ul>
              {controller.catalog.items.map((revision) => {
                const selected = urlState.revision === revision.public_id;
                const href = `${caseReportsPath(walletCase.public_id)}${caseReportsSearch({ snapshot: revision.snapshot_public_id, revision: revision.public_id })}`;
                return (
                  <li key={revision.public_id}>
                    <a data-report-revision-id={revision.public_id} href={href} aria-current={selected ? "page" : undefined} onClick={(event) => selectRevision(event, revision)}>
                      <span className={`case-report-assurance is-${revision.assurance_level}`}>{assuranceLabel(revision.assurance_level)}</span>
                      <span><strong>{formatDate(revision.captured_at)}</strong><small>{revision.activity_count} Activity rows · {revision.evidence_attempt_count} Evidence attempts</small></span>
                      <code title={revision.public_id}>{short(revision.public_id)}</code>
                    </a>
                  </li>
                );
              })}
            </ul>
            {controller.catalog.page.has_more && (
              <button type="button" className="button-secondary case-report-load-more" onClick={() => void controller.loadMore()} disabled={controller.catalogLoading}>
                {controller.catalogLoading && <SpinnerGap className="spin" size={16} />} Load more saved revisions
              </button>
            )}
          </>
        )}
        {controller.catalog && <p>{controller.catalog.limitations.find((item) => item.code === "report_revisions_are_explicit_captures")?.message}</p>}
      </section>

      {urlState.revision !== null && (
        <section className="case-report-detail" aria-labelledby="case-report-detail-title">
          <header>
            <ShieldCheck size={23} />
            <div><span className="eyebrow">Saved revision detail</span><h2 ref={detailHeadingRef} data-route-detail-focus tabIndex={-1} id="case-report-detail-title">Exact stored public report</h2></div>
            <button type="button" className="case-report-detail-close" aria-label="Close saved revision" onClick={() => {
              const selected = urlState.revision;
              commitUrlState({ snapshot: urlState.snapshot, revision: null });
              window.setTimeout(() => (document.querySelector<HTMLElement>(`[data-report-revision-id="${selected}"]`) ?? headingRef.current)?.focus(), 0);
            }}><X size={18} /></button>
          </header>
          {controller.detailError && <InlineError message={controller.detailError} onRetry={controller.reloadDetail} />}
          {controller.detailLoading && !controller.detail ? (
            <div className="case-reports-loading" role="status"><SpinnerGap className="spin" size={22} /><span>Revalidating stored report bytes and provenance…</span></div>
          ) : !detailReport || detailScopeError ? (
            <div className="case-reports-empty is-error"><WarningCircle size={27} /><strong>Saved revision unavailable</strong><p>{detailScopeError ?? "The stored report could not be validated."}</p></div>
          ) : (
            <div className="case-report-detail-body">
              <ReportFacts report={detailReport} capturedAt={controller.detail!.revision.captured_at} />
              <dl className="case-definition-list">
                <div><dt>Report ID</dt><dd><code title={detailReport.public_id}>{detailReport.public_id}</code></dd></div>
                <div><dt>Content hash</dt><dd><code title={detailReport.content_hash_sha256}>{detailReport.content_hash_sha256}</code></dd></div>
                <div><dt>Activity digest</dt><dd><code title={detailReport.activity_revision.digest_sha256}>{detailReport.activity_revision.digest_sha256}</code></dd></div>
                <div><dt>Evidence digest</dt><dd><code title={detailReport.evidence_revision.digest_sha256}>{detailReport.evidence_revision.digest_sha256}</code></dd></div>
              </dl>
              <a className="button-secondary" href={walletCaseReportRevisionExportUrl(walletCase.public_id, detailReport.public_id)} download>
                <DownloadSimple size={17} /> Export saved JSON
              </a>
            </div>
          )}
        </section>
      )}

      <section className="case-findings-boundary" aria-labelledby="case-reports-boundary-title">
        <WarningCircle size={24} />
        <div><h2 id="case-reports-boundary-title">History boundary</h2><p>The catalog contains explicit captures only. It does not reconstruct intermediate Evidence states or convert provider observations into canonical facts.</p></div>
      </section>
    </div>
  );
}

function ReportFacts({ report, capturedAt }: { report: WalletCaseReport; capturedAt?: string }) {
  return (
    <div className="case-report-facts">
      <Fact label="Assurance" value={assuranceLabel(report.assurance_level)} />
      <Fact label="Pinned snapshot" value={short(report.snapshot_public_id)} />
      <Fact label="Activity rows" value={String(report.activity_revision.aggregate.total_items)} />
      <Fact label={capturedAt ? "Captured" : "Evidence attempts"} value={capturedAt ? formatDate(capturedAt) : String(report.evidence_revision.total_attempts)} />
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><small>{label}</small><strong title={value}>{value}</strong></div>;
}

function InlineError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return <div className="case-inline-error" role="alert"><WarningCircle size={18} weight="fill" /><span>{message}</span><button type="button" onClick={onRetry}>Try again</button></div>;
}

function assuranceLabel(level: WalletCaseReport["assurance_level"]): string {
  return level === "partially_verified" ? "Partially verified" : level[0].toUpperCase() + level.slice(1);
}

function short(value: string): string {
  return value.length <= 25 ? value : `${value.slice(0, 12)}…${value.slice(-8)}`;
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
