import { useCallback, useEffect, useRef, useState } from "react";

import { getWalletCaseObservedHistoryFloor } from "./walletCaseApi";
import type { WalletCaseObservedHistoryFloorResponse } from "./walletCaseStreamCheckpoint";

export interface WalletCaseObservedHistoryFloorController {
  floor: WalletCaseObservedHistoryFloorResponse | null;
  state: "idle" | "loading";
  error: string | null;
  verify: () => Promise<void>;
}

export function useWalletCaseObservedHistoryFloor(
  caseId: string,
  evidenceScope: string = caseId,
): WalletCaseObservedHistoryFloorController {
  const [floor, setFloor] = useState<WalletCaseObservedHistoryFloorResponse | null>(null);
  const [state, setState] = useState<WalletCaseObservedHistoryFloorController["state"]>("idle");
  const [error, setError] = useState<string | null>(null);
  const requestRef = useRef<AbortController | null>(null);

  useEffect(() => {
    requestRef.current?.abort();
    requestRef.current = null;
    setFloor(null);
    setState("idle");
    setError(null);
    return () => requestRef.current?.abort();
  }, [caseId, evidenceScope]);

  const verify = useCallback(async () => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    setFloor(null);
    setState("loading");
    setError(null);
    try {
      const response = await getWalletCaseObservedHistoryFloor(
        caseId,
        controller.signal,
      );
      if (!controller.signal.aborted) setFloor(response);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setError(
          cause instanceof Error
            ? cause.message
            : "Observed history floor verification failed.",
        );
      }
    } finally {
      if (requestRef.current === controller) {
        requestRef.current = null;
        setState("idle");
      }
    }
  }, [caseId]);

  return { floor, state, error, verify };
}
