import { useCallback, useEffect, useRef, useState } from "react";

import type { WalletCaseLimitation } from "./walletCase";
import {
  getWalletCaseStreamCheckpoint,
  getWalletCaseStreamCheckpointHistory,
} from "./walletCaseApi";
import type {
  WalletCaseStreamCheckpointDetailResponse,
  WalletCaseStreamCheckpointHistoryItem,
} from "./walletCaseStreamCheckpoint";

const PAGE_LIMIT = 10;

export interface WalletCaseCheckpointHistoryView {
  revisionCutoffPublicId: string | null;
  totalRevisions: number;
  items: WalletCaseStreamCheckpointHistoryItem[];
  hasMore: boolean;
  nextCursor: string | null;
  limitations: WalletCaseLimitation[];
}

export interface WalletCaseCheckpointHistoryController {
  history: WalletCaseCheckpointHistoryView | null;
  historyState: "idle" | "loading" | "loading-more";
  historyError: string | null;
  selected: WalletCaseStreamCheckpointDetailResponse | null;
  selectionLoading: boolean;
  selectionError: string | null;
  load: () => Promise<void>;
  loadMore: () => Promise<void>;
  inspect: (checkpointPublicId: string) => Promise<void>;
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

function view(
  response: Awaited<ReturnType<typeof getWalletCaseStreamCheckpointHistory>>,
): WalletCaseCheckpointHistoryView {
  return {
    revisionCutoffPublicId: response.revision_cutoff_public_id,
    totalRevisions: response.aggregate.total_revisions,
    items: response.items,
    hasMore: response.page.has_more,
    nextCursor: response.page.next_cursor,
    limitations: response.limitations,
  };
}

function mergeLimitations(
  current: WalletCaseLimitation[],
  next: WalletCaseLimitation[],
): WalletCaseLimitation[] {
  return [...new Map(
    [...current, ...next].map((item) => [item.code, item]),
  ).values()];
}

export function useWalletCaseCheckpointHistory(
  caseId: string,
): WalletCaseCheckpointHistoryController {
  const [history, setHistory] = useState<WalletCaseCheckpointHistoryView | null>(null);
  const [historyState, setHistoryState] = useState<WalletCaseCheckpointHistoryController["historyState"]>("idle");
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selected, setSelected] = useState<WalletCaseStreamCheckpointDetailResponse | null>(null);
  const [selectionLoading, setSelectionLoading] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const historyRef = useRef<WalletCaseCheckpointHistoryView | null>(null);
  const historyRequestRef = useRef<AbortController | null>(null);
  const detailRequestRef = useRef<AbortController | null>(null);

  const publishHistory = useCallback((next: WalletCaseCheckpointHistoryView | null) => {
    historyRef.current = next;
    setHistory(next);
  }, []);

  useEffect(() => {
    historyRequestRef.current?.abort();
    detailRequestRef.current?.abort();
    historyRequestRef.current = null;
    detailRequestRef.current = null;
    publishHistory(null);
    setHistoryState("idle");
    setHistoryError(null);
    setSelected(null);
    setSelectionLoading(false);
    setSelectionError(null);
    return () => {
      historyRequestRef.current?.abort();
      detailRequestRef.current?.abort();
    };
  }, [caseId, publishHistory]);

  const load = useCallback(async () => {
    historyRequestRef.current?.abort();
    const controller = new AbortController();
    historyRequestRef.current = controller;
    setHistoryState("loading");
    setHistoryError(null);
    setSelected(null);
    setSelectionError(null);
    try {
      const response = await getWalletCaseStreamCheckpointHistory({
        caseId,
        limit: PAGE_LIMIT,
        signal: controller.signal,
      });
      if (!controller.signal.aborted) publishHistory(view(response));
    } catch (cause) {
      if (!controller.signal.aborted) {
        setHistoryError(message(cause, "Checkpoint history read failed."));
      }
    } finally {
      if (historyRequestRef.current === controller) {
        historyRequestRef.current = null;
        setHistoryState("idle");
      }
    }
  }, [caseId, publishHistory]);

  const loadMore = useCallback(async () => {
    const current = historyRef.current;
    if (!current?.hasMore || current.nextCursor === null || historyRequestRef.current) {
      return;
    }
    const controller = new AbortController();
    historyRequestRef.current = controller;
    setHistoryState("loading-more");
    setHistoryError(null);
    try {
      const response = await getWalletCaseStreamCheckpointHistory({
        caseId,
        limit: PAGE_LIMIT,
        cursor: current.nextCursor,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (
        response.revision_cutoff_public_id !== current.revisionCutoffPublicId ||
        response.aggregate.total_revisions !== current.totalRevisions
      ) {
        throw new Error("Checkpoint history continuation changed its frozen revision set.");
      }
      const known = new Set(current.items.map((item) => item.checkpoint.public_id));
      if (response.items.some((item) => known.has(item.checkpoint.public_id))) {
        throw new Error("Checkpoint history continuation repeated a revision.");
      }
      publishHistory({
        revisionCutoffPublicId: current.revisionCutoffPublicId,
        totalRevisions: current.totalRevisions,
        items: [...current.items, ...response.items],
        hasMore: response.page.has_more,
        nextCursor: response.page.next_cursor,
        limitations: mergeLimitations(current.limitations, response.limitations),
      });
    } catch (cause) {
      if (!controller.signal.aborted) {
        setHistoryError(message(cause, "Checkpoint history continuation failed."));
      }
    } finally {
      if (historyRequestRef.current === controller) {
        historyRequestRef.current = null;
        setHistoryState("idle");
      }
    }
  }, [caseId, publishHistory]);

  const inspect = useCallback(async (checkpointPublicId: string) => {
    detailRequestRef.current?.abort();
    const controller = new AbortController();
    detailRequestRef.current = controller;
    setSelectionLoading(true);
    setSelectionError(null);
    try {
      const response = await getWalletCaseStreamCheckpoint(
        caseId,
        checkpointPublicId,
        controller.signal,
      );
      if (!controller.signal.aborted) setSelected(response);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setSelectionError(message(cause, "Checkpoint revision read failed."));
      }
    } finally {
      if (detailRequestRef.current === controller) {
        detailRequestRef.current = null;
        setSelectionLoading(false);
      }
    }
  }, [caseId]);

  return {
    history,
    historyState,
    historyError,
    selected,
    selectionLoading,
    selectionError,
    load,
    loadMore,
    inspect,
  };
}
