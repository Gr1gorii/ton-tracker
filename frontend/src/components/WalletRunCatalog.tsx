import { useState } from "react";

import type { WalletIngestionRunCatalogItem } from "../types";
import { parseStoredRunId } from "../walletRunLoader";

const COLLAPSED_RUN_COUNT = 3;

interface WalletRunCatalogProps {
  runs: WalletIngestionRunCatalogItem[];
  truncated: boolean;
  loading: boolean;
  error: string | null;
  activeRunId: number | null;
  openingRunId: number | null;
  workspaceBusy: boolean;
  onRefresh: () => void;
  onOpen: (runId: number) => void;
}

export default function WalletRunCatalog({
  runs,
  truncated,
  loading,
  error,
  activeRunId,
  openingRunId,
  workspaceBusy,
  onRefresh,
  onOpen,
}: WalletRunCatalogProps) {
  const [expanded, setExpanded] = useState(false);
  const visibleRuns = expanded ? runs : runs.slice(0, COLLAPSED_RUN_COUNT);
  const hiddenCount = runs.length - visibleRuns.length;

  return (
    <section
      className="wallet-run-catalog"
      aria-labelledby="wallet-run-catalog-title"
      aria-busy={loading}
    >
      <div className="wallet-run-catalog-head">
        <div>
          <span className="state-kicker">RECENT_PERSISTED_RUNS</span>
          <strong id="wallet-run-catalog-title">Recent persisted runs</strong>
          <p>
            Privacy-bounded hints only. Open a row to read its full stored scope
            through the run loader.
          </p>
        </div>
        <button
          className="btn btn-ghost wallet-run-catalog-refresh"
          type="button"
          disabled={loading}
          onClick={onRefresh}
        >
          {loading && runs.length > 0 ? "Refreshing" : "Refresh recent list"}
        </button>
      </div>

      {loading && runs.length === 0 && (
        <div className="wallet-run-catalog-loading" role="status" aria-live="polite">
          <span className="spinner" aria-hidden="true" />
          <span>Loading recent persisted runs.</span>
        </div>
      )}

      {error && (
        <div className="wallet-run-catalog-error" role="alert">
          <div>
            <strong>Recent runs unavailable.</strong>
            <span>
              {runs.length > 0
                ? " The last successful list remains visible."
                : " Exact ID loading still works."}
            </span>
            <small>{error}</small>
          </div>
          <button
            className="btn btn-ghost"
            type="button"
            disabled={loading}
            onClick={onRefresh}
          >
            Retry
          </button>
        </div>
      )}

      {!loading && !error && runs.length === 0 && (
        <div className="wallet-run-catalog-empty" role="status">
          No persisted runs yet. Run ingestion once, then refresh this list.
        </div>
      )}

      {runs.length > 0 && (
        <>
          <ul className="wallet-run-catalog-list" id="wallet-run-catalog-list">
            {visibleRuns.map((run) => {
              const parsedRunId = parseStoredRunId(run.run_id);
              const active =
                parsedRunId !== null && activeRunId === parsedRunId;
              const opening =
                parsedRunId !== null && openingRunId === parsedRunId;
              const openDisabled =
                parsedRunId === null || workspaceBusy || openingRunId !== null;
              const openLabel = `Open stored run #${run.run_id}, wallet ${run.wallet_hint}`;

              return (
                <li
                  className={`wallet-run-catalog-row${active ? " wallet-run-catalog-row-current" : ""}`}
                  key={run.run_id}
                >
                  <div className="wallet-run-catalog-identity">
                    <div>
                      <code>RUN #{run.run_id}</code>
                      {active && <span className="badge badge-real">CURRENT</span>}
                    </div>
                    <span>{run.wallet_hint}</span>
                  </div>
                  <div className="wallet-run-catalog-meta">
                    <span className="badge badge-provider">{run.status}</span>
                    <span className="badge badge-provider">{run.data_mode}</span>
                    <span>{run.time_window}</span>
                    <time dateTime={run.created_at}>
                      {formatCatalogDate(run.created_at)}
                    </time>
                  </div>
                  <div className="wallet-run-catalog-action">
                    <button
                      className="btn btn-ghost"
                      type="button"
                      aria-label={openLabel}
                      aria-current={active ? "true" : undefined}
                      disabled={openDisabled}
                      onClick={() => {
                        if (parsedRunId !== null) onOpen(parsedRunId);
                      }}
                    >
                      {opening ? "Opening" : active ? "Open again" : "Open"}
                    </button>
                    {parsedRunId === null && (
                      <small>
                        Exact ID is preserved, but this browser cannot safely
                        open it. The browser loader supports IDs through
                        9007199254740991.
                      </small>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>

          {(hiddenCount > 0 || expanded) && runs.length > COLLAPSED_RUN_COUNT && (
            <button
              className="wallet-run-catalog-expand"
              type="button"
              aria-expanded={expanded}
              aria-controls="wallet-run-catalog-list"
              onClick={() => setExpanded((current) => !current)}
            >
              {expanded ? "Show fewer" : `Show all ${runs.length}`}
            </button>
          )}
          {truncated && (
            <p className="wallet-run-catalog-truncated">
              Showing the {runs.length} newest runs. Enter an exact ID above to
              open an older run.
            </p>
          )}
        </>
      )}
    </section>
  );
}

function formatCatalogDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}
