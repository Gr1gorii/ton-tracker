import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise,
  ClockCounterClockwise,
  Fingerprint,
  MagnifyingGlass,
  ShieldCheck,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import type { WalletCaseSync } from "../walletCase";
import {
  getWalletCaseStreamCheckpoints,
  getWalletCaseSyncManifest,
} from "../walletCaseApi";
import type { WalletCaseSyncManifestResponse } from "../walletCaseSyncManifest";
import type { WalletCaseStreamCheckpointCatalogResponse } from "../walletCaseStreamCheckpoint";
import { useWalletCaseCheckpointHistory } from "../useWalletCaseCheckpointHistory";

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export default function CaseAcquisitionManifest({
  caseId,
  snapshot,
  resumeDisabled,
  onResume,
}: {
  caseId: string;
  snapshot: WalletCaseSync;
  resumeDisabled: boolean;
  onResume: (checkpointPublicId: string) => Promise<void>;
}) {
  const descriptor = snapshot.acquisition_manifest;
  const [detail, setDetail] = useState<WalletCaseSyncManifestResponse | null>(null);
  const [checkpoints, setCheckpoints] = useState<WalletCaseStreamCheckpointCatalogResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const checkpointHistory = useWalletCaseCheckpointHistory(caseId);

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setDetail(null);
    setCheckpoints(null);
    setLoading(false);
    setError(null);
    return () => requestRef.current?.abort();
  }, [snapshot.public_id, descriptor?.public_id]);

  const load = async () => {
    if (!descriptor || loading) return;
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setLoading(true);
    setError(null);
    try {
      const [manifestResponse, checkpointResponse] = await Promise.all([
        getWalletCaseSyncManifest(
          caseId,
          snapshot.public_id,
          controller.signal,
        ),
        getWalletCaseStreamCheckpoints(caseId, controller.signal),
        checkpointHistory.load(),
      ]);
      if (manifestResponse.manifest.public_id !== descriptor.public_id) {
        throw new Error("The loaded manifest does not match this snapshot descriptor.");
      }
      setDetail(manifestResponse);
      setCheckpoints(checkpointResponse);
    } catch (cause) {
      if (controller.signal.aborted) return;
      setError(cause instanceof Error ? cause.message : "Acquisition manifest read failed.");
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setLoading(false);
      }
    }
  };

  return (
    <article className="case-detail-card case-manifest-card">
      <header>
        <div>
          <span className="eyebrow">Acquisition provenance</span>
          <h2>{descriptor ? "Content-addressed manifest" : "Manifest unavailable"}</h2>
        </div>
        <Fingerprint size={22} />
      </header>
      {descriptor ? (
        <>
          <dl className="case-definition-list">
            <div><dt>Manifest ID</dt><dd><code>{descriptor.public_id}</code></dd></div>
            <div><dt>SHA-256</dt><dd><code>{descriptor.content_hash_sha256}</code></dd></div>
            <div><dt>Provider streams</dt><dd>{descriptor.stream_count}</dd></div>
            <div><dt>Captured pages</dt><dd>{descriptor.page_count}</dd></div>
            <div><dt>Response digests</dt><dd>{descriptor.response_digest_count}</dd></div>
          </dl>
          <div className="case-manifest-actions">
            <p>
              The manifest records sanitized acquisition bounds, checkpoints, and
              provider response hashes. It does not contain raw payloads or credentials.
            </p>
            <button
              className="button-secondary"
              type="button"
              disabled={loading}
              onClick={() => void load()}
            >
              {loading ? <SpinnerGap className="spin" size={17} /> : <ShieldCheck size={17} />}
              {loading ? "Verifying…" : detail ? "Verify again" : "Inspect manifest"}
            </button>
          </div>
          {error && (
            <div className="case-sync-message is-error" role="alert">
              <WarningCircle size={18} weight="fill" />
              <span>{error}</span>
            </div>
          )}
          {detail && (
            <div className="case-manifest-detail" role="status">
              <strong>Verified by the server integrity gate</strong>
              <span>
                {detail.document.acquisition_mode === "resume"
                  ? "Checkpoint continuation"
                  : detail.document.acquisition_mode === "incremental"
                    ? "Incremental overlap"
                    : "Bounded interval"}
                {" · "}{detail.document.streams.length} streams
                {" · "}{detail.manifest.page_count} pages
                {" · "}{detail.manifest.response_digest_count} response digests
              </span>
              {detail.document.streams.map((stream) => (
                <span key={`${stream.provider}:${stream.stream_key}`}>
                  {stream.provider} / {stream.stream_key}: {stream.completion_state},
                  {" "}{stream.pages_succeeded}/{stream.page_count} pages succeeded
                </span>
              ))}
              {checkpoints && (
                <section className="case-checkpoint-catalog">
                  <strong>Durable stream checkpoints</strong>
                  <span>
                    {checkpoints.ready_count} ready
                    {" · "}{checkpoints.complete_count} complete
                    {" · "}{checkpoints.blocked_count} blocked
                  </span>
                  {checkpoints.checkpoints.length === 0 ? (
                    <span>No provider stream emitted a continuation checkpoint.</span>
                  ) : (
                    <ul>
                      {checkpoints.checkpoints.map(({ checkpoint, document }) => (
                        <li
                          className={`is-${document.resume_state}`}
                          key={checkpoint.public_id}
                        >
                          <span>
                            <b>{document.provider} / {document.stream_key}</b>
                            <small>
                              {document.resume_state === "ready"
                                ? `Continuation verified; the next request starts at page ${document.continuation_page_index}.`
                                : document.resume_state === "complete"
                                  ? "Requested interval finished; no continuation cursor is retained."
                                  : `Continuation blocked: ${document.resume_blocker}.`}
                            </small>
                          </span>
                          <div className="case-checkpoint-actions">
                            <code>{checkpoint.public_id}</code>
                            {document.resume_state === "ready" && (
                              <button
                                className="button-secondary"
                                type="button"
                                disabled={resumeDisabled}
                                aria-label={`Resume ${document.stream_key} stream`}
                                onClick={() => void onResume(checkpoint.public_id)}
                              >
                                <ArrowClockwise size={15} /> Resume stream
                              </button>
                            )}
                          </div>
                        </li>
                      ))}
                    </ul>
                  )}
                  <section className="case-checkpoint-history">
                    <header>
                      <span>
                        <ClockCounterClockwise size={17} />
                        <strong>Checkpoint revision history</strong>
                      </span>
                      {checkpointHistory.history && (
                        <small>
                          {checkpointHistory.history.items.length} of
                          {" "}{checkpointHistory.history.totalRevisions} loaded
                        </small>
                      )}
                    </header>
                    {checkpointHistory.historyState === "loading" && (
                      <span className="case-checkpoint-history-loading">
                        <SpinnerGap className="spin" size={16} /> Verifying revisions…
                      </span>
                    )}
                    {checkpointHistory.history?.items.length === 0 && (
                      <span>No checkpoint revisions have been published.</span>
                    )}
                    {checkpointHistory.history && checkpointHistory.history.items.length > 0 && (
                      <ol>
                        {checkpointHistory.history.items.map((item) => (
                          <li key={item.checkpoint.public_id}>
                            <span>
                              <b>{item.checkpoint.provider} / {item.checkpoint.stream_key}</b>
                              <small>
                                {item.lineage.acquisition_mode === "resume"
                                  ? `Resume lineage depth ${item.lineage.chain_depth}`
                                  : item.lineage.acquisition_mode === "incremental"
                                    ? "Incremental root revision"
                                    : "Bounded root revision"}
                                {" · "}{item.pages_succeeded}/{item.page_count} pages
                                {" · "}{formatTimestamp(item.checkpoint.created_at)}
                              </small>
                              <code>{item.checkpoint.public_id}</code>
                            </span>
                            <button
                              className="button-secondary"
                              type="button"
                              disabled={checkpointHistory.selectionLoading}
                              aria-label={`Inspect checkpoint revision ${item.checkpoint.public_id}`}
                              onClick={() => void checkpointHistory.inspect(
                                item.checkpoint.public_id,
                              )}
                            >
                              {checkpointHistory.selectionLoading
                                ? <SpinnerGap className="spin" size={14} />
                                : <MagnifyingGlass size={14} />}
                              Inspect
                            </button>
                          </li>
                        ))}
                      </ol>
                    )}
                    {checkpointHistory.selected && (
                      <dl className="case-checkpoint-revision-detail" role="status">
                        <div><dt>Verified revision</dt><dd><code>{checkpointHistory.selected.checkpoint.public_id}</code></dd></div>
                        <div><dt>Source sync</dt><dd><code>{checkpointHistory.selected.document.source_sync_public_id}</code></dd></div>
                        <div><dt>Source manifest</dt><dd><code>{checkpointHistory.selected.document.source_manifest_public_id}</code></dd></div>
                        <div><dt>Parent revision</dt><dd><code>{checkpointHistory.selected.lineage.parent_checkpoint_public_id ?? "Root revision"}</code></dd></div>
                        <div><dt>Chain depth</dt><dd>{checkpointHistory.selected.lineage.chain_depth}</dd></div>
                        <div><dt>Resume state</dt><dd>{checkpointHistory.selected.document.resume_state}</dd></div>
                      </dl>
                    )}
                    {(checkpointHistory.historyError || checkpointHistory.selectionError) && (
                      <div className="case-sync-message is-error" role="alert">
                        <WarningCircle size={16} weight="fill" />
                        <span>{checkpointHistory.historyError ?? checkpointHistory.selectionError}</span>
                      </div>
                    )}
                    {checkpointHistory.history?.hasMore && (
                      <button
                        className="button-secondary case-checkpoint-load-more"
                        type="button"
                        disabled={checkpointHistory.historyState !== "idle"}
                        onClick={() => void checkpointHistory.loadMore()}
                      >
                        {checkpointHistory.historyState === "loading-more"
                          ? <SpinnerGap className="spin" size={15} />
                          : <ClockCounterClockwise size={15} />}
                        {checkpointHistory.historyState === "loading-more"
                          ? "Loading older…"
                          : "Load older revisions"}
                      </button>
                    )}
                    {checkpointHistory.history?.limitations[0] && (
                      <small className="case-checkpoint-history-boundary">
                        {checkpointHistory.history.limitations[0].message}
                      </small>
                    )}
                  </section>
                </section>
              )}
            </div>
          )}
        </>
      ) : (
        <div className="case-card-empty">
          <p>
            This legacy snapshot has no immutable page-checkpoint manifest. Its other
            evidence remains available with that boundary stated explicitly.
          </p>
        </div>
      )}
    </article>
  );
}
