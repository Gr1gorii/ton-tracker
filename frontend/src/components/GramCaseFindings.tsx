import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent, type ReactNode } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  ArrowsLeftRight,
  ChartDonut,
  Database,
  Info,
  ShieldCheck,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import { caseActivitySearch, DEFAULT_CASE_ACTIVITY_FILTERS } from "../caseActivityQuery";
import {
  caseFindingsSearch,
  EMPTY_CASE_FINDINGS_URL_STATE,
  readCaseFindingsUrlState,
  type CaseFindingsUrlState,
} from "../caseFindingsQuery";
import { caseActivityPath, caseFindingsPath } from "../caseRouting";
import type { WalletCase } from "../walletCase";
import type {
  WalletCaseAssetFlow,
  WalletCaseFinding,
  WalletCaseFindingEvidenceLevel,
} from "../walletCaseFindings";
import { useWalletCaseFindings } from "../useWalletCaseFindings";

export default function GramCaseFindings({
  walletCase,
  onOpenActivity,
}: {
  walletCase: WalletCase;
  onOpenActivity: (snapshotId: string, activityId: string) => void;
}) {
  const initial = useMemo(readCaseFindingsUrlState, []);
  const [urlState, setUrlState] = useState(initial.state);
  const [queryError, setQueryError] = useState(initial.error);
  const headingRef = useRef<HTMLHeadingElement>(null);

  const commitUrlState = useCallback((next: CaseFindingsUrlState, replace = false) => {
    window.history[replace ? "replaceState" : "pushState"]({}, "", `${caseFindingsPath(walletCase.public_id)}${caseFindingsSearch(next)}`);
    setQueryError(null);
    setUrlState(next);
  }, [walletCase.public_id]);

  const controller = useWalletCaseFindings({
    caseId: walletCase.public_id,
    urlState,
    enabled: queryError === null,
    onSnapshotPinned: useCallback((snapshotId: string) => {
      setUrlState((current) => {
        if (current.snapshot !== null) return current;
        const next = { snapshot: snapshotId };
        window.history.replaceState({}, "", `${caseFindingsPath(walletCase.public_id)}${caseFindingsSearch(next)}`);
        return next;
      });
    }, [walletCase.public_id]),
  });

  useEffect(() => {
    function restore() {
      const next = readCaseFindingsUrlState();
      setQueryError(next.error);
      setUrlState(next.state);
      window.setTimeout(() => headingRef.current?.focus(), 0);
    }
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  if (queryError) {
    return (
      <section className="case-state-panel is-error" role="alert">
        <WarningCircle size={27} weight="fill" />
        <div><h2>Findings URL is invalid</h2><p>{queryError}</p></div>
        <button type="button" className="button-secondary" onClick={() => commitUrlState(EMPTY_CASE_FINDINGS_URL_STATE, true)}>
          Reset Findings view <ArrowClockwise size={17} />
        </button>
      </section>
    );
  }

  const receivedDocument = controller.response?.findings ?? null;
  const scopeError = receivedDocument && (
    receivedDocument.subject.network !== walletCase.network
    || receivedDocument.subject.data_environment !== walletCase.data_environment
    || receivedDocument.subject.wallet_account_canonical !== walletCase.canonical_wallet_key
  )
    ? "Wallet Case Findings does not match the open case identity or evidence environment."
    : null;
  const document = scopeError ? null : receivedDocument;
  const snapshot = document?.snapshot ?? null;

  function openActivity(event: MouseEvent<HTMLAnchorElement>, activityId: string) {
    if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !snapshot) return;
    event.preventDefault();
    onOpenActivity(snapshot.public_id, activityId);
  }

  return (
    <div className="case-findings-page">
      <section className="case-findings-toolbar" aria-labelledby="case-findings-title">
        <div>
          <span className="eyebrow">Findings and flows</span>
          <h2 ref={headingRef} tabIndex={-1} id="case-findings-title">Explain the pinned observations without assigning a risk score</h2>
          <p>Published rules point back to Activity rows. Asset amounts remain separated by canonical identity, and missing evidence stays visible.</p>
        </div>
        <button type="button" className="button-secondary" onClick={controller.reload} disabled={controller.loading}>
          <ArrowClockwise className={controller.loading ? "spin" : undefined} size={17} /> Refresh
        </button>
      </section>

      {controller.error && (
        <section className="case-inline-error" role="alert">
          <WarningCircle size={18} /><span>{controller.error}</span><button type="button" onClick={controller.reload}>Try again</button>
        </section>
      )}

      {scopeError && (
        <section className="case-inline-error" role="alert">
          <WarningCircle size={18} /><span>{scopeError}</span><button type="button" onClick={controller.reload}>Reload</button>
        </section>
      )}

      {scopeError ? null : controller.loading && !controller.response ? (
        <section className="case-state-panel" aria-live="polite">
          <SpinnerGap className="spin" size={25} />
          <div><h2>Building Findings</h2><p>Revalidating one pinned Activity and Evidence revision…</p></div>
        </section>
      ) : !document || !snapshot ? (
        <section className="case-findings-empty">
          <Database size={30} />
          <h2>No usable snapshot yet</h2>
          <p>Run a bounded synchronization from Summary before reviewing explainable findings.</p>
        </section>
      ) : (
        <>
          <section className="case-findings-trust" aria-label="Findings revision boundaries">
            <Fact label="Pinned snapshot" value={short(snapshot.public_id)} icon={<Database size={19} />} />
            <Fact label="Activity rows" value={String(document.activity_revision.aggregate.total_items)} icon={<ArrowsLeftRight size={19} />} />
            <Fact label="Rule matches" value={String(document.findings.length)} icon={<Info size={19} />} />
            <Fact label="Evidence attempts" value={`${document.evidence_revision.returned_revalidated}/${document.evidence_revision.total_attempts}`} icon={<ShieldCheck size={19} />} />
          </section>

          <section className="case-findings-section" aria-labelledby="asset-flows-title">
            <header><div><span className="eyebrow">Asset flows</span><h2 id="asset-flows-title">Quantities stay inside one canonical asset identity</h2></div><ChartDonut size={24} /></header>
            {document.flows.asset_flows.length === 0 ? (
              <EmptyLine text="No identified transfer or swap asset flow is available in this revision." />
            ) : (
              <div className="case-flow-grid">
                {document.flows.asset_flows.map((flow) => <AssetFlowCard key={flow.asset_id} flow={flow} />)}
              </div>
            )}
          </section>

          <div className="case-findings-columns">
            <section className="case-findings-section" aria-labelledby="counterparty-flows-title">
              <header><div><span className="eyebrow">Counterparties</span><h2 id="counterparty-flows-title">Canonical transfer groups</h2></div><ArrowsLeftRight size={23} /></header>
              {document.flows.counterparty_flows.length === 0 ? <EmptyLine text="No canonical counterparty group is available." /> : (
                <ul className="case-flow-list">
                  {document.flows.counterparty_flows.map((flow) => (
                    <li key={flow.canonical_address}>
                      <strong title={flow.canonical_address}>{short(flow.canonical_address)}</strong>
                      <span>{flow.incoming_observations} incoming · {flow.outgoing_observations} outgoing{flow.unknown_direction_observations ? ` · ${flow.unknown_direction_observations} unknown` : ""}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="case-findings-section" aria-labelledby="protocol-flows-title">
              <header><div><span className="eyebrow">Protocols</span><h2 id="protocol-flows-title">Recognized swap decoders</h2></div><ChartDonut size={23} /></header>
              {document.flows.protocol_flows.length === 0 ? <EmptyLine text="No recognized protocol observation is available." /> : (
                <ul className="case-flow-list">
                  {document.flows.protocol_flows.map((flow) => (
                    <li key={flow.protocol_id}>
                      <strong>{flow.label ?? flow.protocol_id}</strong>
                      <span>{flow.swap_observations} swap observation{flow.swap_observations === 1 ? "" : "s"} · {flow.version ?? "version unavailable"}</span>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>

          <section className="case-findings-section" aria-labelledby="published-findings-title">
            <header><div><span className="eyebrow">Published rules</span><h2 id="published-findings-title">Explainable findings with supporting rows</h2></div><Info size={24} /></header>
            {document.findings.length === 0 ? (
              <div className="case-findings-no-match"><Info size={24} /><strong>No published rule matched this returned revision.</strong><p>This is not a safe-wallet classification and does not establish complete history.</p></div>
            ) : (
              <div className="case-finding-list">
                {document.findings.map((finding) => (
                  <article key={finding.public_id} className={`case-finding-card is-${finding.importance}`}>
                    <header>
                      <div><span>{finding.category.replace(/_/g, " ")}</span><h3>{finding.title}</h3></div>
                      <EvidenceChip level={finding.evidence_level} />
                    </header>
                    <p>{finding.explanation}</p>
                    <dl><div><dt>Affected</dt><dd>{finding.affected_count}</dd></div><div><dt>Rule</dt><dd><code>{finding.rule_id}</code></dd></div></dl>
                    {finding.supporting_activities.length > 0 && (
                      <div className="case-finding-support">
                        <strong>Supporting Activity</strong>
                        <ul>
                          {finding.supporting_activities.map((support) => {
                            const state = { snapshot: snapshot.public_id, filters: DEFAULT_CASE_ACTIVITY_FILTERS, selectedActivityId: support.activity_public_id };
                            return (
                              <li key={support.activity_public_id}>
                                <a href={`${caseActivityPath(walletCase.public_id)}${caseActivitySearch(state)}`} onClick={(event) => openActivity(event, support.activity_public_id)}>
                                  <span><strong>{support.kind}</strong><small>{formatDate(support.occurred_at)}</small></span>
                                  <EvidenceChip level={support.evidence_level} compact />
                                  <ArrowRight size={16} />
                                </a>
                              </li>
                            );
                          })}
                        </ul>
                        {finding.support_truncated && <small>Supporting rows are truncated to the public bound.</small>}
                      </div>
                    )}
                  </article>
                ))}
              </div>
            )}
          </section>

          <section className="case-findings-boundary" aria-labelledby="findings-boundary-title">
            <WarningCircle size={24} />
            <div>
              <h2 id="findings-boundary-title">Interpretation boundary</h2>
              <p>These rules do not establish ownership, illicit activity, safety, complete wallet history, cost basis or comparable value across assets.</p>
              <ul>{document.limitations.map((item) => <li key={item.code}><strong>{item.code.replace(/_/g, " ")}</strong><span>{item.message}</span></li>)}</ul>
            </div>
          </section>
        </>
      )}
    </div>
  );
}

function Fact({ label, value, icon }: { label: string; value: string; icon: ReactNode }) {
  return <div><span>{icon}</span><small>{label}</small><strong title={value}>{value}</strong></div>;
}

function AssetFlowCard({ flow }: { flow: WalletCaseAssetFlow }) {
  const label = flow.symbol ?? (flow.standard === "native" ? "TON" : "Jetton");
  return (
    <article className="case-asset-flow-card">
      <header><div><strong>{label}</strong><small>{flow.standard}{flow.contract_address ? ` · ${short(flow.contract_address)}` : ""}</small></div><code title={flow.asset_id}>{short(flow.asset_id)}</code></header>
      <dl>
        <div><dt>Observed inflow</dt><dd>{flow.inflow_amount ?? "Amount unavailable"}</dd></div>
        <div><dt>Observed outflow</dt><dd>{flow.outflow_amount ?? "Amount unavailable"}</dd></div>
        <div><dt>Rows</dt><dd>{flow.inflow_observations + flow.outflow_observations + flow.unknown_direction_observations}</dd></div>
      </dl>
    </article>
  );
}

function EvidenceChip({ level, compact = false }: { level: WalletCaseFindingEvidenceLevel; compact?: boolean }) {
  const label = level === "chain_inclusion_proven" ? "Chain inclusion proven" : level === "locally_verified" ? "Locally verified" : level === "fixture" ? "Demo fixture" : "Provider observation";
  return <span className={`case-finding-evidence is-${level}${compact ? " is-compact" : ""}`}>{label}</span>;
}

function EmptyLine({ text }: { text: string }) {
  return <div className="case-findings-empty-line"><Info size={20} /><span>{text}</span></div>;
}

function short(value: string): string {
  return value.length <= 24 ? value : `${value.slice(0, 12)}…${value.slice(-8)}`;
}

function formatDate(value: string | null): string {
  if (value === null) return "Time unavailable";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
