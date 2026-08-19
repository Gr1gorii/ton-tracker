import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CaseFindingsUrlState } from "./caseFindingsQuery";
import type { WalletCaseFindingsResponse } from "./walletCaseFindings";
import { getWalletCaseFindings } from "./walletCaseFindingsApi";

export function useWalletCaseFindings({
  caseId,
  urlState,
  enabled,
  onSnapshotPinned,
}: {
  caseId: string;
  urlState: CaseFindingsUrlState;
  enabled: boolean;
  onSnapshotPinned: (snapshotId: string) => void;
}) {
  const [response, setResponse] = useState<WalletCaseFindingsResponse | null>(null);
  const [responseScope, setResponseScope] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const controllerRef = useRef<AbortController | null>(null);
  const generation = useRef(0);
  const scope = `${caseId}|${urlState.snapshot ?? "latest"}`;

  useEffect(() => {
    controllerRef.current?.abort();
    generation.current += 1;
    setResponse(null);
    setResponseScope(null);
    setError(null);
    if (!enabled) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    controllerRef.current = controller;
    const requestGeneration = generation.current;
    setLoading(true);
    void getWalletCaseFindings(caseId, urlState.snapshot, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || requestGeneration !== generation.current) return;
        setResponse(result);
        setResponseScope(scope);
        if (urlState.snapshot === null && result.snapshot_public_id !== null) {
          onSnapshotPinned(result.snapshot_public_id);
        }
      })
      .catch((caught) => {
        if (!controller.signal.aborted && requestGeneration === generation.current) {
          setError(caught instanceof Error ? caught.message : "Wallet Case Findings is unavailable.");
        }
      })
      .finally(() => {
        if (controllerRef.current === controller) controllerRef.current = null;
        if (!controller.signal.aborted && requestGeneration === generation.current) setLoading(false);
      });
    return () => controller.abort();
  }, [caseId, enabled, onSnapshotPinned, scope, urlState.snapshot, version]);

  useEffect(() => () => {
    generation.current += 1;
    controllerRef.current?.abort();
  }, []);

  const reload = useCallback(() => setVersion((current) => current + 1), []);
  const visibleResponse = responseScope === scope ? response : null;
  return useMemo(() => ({ response: visibleResponse, loading, error, reload }), [error, loading, reload, visibleResponse]);
}
