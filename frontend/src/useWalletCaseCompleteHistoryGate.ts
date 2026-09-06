import { useCallback, useEffect, useRef, useState } from "react";

import { getWalletCaseCompleteHistoryGate } from "./walletCaseApi";
import type { WalletCaseCompleteHistoryGateResponse } from "./walletCaseStreamCheckpoint";

export interface WalletCaseCompleteHistoryGateController {
  gate: WalletCaseCompleteHistoryGateResponse | null;
  state: "idle" | "loading";
  error: string | null;
  verify: () => Promise<void>;
}

export function useWalletCaseCompleteHistoryGate(
  caseId: string,
  evidenceScope: string = caseId,
): WalletCaseCompleteHistoryGateController {
  const [gate, setGate] = useState<WalletCaseCompleteHistoryGateResponse | null>(null);
  const [state, setState] = useState<WalletCaseCompleteHistoryGateController["state"]>("idle");
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setGate(null);
    setState("idle");
    setError(null);
    return () => requestRef.current?.abort();
  }, [caseId, evidenceScope]);

  const verify = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setGate(null);
    setState("loading");
    setError(null);
    try {
      const response = await getWalletCaseCompleteHistoryGate(
        caseId,
        controller.signal,
      );
      if (!controller.signal.aborted) setGate(response);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Complete-history gate verification failed.",
        );
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setState("idle");
      }
    }
  }, [caseId]);

  return { gate, state, error, verify };
}
