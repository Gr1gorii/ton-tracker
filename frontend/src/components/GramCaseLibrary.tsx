import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowCounterClockwise,
  Archive,
  ArrowsClockwise,
  ChartLineUp,
  FolderOpen,
  Plus,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import type { WalletCase, WalletCaseCatalogState } from "../walletCase";
import { listWalletCases, restoreWalletCase } from "../walletCaseApi";

const INITIAL_LIMIT = 12;

interface CaseLibraryCatalog {
  cases: WalletCase[];
  continued: boolean;
  hasMore: boolean;
  nextCursor: string | null;
}

function shortAddress(value: string): string {
  if (value.length <= 24) return value;
  return `${value.slice(0, 12)}…${value.slice(-9)}`;
}

function activityCount(walletCase: WalletCase): number {
  return Object.values(walletCase.summary.activity_counts).reduce(
    (total, count) => total + count,
    0,
  );
}

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Unknown update time";
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function syncLabel(walletCase: WalletCase): string {
  if (walletCase.active_sync?.state === "queued") return "Sync queued";
  if (walletCase.active_sync?.state === "running") return "Sync running";
  if (walletCase.current_snapshot?.state === "partial") return "Partial snapshot";
  if (walletCase.current_snapshot) return "Snapshot ready";
  if (walletCase.latest_sync_attempt?.state === "failed") return "Latest sync failed";
  if (walletCase.latest_sync_attempt?.state === "cancelled") return "Latest sync cancelled";
  return "Not synchronized";
}

