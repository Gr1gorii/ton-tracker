import { useCallback, useEffect, useRef, useState } from "react";

import { getWalletIngestionRunCatalog } from "./api";
import type { WalletIngestionRunCatalogItem } from "./types";
import { validateWalletRunCatalogResponse } from "./walletRunCatalog";

export const RECENT_RUN_CATALOG_LIMIT = 8;

export interface WalletRunCatalogState {
  runs: WalletIngestionRunCatalogItem[];
  truncated: boolean;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
}

export function useWalletRunCatalog(): WalletRunCatalogState {
  const [runs, setRuns] = useState<WalletIngestionRunCatalogItem[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setLoading(true);
    setError(null);

    try {
      const response = await getWalletIngestionRunCatalog(
        RECENT_RUN_CATALOG_LIMIT,
        nextController.signal,
      );
      const validated = validateWalletRunCatalogResponse(
        response,
        RECENT_RUN_CATALOG_LIMIT,
      );
      if (requestSequence.current !== sequence) return;
      setRuns(validated.runs);
      setTruncated(validated.truncated);
    } catch (caught) {
      if (nextController.signal.aborted || requestSequence.current !== sequence) {
        return;
      }
      setError(
        caught instanceof Error ? caught.message : "Unknown recent-run error",
      );
    } finally {
      if (requestSequence.current === sequence) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    return () => {
      requestSequence.current += 1;
      controller.current?.abort();
    };
  }, [refresh]);

  return { runs, truncated, loading, error, refresh };
}
