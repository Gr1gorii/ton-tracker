import { useEffect, useRef, useState } from "react";
import {
  Fingerprint,
  ShieldCheck,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import type { WalletCaseSync } from "../walletCase";
import { getWalletCaseSyncManifest } from "../walletCaseApi";
import type { WalletCaseSyncManifestResponse } from "../walletCaseSyncManifest";

export default function CaseAcquisitionManifest({
  caseId,
  snapshot,
}: {
  caseId: string;
  snapshot: WalletCaseSync;
}) {
  const descriptor = snapshot.acquisition_manifest;
  const [detail, setDetail] = useState<WalletCaseSyncManifestResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setDetail(null);
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
      const response = await getWalletCaseSyncManifest(
        caseId,
        snapshot.public_id,
        controller.signal,
      );
      if (response.manifest.public_id !== descriptor.public_id) {
        throw new Error("The loaded manifest does not match this snapshot descriptor.");
      }
      setDetail(response);
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
                {detail.document.acquisition_mode === "incremental"
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
