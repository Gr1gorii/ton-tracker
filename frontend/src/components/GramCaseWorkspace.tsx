import { useCallback, useEffect, useRef, useState, type MouseEvent } from "react";
import { ArrowClockwise, ChartLineUp, Gauge, ShieldCheck, SpinnerGap, WarningCircle } from "@phosphor-icons/react";

import { caseActivitySearch, DEFAULT_CASE_ACTIVITY_FILTERS } from "../caseActivityQuery";
import { caseEvidenceSearch } from "../caseEvidenceQuery";
import { caseActivityPath, caseEvidencePath, caseSummaryPath } from "../caseRouting";
import { getWalletCase } from "../walletCaseApi";
import type { WalletCase } from "../walletCase";
import GramCaseActivity from "./GramCaseActivity";
import GramCaseEvidence from "./GramCaseEvidence";
import GramCaseSummary from "./GramCaseSummary";

export type WalletCaseView = "summary" | "activity" | "evidence";

function shortAddress(value: string): string {
  if (value.length <= 24) return value;
  return `${value.slice(0, 12)}…${value.slice(-9)}`;
}

export default function GramCaseWorkspace({
  caseId,
  view,
  onNavigate,
}: {
  caseId: string;
  view: WalletCaseView;
  onNavigate: (view: WalletCaseView, search?: string) => void;
}) {
  const [walletCase, setWalletCase] = useState<WalletCase | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const generation = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);

  const load = useCallback(async (background = false) => {
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestGeneration = ++generation.current;
    if (background) {
      setRefreshing(true);
      setRefreshError(null);
    } else {
      setLoading(true);
      setError(null);
      setRefreshError(null);
    }
    try {
      const result = await getWalletCase(caseId, controller.signal);
      if (controller.signal.aborted || requestGeneration !== generation.current) return;
      setWalletCase(result);
      setError(null);
    } catch (caught) {
      if (controller.signal.aborted || requestGeneration !== generation.current) return;
      const message = caught instanceof Error ? caught.message : "Wallet Case is unavailable";
      if (background) setRefreshError(message);
      else setError(message);
    } finally {
      if (!controller.signal.aborted && requestGeneration === generation.current) {
        if (background) setRefreshing(false);
        else setLoading(false);
      }
    }
  }, [caseId]);

  useEffect(() => {
    void load();
    return () => {
      generation.current += 1;
      controllerRef.current?.abort();
    };
  }, [load]);

  function followCaseLink(event: MouseEvent<HTMLAnchorElement>, nextView: WalletCaseView) {
    if (
      event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
      event.shiftKey || event.altKey
    ) return;
    event.preventDefault();
    if (nextView !== view) onNavigate(nextView);
  }

  if (loading) {
    return (
      <section className="case-state-panel" aria-live="polite">
        <SpinnerGap className="spin" size={25} />
        <div><h1>Opening Wallet Case</h1><p>Loading persisted scope and snapshot provenance…</p></div>
      </section>
    );
  }

  if (error || !walletCase) {
    return (
      <section className="case-state-panel is-error" role="alert">
        <WarningCircle size={27} weight="fill" />
        <div><h1>Wallet Case unavailable</h1><p>{error ?? "The response did not contain a Wallet Case."}</p></div>
        <button type="button" className="button-secondary" onClick={() => void load()}>
          Try again <ArrowClockwise size={17} />
        </button>
      </section>
    );
  }

  return (
    <div className="case-workspace">
      <header className="case-heading case-workspace-heading">
        <div>
          <div className="case-eyebrow-row">
            <span>Wallet Case</span>
            <strong className={`case-mode-badge is-${walletCase.data_environment}`}>
              {walletCase.data_environment === "live" ? "Live data" : "Demo data"}
            </strong>
            <strong className="case-network-badge">
              {walletCase.network === "ton-mainnet" ? "TON mainnet" : "TON testnet"}
            </strong>
          </div>
          <h1 id="case-wallet-title">{walletCase.label ?? shortAddress(walletCase.display_address)}</h1>
          <p>One persistent case for this canonical TON address. Every view remains bounded by a pinned snapshot and its recorded evidence source.</p>
          <code title={walletCase.canonical_wallet_key}>{walletCase.canonical_wallet_key}</code>
        </div>
        {refreshing && <span className="case-refreshing" role="status"><SpinnerGap className="spin" size={17} /> Publishing the new snapshot…</span>}
      </header>

      <nav className="case-view-nav" aria-label="Wallet Case views">
        <a
          href={caseSummaryPath(caseId)}
          aria-current={view === "summary" ? "page" : undefined}
          onClick={(event) => followCaseLink(event, "summary")}
        >
          <Gauge size={18} weight={view === "summary" ? "fill" : "regular"} />
          <span><strong>Summary</strong><small>Snapshot and coverage</small></span>
        </a>
        <a
          href={caseActivityPath(caseId)}
          aria-current={view === "activity" ? "page" : undefined}
          onClick={(event) => followCaseLink(event, "activity")}
        >
          <ChartLineUp size={18} weight={view === "activity" ? "fill" : "regular"} />
          <span><strong>Activity</strong><small>Filtered snapshot rows</small></span>
        </a>
        <a
          href={caseEvidencePath(caseId)}
          aria-current={view === "evidence" ? "page" : undefined}
          onClick={(event) => followCaseLink(event, "evidence")}
        >
          <ShieldCheck size={18} weight={view === "evidence" ? "fill" : "regular"} />
          <span><strong>Evidence</strong><small>Transaction verification</small></span>
        </a>
      </nav>

      {view === "summary" ? (
        <GramCaseSummary
          walletCase={walletCase}
          refreshError={refreshError}
          onRefresh={load}
        />
      ) : view === "activity" ? (
        <GramCaseActivity
          walletCase={walletCase}
          onVerifyEvidence={(snapshotId, activityId) => onNavigate("evidence", caseEvidenceSearch({ snapshot: snapshotId, activity: activityId, verification: null }))}
        />
      ) : (
        <GramCaseEvidence
          walletCase={walletCase}
          onOpenActivity={(snapshotId, activityId) => onNavigate(
            "activity",
            snapshotId === null
              ? ""
              : caseActivitySearch({
                  snapshot: snapshotId,
                  filters: DEFAULT_CASE_ACTIVITY_FILTERS,
                  selectedActivityId: activityId,
                }),
          )}
        />
      )}
    </div>
  );
}
