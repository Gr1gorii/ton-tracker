import { useCallback, useEffect, useRef, useState } from "react";

import { getWalletCaseEarliestActivityAnchor } from "./walletCaseApi";
import type { WalletCaseEarliestActivityAnchorResponse } from "./walletCaseStreamCheckpoint";

export interface WalletCaseEarliestActivityAnchorController {
  anchor: WalletCaseEarliestActivityAnchorResponse | null;
  state: "idle" | "loading";
  error: string | null;
  verify: () => Promise<void>;
}

export function useWalletCaseEarliestActivityAnchor(
  caseId: string,
  evidenceScope: string = caseId,
): WalletCaseEarliestActivityAnchorController {
  const [anchor, setAnchor] = useState<WalletCaseEarliestActivityAnchorResponse | null>(null);
  const [state, setState] = useState<WalletCaseEarliestActivityAnchorController["state"]>("idle");
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setAnchor(null);
    setState("idle");
    setError(null);
    return () => requestRef.current?.abort();
  }, [caseId, evidenceScope]);

  const verify = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setAnchor(null);
    setState("loading");
    setError(null);
    try {
      const response = await getWalletCaseEarliestActivityAnchor(
        caseId,
        controller.signal,
      );
      if (!controller.signal.aborted) setAnchor(response);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Earliest activity anchor verification failed.",
        );
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setState("idle");
      }
    }
  }, [caseId]);

  return { anchor, state, error, verify };
}
