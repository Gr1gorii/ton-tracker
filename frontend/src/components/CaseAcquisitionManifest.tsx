import { useEffect, useRef, useState } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  ClockCounterClockwise,
  DownloadSimple,
  Fingerprint,
  MagnifyingGlass,
  TreeStructure,
  ShieldCheck,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import type { WalletCaseSync } from "../walletCase";
import {
  getWalletCaseCheckpointContinuationReceipt,
  getWalletCaseCheckpointContinuationPlan,
  getWalletCaseStreamCheckpoints,
  getWalletCaseSyncManifest,
} from "../walletCaseApi";
import type { WalletCaseSyncManifestResponse } from "../walletCaseSyncManifest";
import {
  serializeWalletCaseCheckpointContinuationReceipt,
  serializeWalletCaseCheckpointContinuationPlan,
  serializeWalletCaseStreamCheckpointChain,
  type WalletCaseCheckpointContinuationReceiptResponse,
  type WalletCaseCheckpointContinuationPlanResponse,
  type WalletCaseStreamCheckpointCatalogResponse,
  type WalletCaseStreamCheckpointChainResponse,
} from "../walletCaseStreamCheckpoint";
import { useWalletCaseCheckpointHistory } from "../useWalletCaseCheckpointHistory";

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function downloadCheckpointChain(
  chain: WalletCaseStreamCheckpointChainResponse,
): void {
  const url = URL.createObjectURL(new Blob(
    [serializeWalletCaseStreamCheckpointChain(chain)],
    { type: "application/json" },
  ));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `checkpoint-chain-${chain.chain.public_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadContinuationPlan(
  plan: WalletCaseCheckpointContinuationPlanResponse,
): void {
  const url = URL.createObjectURL(new Blob(
    [serializeWalletCaseCheckpointContinuationPlan(plan)],
    { type: "application/json" },
  ));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `checkpoint-continuation-plan-${plan.plan.public_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
}

function downloadContinuationReceipt(
  receipt: WalletCaseCheckpointContinuationReceiptResponse,
): void {
  const url = URL.createObjectURL(new Blob(
    [serializeWalletCaseCheckpointContinuationReceipt(receipt)],
    { type: "application/json" },
  ));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `checkpoint-continuation-receipt-${receipt.receipt.public_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
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
  onResume: (
    continuationPlanPublicId: string,
    checkpointPublicId: string,
  ) => Promise<void>;
}) {
  const descriptor = snapshot.acquisition_manifest;
  const [detail, setDetail] = useState<WalletCaseSyncManifestResponse | null>(null);
  const [checkpoints, setCheckpoints] = useState<WalletCaseStreamCheckpointCatalogResponse | null>(null);
  const [continuationPlan, setContinuationPlan] = useState<WalletCaseCheckpointContinuationPlanResponse | null>(null);
  const [continuationPlanLoading, setContinuationPlanLoading] = useState(false);
  const [continuationPlanError, setContinuationPlanError] = useState<string | null>(null);
  const [continuationReceipt, setContinuationReceipt] = useState<WalletCaseCheckpointContinuationReceiptResponse | null>(null);
  const [continuationReceiptLoading, setContinuationReceiptLoading] = useState(false);
  const [continuationReceiptError, setContinuationReceiptError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);
  const continuationPlanRequestRef = useRef<AbortController | null>(null);
  const continuationReceiptRequestRef = useRef<AbortController | null>(null);
  const checkpointHistory = useWalletCaseCheckpointHistory(caseId);
  const canVerifyContinuationReceipt = (
    snapshot.requested_scope.mode === "resume" &&
    snapshot.requested_scope.continuation_plan_public_id !== null &&
    (snapshot.state === "partial" || snapshot.state === "succeeded")
  );

  useEffect(() => {
    requestRef.current?.abort();
    continuationPlanRequestRef.current?.abort();
    continuationReceiptRequestRef.current?.abort();
    requestRef.current = null;
    continuationPlanRequestRef.current = null;
    continuationReceiptRequestRef.current = null;
    setDetail(null);
    setCheckpoints(null);
    setContinuationPlan(null);
    setContinuationPlanLoading(false);
    setContinuationPlanError(null);
    setContinuationReceipt(null);
    setContinuationReceiptLoading(false);
    setContinuationReceiptError(null);
    setLoading(false);
    setError(null);
    return () => {
      requestRef.current?.abort();
      continuationPlanRequestRef.current?.abort();
      continuationReceiptRequestRef.current?.abort();
    };
  }, [caseId, snapshot.public_id, descriptor?.public_id]);

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

  const loadContinuationPlan = async () => {
    if (continuationPlanLoading) return;
    continuationPlanRequestRef.current?.abort();
    const controller = new AbortController();
    continuationPlanRequestRef.current = controller;
    setContinuationPlanLoading(true);
    setContinuationPlanError(null);
    try {
      setContinuationPlan(await getWalletCaseCheckpointContinuationPlan(
        caseId,
        controller.signal,
      ));
    } catch (cause) {
      if (controller.signal.aborted) return;
      setContinuationPlanError(
        cause instanceof Error
          ? cause.message
          : "Checkpoint continuation plan read failed.",
      );
    } finally {
      if (continuationPlanRequestRef.current === controller) {
        continuationPlanRequestRef.current = null;
        setContinuationPlanLoading(false);
      }
    }
  };

  const loadContinuationReceipt = async () => {
    if (!canVerifyContinuationReceipt || continuationReceiptLoading) return;
    continuationReceiptRequestRef.current?.abort();
    const controller = new AbortController();
    continuationReceiptRequestRef.current = controller;
    setContinuationReceiptLoading(true);
    setContinuationReceiptError(null);
    try {
      setContinuationReceipt(await getWalletCaseCheckpointContinuationReceipt(
        caseId,
        snapshot.public_id,
        controller.signal,
      ));
    } catch (cause) {
      if (controller.signal.aborted) return;
      setContinuationReceiptError(
        cause instanceof Error
          ? cause.message
          : "Checkpoint continuation receipt read failed.",
      );
    } finally {
      if (continuationReceiptRequestRef.current === controller) {
        continuationReceiptRequestRef.current = null;
        setContinuationReceiptLoading(false);
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
          {canVerifyContinuationReceipt && (
            <section className="case-continuation-receipt-shell">
              <header>
                <div>
                  <span className="eyebrow">Resume result</span>
                  <strong>Continuation receipt</strong>
                </div>
                <button
                  className="button-secondary"
                  type="button"
                  disabled={continuationReceiptLoading}
                  onClick={() => void loadContinuationReceipt()}
                >
                  {continuationReceiptLoading
                    ? <SpinnerGap className="spin" size={16} />
                    : <ShieldCheck size={16} />}
                  {continuationReceiptLoading
                    ? "Verifying receipt…"
                    : continuationReceipt
                      ? "Verify receipt again"
                      : "Verify continuation receipt"}
                </button>
              </header>
              <p>
                Reconstruct the exact checkpoint and plan transition published by
                this plan-bound resume, independently of later continuations.
              </p>
              {continuationReceiptError && (
                <div className="case-sync-message is-error" role="alert">
                  <WarningCircle size={16} weight="fill" />
                  <span>{continuationReceiptError}</span>
                </div>
              )}
              {continuationReceipt && (
                <section
                  className="case-checkpoint-chain case-continuation-receipt"
                  aria-label="Verified continuation receipt"
                  role="status"
                >
                  <header>
                    <span>
                      <ShieldCheck size={18} />
                      <strong>Verified checkpoint transition</strong>
                    </span>
                    <code>{continuationReceipt.receipt.public_id}</code>
                  </header>
                  <div className="case-continuation-transition">
                    <article>
                      <small>Accepted input</small>
                      <b>Page {continuationReceipt.document.input.next_page_index}</b>
                      <code>{continuationReceipt.receipt.input_plan_public_id}</code>
                      <code>{continuationReceipt.receipt.input_checkpoint_public_id}</code>
                    </article>
                    <ArrowRight size={22} aria-hidden="true" />
                    <article>
                      <small>Published output</small>
                      <b>
                        {continuationReceipt.document.output.resume_state}
                        {continuationReceipt.document.output.next_page_index !== null
                          ? ` · next page ${continuationReceipt.document.output.next_page_index}`
                          : ""}
                      </b>
                      <code>{continuationReceipt.receipt.output_checkpoint_public_id}</code>
                      <code>{continuationReceipt.receipt.after_plan_public_id}</code>
                    </article>
                  </div>
                  <dl>
                    <div><dt>New revisions</dt><dd>+{continuationReceipt.receipt.revision_delta}</dd></div>
                    <div><dt>Provider pages</dt><dd>+{continuationReceipt.receipt.page_count_delta}</dd></div>
                    <div><dt>Successful pages</dt><dd>+{continuationReceipt.receipt.pages_succeeded_delta}</dd></div>
                    <div><dt>After-plan streams</dt><dd>{continuationReceipt.document.after_plan.plan.stream_count}</dd></div>
                  </dl>
                  <button
                    className="button-secondary case-checkpoint-chain-export"
                    type="button"
                    onClick={() => downloadContinuationReceipt(continuationReceipt)}
                  >
                    <DownloadSimple size={15} /> Export verified continuation receipt JSON
                  </button>
                  <small className="case-checkpoint-history-boundary">
                    {continuationReceipt.document.limitations[0]?.message}
                  </small>
                </section>
              )}
            </section>
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
                  <button
                    className="button-secondary case-checkpoint-plan-button"
                    type="button"
                    disabled={continuationPlanLoading}
                    onClick={() => void loadContinuationPlan()}
                  >
                    {continuationPlanLoading
                      ? <SpinnerGap className="spin" size={15} />
                      : <TreeStructure size={15} />}
                    {continuationPlanLoading
                      ? "Verifying plan…"
                      : continuationPlan
                        ? "Verify plan again"
                        : "Verify continuation plan"}
                  </button>
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
                              <small>Verify the current plan before resuming.</small>
                            )}
                          </div>
                        </li>
                      ))}
                      </ul>
                  )}
                  {continuationPlan && (
                    <section
                      className="case-checkpoint-chain case-continuation-plan"
                      aria-label="Verified continuation plan"
                    >
                      <header>
                        <span>
                          <TreeStructure size={18} />
                          <strong>Verified continuation plan</strong>
                        </span>
                        <code>{continuationPlan.plan.public_id}</code>
                      </header>
                      <dl>
                        <div><dt>Streams</dt><dd>{continuationPlan.plan.stream_count}</dd></div>
                        <div><dt>Ready</dt><dd>{continuationPlan.plan.ready_count}</dd></div>
                        <div><dt>Revisions</dt><dd>{continuationPlan.plan.revision_count}</dd></div>
                        <div><dt>Provider pages</dt><dd>{continuationPlan.plan.pages_succeeded}/{continuationPlan.plan.page_count}</dd></div>
                      </dl>
                      {continuationPlan.document.streams.length === 0 ? (
                        <span>No current provider stream checkpoints are available.</span>
                      ) : (
                        <ol>
                          {continuationPlan.document.streams.map((stream) => (
                            <li key={`${stream.provider}:${stream.stream_key}`}>
                              <span>
                                <b>{stream.provider} / {stream.stream_key}</b>
                                <small>
                                  {stream.revision_count} revisions
                                  {" · "}{stream.pages_succeeded}/{stream.page_count} pages
                                  {" · "}{stream.resume_state}
                                  {stream.next_page_index !== null
                                    ? ` · next page ${stream.next_page_index}`
                                    : stream.resume_blocker !== null
                                      ? ` · ${stream.resume_blocker}`
                                      : ""}
                                </small>
                                <code>{stream.chain_public_id}</code>
                              </span>
                              {stream.resume_state === "ready" && (
                                <button
                                  className="button-secondary"
                                  type="button"
                                  disabled={resumeDisabled}
                                  aria-label={`Resume planned ${stream.stream_key} stream`}
                                  onClick={() => void onResume(
                                    continuationPlan.plan.public_id,
                                    stream.tip_checkpoint.public_id,
                                  )}
                                >
                                  <ArrowClockwise size={15} /> Resume planned stream
                                </button>
                              )}
                            </li>
                          ))}
                        </ol>
                      )}
                      <button
                        className="button-secondary case-checkpoint-chain-export"
                        type="button"
                        onClick={() => downloadContinuationPlan(continuationPlan)}
                      >
                        <DownloadSimple size={15} /> Export verified continuation plan JSON
                      </button>
                      <small className="case-checkpoint-history-boundary">
                        {continuationPlan.document.limitations[
                          continuationPlan.document.limitations.length - 1
                        ]?.message}
                      </small>
                    </section>
                  )}
                  {continuationPlanError && (
                    <div className="case-sync-message is-error" role="alert">
                      <WarningCircle size={16} weight="fill" />
                      <span>{continuationPlanError}</span>
                    </div>
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
                      <>
                        <dl className="case-checkpoint-revision-detail" role="status">
                          <div><dt>Verified revision</dt><dd><code>{checkpointHistory.selected.checkpoint.public_id}</code></dd></div>
                          <div><dt>Source sync</dt><dd><code>{checkpointHistory.selected.document.source_sync_public_id}</code></dd></div>
                          <div><dt>Source manifest</dt><dd><code>{checkpointHistory.selected.document.source_manifest_public_id}</code></dd></div>
                          <div><dt>Parent revision</dt><dd><code>{checkpointHistory.selected.lineage.parent_checkpoint_public_id ?? "Root revision"}</code></dd></div>
                          <div><dt>Chain depth</dt><dd>{checkpointHistory.selected.lineage.chain_depth}</dd></div>
                          <div><dt>Resume state</dt><dd>{checkpointHistory.selected.document.resume_state}</dd></div>
                        </dl>
                        <button
                          className="button-secondary case-checkpoint-chain-button"
                          type="button"
                          disabled={checkpointHistory.chainLoading}
                          onClick={() => void checkpointHistory.loadChain(
                            checkpointHistory.selected!.checkpoint.public_id,
                          )}
                        >
                          {checkpointHistory.chainLoading
                            ? <SpinnerGap className="spin" size={15} />
                            : <TreeStructure size={15} />}
                          {checkpointHistory.chainLoading
                            ? "Verifying chain…"
                            : "Verify checkpoint chain"}
                        </button>
                      </>
                    )}
                    {checkpointHistory.chain && (
                      <section className="case-checkpoint-chain" aria-label="Verified checkpoint chain">
                        <header>
                          <span>
                            <TreeStructure size={18} />
                            <strong>Content-addressed chain</strong>
                          </span>
                          <code>{checkpointHistory.chain.chain.public_id}</code>
                        </header>
                        <dl>
                          <div><dt>Revisions</dt><dd>{checkpointHistory.chain.chain.revision_count}</dd></div>
                          <div><dt>Provider pages</dt><dd>{checkpointHistory.chain.chain.pages_succeeded}/{checkpointHistory.chain.chain.page_count}</dd></div>
                          <div><dt>Current state</dt><dd>{checkpointHistory.chain.document.current_resume_state}</dd></div>
                          <div><dt>Next page</dt><dd>{checkpointHistory.chain.document.next_page_index ?? "None"}</dd></div>
                        </dl>
                        <ol>
                          {checkpointHistory.chain.document.revisions.map((revision) => (
                            <li key={revision.checkpoint.public_id}>
                              <span>
                                <b>#{revision.ordinal + 1} · {revision.acquisition_mode}</b>
                                <small>
                                  {revision.pages_succeeded}/{revision.page_count} pages
                                  {" · "}{revision.checkpoint.resume_state}
                                </small>
                                <code>{revision.checkpoint.public_id}</code>
                              </span>
                            </li>
                          ))}
                        </ol>
                        <button
                          className="button-secondary case-checkpoint-chain-export"
                          type="button"
                          onClick={() => downloadCheckpointChain(checkpointHistory.chain!)}
                        >
                          <DownloadSimple size={15} /> Export verified chain JSON
                        </button>
                        <small className="case-checkpoint-history-boundary">
                          {checkpointHistory.chain.document.limitations[0]?.message}
                        </small>
                      </section>
                    )}
                    {(checkpointHistory.historyError || checkpointHistory.selectionError || checkpointHistory.chainError) && (
                      <div className="case-sync-message is-error" role="alert">
                        <WarningCircle size={16} weight="fill" />
                        <span>{checkpointHistory.historyError ?? checkpointHistory.selectionError ?? checkpointHistory.chainError}</span>
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
