import { useCallback, useEffect, useRef, useState } from "react";

import type { WalletCaseLimitation } from "./walletCase";
import {
  getWalletCaseBackfillOutcome,
  getWalletCaseBackfillOutcomeHistory,
} from "./walletCaseApi";
import type {
  WalletCaseBackfillOutcomeHistoryItem,
  WalletCaseBackfillOutcomeResponse,
} from "./walletCaseStreamCheckpoint";

const PAGE_LIMIT = 10;

export interface WalletCaseBackfillHistoryView {
  syncCutoffPublicId: string | null;
  totalOutcomes: number;
  items: WalletCaseBackfillOutcomeHistoryItem[];
  hasMore: boolean;
  nextCursor: string | null;
  limitations: WalletCaseLimitation[];
}

export interface WalletCaseBackfillHistoryController {
  history: WalletCaseBackfillHistoryView | null;
  historyState: "idle" | "loading" | "loading-more";
  historyError: string | null;
  selected: WalletCaseBackfillOutcomeResponse | null;
  selectionLoading: boolean;
  selectionError: string | null;
  load: () => Promise<void>;
  loadMore: () => Promise<void>;
  inspect: (syncPublicId: string) => Promise<void>;
}

function message(cause: unknown, fallback: string): string {
  return cause instanceof Error ? cause.message : fallback;
}

function view(
  response: Awaited<ReturnType<typeof getWalletCaseBackfillOutcomeHistory>>,
): WalletCaseBackfillHistoryView {
  return {
    syncCutoffPublicId: response.sync_cutoff_public_id,
    totalOutcomes: response.aggregate.total_outcomes,
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

export function useWalletCaseBackfillHistory(
  caseId: string,
): WalletCaseBackfillHistoryController {
  const [history, setHistory] = useState<WalletCaseBackfillHistoryView | null>(null);
  const [historyState, setHistoryState] = useState<WalletCaseBackfillHistoryController["historyState"]>("idle");
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [selected, setSelected] = useState<WalletCaseBackfillOutcomeResponse | null>(null);
  const [selectionLoading, setSelectionLoading] = useState(false);
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const historyRef = useRef<WalletCaseBackfillHistoryView | null>(null);
  const historyRequestRef = useRef<AbortController | null>(null);
  const selectionRequestRef = useRef<AbortController | null>(null);

  const publishHistory = useCallback((next: WalletCaseBackfillHistoryView | null) => {
    historyRef.current = next;
    setHistory(next);
  }, []);

  useEffect(() => {
    historyRequestRef.current?.abort();
    selectionRequestRef.current?.abort();
    historyRequestRef.current = null;
    selectionRequestRef.current = null;
    publishHistory(null);
    setHistoryState("idle");
    setHistoryError(null);
    setSelected(null);
    setSelectionLoading(false);
    setSelectionError(null);
    return () => {
      historyRequestRef.current?.abort();
      selectionRequestRef.current?.abort();
    };
  }, [caseId, publishHistory]);

  const load = useCallback(async () => {
    historyRequestRef.current?.abort();
    selectionRequestRef.current?.abort();
    selectionRequestRef.current = null;
    const controller = new AbortController();
    historyRequestRef.current = controller;
    publishHistory(null);
    setHistoryState("loading");
    setHistoryError(null);
    setSelected(null);
    setSelectionLoading(false);
    setSelectionError(null);
    try {
      const response = await getWalletCaseBackfillOutcomeHistory({
        caseId,
        limit: PAGE_LIMIT,
        signal: controller.signal,
      });
      if (!controller.signal.aborted) publishHistory(view(response));
    } catch (cause) {
      if (!controller.signal.aborted) {
        setHistoryError(message(cause, "Backfill Outcome history read failed."));
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
      const response = await getWalletCaseBackfillOutcomeHistory({
        caseId,
        limit: PAGE_LIMIT,
        cursor: current.nextCursor,
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (
        response.sync_cutoff_public_id !== current.syncCutoffPublicId ||
        response.aggregate.total_outcomes !== current.totalOutcomes
      ) {
        throw new Error("Backfill Outcome history continuation changed its frozen result set.");
      }
      const outcomeIds = new Set(current.items.map((item) => item.outcome.public_id));
      const syncIds = new Set(current.items.map((item) => item.outcome.sync_public_id));
      if (response.items.some((item) => (
        outcomeIds.has(item.outcome.public_id) || syncIds.has(item.outcome.sync_public_id)
      ))) {
        throw new Error("Backfill Outcome history continuation repeated a result.");
      }
      publishHistory({
        syncCutoffPublicId: current.syncCutoffPublicId,
        totalOutcomes: current.totalOutcomes,
        items: [...current.items, ...response.items],
        hasMore: response.page.has_more,
        nextCursor: response.page.next_cursor,
        limitations: mergeLimitations(current.limitations, response.limitations),
      });
    } catch (cause) {
      if (!controller.signal.aborted) {
        setHistoryError(message(cause, "Backfill Outcome history continuation failed."));
      }
    } finally {
      if (historyRequestRef.current === controller) {
        historyRequestRef.current = null;
        setHistoryState("idle");
      }
    }
  }, [caseId, publishHistory]);

  const inspect = useCallback(async (syncPublicId: string) => {
    selectionRequestRef.current?.abort();
    const controller = new AbortController();
    selectionRequestRef.current = controller;
    setSelectionLoading(true);
    setSelectionError(null);
    try {
      const response = await getWalletCaseBackfillOutcome(
        caseId,
        syncPublicId,
        controller.signal,
      );
      if (!controller.signal.aborted) setSelected(response);
    } catch (cause) {
      if (!controller.signal.aborted) {
        setSelectionError(message(cause, "Backfill Outcome verification failed."));
      }
    } finally {
      if (selectionRequestRef.current === controller) {
        selectionRequestRef.current = null;
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