export default function GramCaseLibrary({
  onOpenCase,
  onCreateCase,
}: {
  onOpenCase: (caseId: string) => void;
  onCreateCase: () => void;
}) {
  const [catalog, setCatalog] = useState<CaseLibraryCatalog | null>(null);
  const [catalogState, setCatalogState] = useState<WalletCaseCatalogState>("active");
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [moreError, setMoreError] = useState<string | null>(null);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [restoringId, setRestoringId] = useState<string | null>(null);
  const generation = useRef(0);
  const controllerRef = useRef<AbortController | null>(null);
  const restoreControllerRef = useRef<AbortController | null>(null);
  const catalogRef = useRef<CaseLibraryCatalog | null>(null);

  function commitCatalog(next: CaseLibraryCatalog) {
    catalogRef.current = next;
    setCatalog(next);
  }

  async function load(
    state: WalletCaseCatalogState,
    cursor: string | null = null,
    expanding = false,
  ) {
    const startingCatalog = catalogRef.current;
    if (
      expanding &&
      (cursor === null || startingCatalog?.nextCursor !== cursor)
    ) return;
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestGeneration = ++generation.current;
    if (expanding) {
      setLoadingMore(true);
      setMoreError(null);
    } else {
      setLoading(true);
      setError(null);
      setMoreError(null);
    }
    try {
      const result = await listWalletCases({
        limit: INITIAL_LIMIT,
        state,
        cursor,
        signal: controller.signal,
      });
      if (controller.signal.aborted || requestGeneration !== generation.current) return;
      if (!expanding) {
        commitCatalog({
          cases: result.cases,
          continued: false,
          hasMore: result.truncated,
          nextCursor: result.next_cursor,
        });
        return;
      }
      const current = catalogRef.current;
      if (current === null || current.nextCursor !== cursor) return;
      const knownIds = new Set(current.cases.map((walletCase) => walletCase.public_id));
      if (result.cases.some((walletCase) => knownIds.has(walletCase.public_id))) {
        throw new Error(
          "Wallet Case catalog continuation overlaps previously loaded Cases.",
        );
      }
      if (result.next_cursor !== null && result.next_cursor === cursor) {
        throw new Error("Wallet Case catalog continuation did not advance.");
      }
      commitCatalog({
        cases: [...current.cases, ...result.cases],
        continued: true,
        hasMore: result.truncated,
        nextCursor: result.next_cursor,
      });
    } catch (caught) {
      if (controller.signal.aborted || requestGeneration !== generation.current) return;
      const message = caught instanceof Error
        ? caught.message
        : "Wallet Case library is unavailable.";
      if (expanding) setMoreError(message);
      else setError(message);
    } finally {
      if (!controller.signal.aborted && requestGeneration === generation.current) {
        if (expanding) setLoadingMore(false);
        else setLoading(false);
      }
    }
  }

  useEffect(() => {
    void load(catalogState);
    return () => {
      generation.current += 1;
      controllerRef.current?.abort();
      controllerRef.current = null;
      restoreControllerRef.current?.abort();
      restoreControllerRef.current = null;
    };
  }, [catalogState]);

  function selectCatalogState(next: WalletCaseCatalogState) {
    if (next === catalogState) return;
    generation.current += 1;
    controllerRef.current?.abort();
    restoreControllerRef.current?.abort();
    controllerRef.current = null;
    restoreControllerRef.current = null;
    catalogRef.current = null;
    setCatalog(null);
    setLifecycleError(null);
    setRestoringId(null);
    setCatalogState(next);
  }

  async function restoreCase(walletCase: WalletCase) {
    if (walletCase.archived_at === null || restoringId !== null) return;
    restoreControllerRef.current?.abort();
    const controller = new AbortController();
    restoreControllerRef.current = controller;
    setRestoringId(walletCase.public_id);
    setLifecycleError(null);
    try {
      await restoreWalletCase(walletCase.public_id, controller.signal);
      if (controller.signal.aborted) return;
      await load("archived");
    } catch (caught) {
      if (controller.signal.aborted) return;
      setLifecycleError(
        caught instanceof Error ? caught.message : "Wallet Case restoration failed.",
      );
    } finally {
      if (!controller.signal.aborted) {
        setRestoringId(null);
        restoreControllerRef.current = null;
      }
    }
  }

  return (
    <section className="case-library" aria-labelledby="case-library-title">
      <header className="case-library-heading">
        <div>
          <span>Local evidence workspace</span>
          <h1 id="case-library-title">Wallet Case library</h1>
          <p>
            Reopen a canonical wallet workspace with its latest bounded snapshot,
            sync state, notes, Evidence, Findings, and saved Reports intact.
          </p>
        </div>
        <button type="button" className="button-primary" onClick={onCreateCase}>
          <Plus size={17} weight="bold" /> Create or open Case
        </button>
      </header>

      <div className="case-library-tabs" role="tablist" aria-label="Case lifecycle">
        <button
          type="button"
          role="tab"
          aria-selected={catalogState === "active"}
          onClick={() => selectCatalogState("active")}
        >
          <FolderOpen size={17} /> Active Cases
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={catalogState === "archived"}
          onClick={() => selectCatalogState("archived")}
        >
          <Archive size={17} /> Archived Cases
        </button>
      </div>

      {loading && !catalog && (
        <div className="case-library-state" role="status">
          <SpinnerGap className="spin" size={25} />
          <div><h2>Loading your Cases</h2><p>Reading the owner-scoped local catalog…</p></div>
        </div>
      )}

      {error && !catalog && (
        <div className="case-library-state is-error" role="alert">
          <WarningCircle size={25} weight="fill" />
          <div><h2>Case library unavailable</h2><p>{error}</p></div>
          <button type="button" className="button-secondary" onClick={() => void load(catalogState)}>
            <ArrowsClockwise size={17} /> Retry
          </button>
        </div>
      )}

      {!loading && !error && catalog?.cases.length === 0 && (
        <div className="case-library-empty">
          <span>{catalogState === "active" ? <FolderOpen size={31} weight="duotone" /> : <Archive size={31} weight="duotone" />}</span>
          <h2>{catalogState === "active" ? "No Wallet Cases yet" : "No archived Cases"}</h2>
          <p>
            {catalogState === "active"
              ? "Create a Case from a TON address to start a durable evidence workspace."
              : "Archived Cases keep their snapshots, evidence, notes, and reports until you restore or permanently delete them."}
          </p>
          {catalogState === "active" && (
            <button type="button" className="button-primary" onClick={onCreateCase}>
              <Plus size={17} /> Create your first Case
            </button>
          )}
        </div>
      )}

      {lifecycleError && (
        <p className="case-library-lifecycle-error" role="alert">
          <WarningCircle size={17} weight="fill" /> {lifecycleError}
        </p>
      )}

      {catalog && catalog.cases.length > 0 && (
        <>
          <div className="case-library-summary" role="status">
            <span>{catalog.cases.length} {catalog.cases.length === 1 ? "Case" : "Cases"}</span>
            <small>{catalogState === "active" ? "Newest updates first" : "Newest archives first"} · local owner scope</small>
          </div>
          <div className="case-library-grid">
            {catalog.cases.map((walletCase) => {
              const title = walletCase.label ?? shortAddress(walletCase.display_address);
              const count = activityCount(walletCase);
              const state = syncLabel(walletCase);
              return (
                <article className="case-library-card" key={walletCase.public_id}>
                  <div className="case-library-card-badges">
                    <span>{walletCase.data_environment === "demo" ? "Demo data" : "Live data"}</span>
                    <span>{walletCase.network === "ton-mainnet" ? "TON mainnet" : "TON testnet"}</span>
                  </div>
                  <h2>{title}</h2>
                  {walletCase.note && <p className="case-library-note">{walletCase.note}</p>}
                  <code title={walletCase.canonical_wallet_key}>{shortAddress(walletCase.canonical_wallet_key)}</code>
                  <dl>
                    <div><dt>State</dt><dd>{state}</dd></div>
                    <div><dt>Activity</dt><dd><ChartLineUp size={15} /> {count} rows</dd></div>
                    <div>
                      <dt>{catalogState === "active" ? "Updated" : "Archived"}</dt>
                      <dd><time dateTime={walletCase.archived_at ?? walletCase.updated_at}>{formatDate(walletCase.archived_at ?? walletCase.updated_at)}</time></dd>
                    </div>
                  </dl>
                  {catalogState === "active" ? (
                    <button
                      type="button"
                      className="case-library-open"
                      aria-label={`Open Case ${title}`}
                      disabled={walletCase.archived_at !== null}
                      onClick={() => onOpenCase(walletCase.public_id)}
                    >
                      {walletCase.archived_at === null ? "Open Case" : "Archived since snapshot"}
                      <ArrowRight size={17} weight="bold" />
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="case-library-restore"
                      aria-label={`Restore Case ${title}`}
                      disabled={walletCase.archived_at === null || restoringId !== null}
                      onClick={() => void restoreCase(walletCase)}
                    >
                      {restoringId === walletCase.public_id
                        ? <SpinnerGap className="spin" size={17} />
                        : <ArrowCounterClockwise size={17} weight="bold" />}
                      {walletCase.archived_at === null
                        ? "Already restored"
                        : restoringId === walletCase.public_id
                          ? "Restoring…"
                          : "Restore Case"}
                    </button>
                  )}
                </article>
              );
            })}
          </div>

          {catalog.hasMore && catalog.nextCursor && (
            <div className="case-library-more">
              <button
                type="button"
                className="button-secondary"
                disabled={loadingMore}
                onClick={() => void load(catalogState, catalog.nextCursor, true)}
              >
                {loadingMore ? <SpinnerGap className="spin" size={17} /> : <FolderOpen size={17} />}
                {loadingMore
                  ? "Loading…"
                  : moreError
                    ? "Retry loading more"
                    : catalogState === "active" ? "Load more Cases" : "Load more archived Cases"}
              </button>
            </div>
          )}
          {!catalog.hasMore && catalog.continued && (
            <p className="case-library-boundary">
              End of this Case catalog snapshot.
            </p>
          )}
          {moreError && <p className="case-library-more-error" role="alert">{moreError}</p>}
        </>
      )}
    </section>
  );
}
