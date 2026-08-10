import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CaseActivityUrlState } from "./caseActivityQuery";
import { getWalletCaseActivity, getWalletCaseActivityDetail } from "./walletCaseApi";
import type {
  WalletCaseActivityDetailResponse,
  WalletCaseActivityItem,
  WalletCaseActivityResponse,
} from "./walletCaseActivity";

export interface WalletCaseActivityController {
  response: WalletCaseActivityResponse | null;
  items: WalletCaseActivityItem[];
  loading: boolean;
  loadingMore: boolean;
  error: string | null;
  reload: () => void;
  loadMore: () => Promise<void>;
  detail: WalletCaseActivityDetailResponse | null;
  detailLoading: boolean;
  detailError: string | null;
  retryDetail: () => void;
}

export function useWalletCaseActivity({
  caseId,
  urlState,
  onSnapshotPinned,
  enabled = true,
}: {
  caseId: string;
  urlState: CaseActivityUrlState;
  onSnapshotPinned: (snapshotId: string) => void;
  enabled?: boolean;
}): WalletCaseActivityController {
  const [response, setResponse] = useState<WalletCaseActivityResponse | null>(null);
  const [items, setItems] = useState<WalletCaseActivityItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadVersion, setReloadVersion] = useState(0);
  const [detail, setDetail] = useState<WalletCaseActivityDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailVersion, setDetailVersion] = useState(0);
  const listGeneration = useRef(0);
  const detailGeneration = useRef(0);
  const listController = useRef<AbortController | null>(null);
  const detailController = useRef<AbortController | null>(null);
  const loadMoreInFlight = useRef(false);

  const filterKey = useMemo(() => JSON.stringify(urlState.filters), [urlState.filters]);

  useEffect(() => {
    listController.current?.abort();
    if (!enabled) {
      listGeneration.current += 1;
      setLoading(false);
      setLoadingMore(false);
      setError(null);
      setResponse(null);
      setItems([]);
      return;
    }
    const controller = new AbortController();
    listController.current = controller;
    const generation = ++listGeneration.current;
    setLoading(true);
    setLoadingMore(false);
    loadMoreInFlight.current = false;
    setError(null);
    setResponse(null);
    setItems([]);
    void getWalletCaseActivity(caseId, {
      snapshot: urlState.snapshot,
      limit: 50,
      cursor: null,
      ...urlState.filters,
    }, controller.signal).then((result) => {
      if (controller.signal.aborted || generation !== listGeneration.current) return;
      setResponse(result);
      setItems(result.items);
      if (urlState.snapshot === null && result.snapshot !== null) {
        onSnapshotPinned(result.snapshot.public_id);
      }
    }).catch((caught) => {
      if (controller.signal.aborted || generation !== listGeneration.current) return;
      setError(caught instanceof Error ? caught.message : "Wallet Case Activity is unavailable");
    }).finally(() => {
      if (!controller.signal.aborted && generation === listGeneration.current) setLoading(false);
    });
    return () => controller.abort();
  }, [caseId, enabled, filterKey, onSnapshotPinned, reloadVersion, urlState.snapshot]);

  const loadMore = useCallback(async () => {
    if (
      loadMoreInFlight.current || loading || loadingMore || !response?.snapshot ||
      !response.page.has_more || !response.page.next_cursor
    ) return;
    loadMoreInFlight.current = true;
    setLoadingMore(true);
    setError(null);
    const controller = new AbortController();
    listController.current = controller;
    const generation = listGeneration.current;
    try {
      const next = await getWalletCaseActivity(caseId, {
        snapshot: response.snapshot.public_id,
        limit: response.page.limit,
        cursor: response.page.next_cursor,
        ...urlState.filters,
      }, controller.signal);
      if (controller.signal.aborted || generation !== listGeneration.current) return;
      if (next.snapshot?.public_id !== response.snapshot.public_id) {
        throw new Error("Wallet Case Activity snapshot changed during pagination");
      }
      const identities = new Set(items.map((item) => item.public_id));
      if (next.items.some((item) => identities.has(item.public_id))) {
        throw new Error("Wallet Case Activity pages overlap");
      }
      setItems((current) => [...current, ...next.items]);
      setResponse(next);
    } catch (caught) {
      if (!controller.signal.aborted && generation === listGeneration.current) {
        setError(caught instanceof Error ? caught.message : "More Activity rows are unavailable");
      }
    } finally {
      if (generation === listGeneration.current) setLoadingMore(false);
      loadMoreInFlight.current = false;
    }
  }, [caseId, items, loading, loadingMore, response, urlState.filters]);

  useEffect(() => {
    detailController.current?.abort();
    setDetail(null);
    setDetailError(null);
    const selectedId = urlState.selectedActivityId;
    const snapshotId = urlState.snapshot;
    if (!enabled || !selectedId || !snapshotId) {
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    detailController.current = controller;
    const generation = ++detailGeneration.current;
    setDetailLoading(true);
    void getWalletCaseActivityDetail(caseId, snapshotId, selectedId, controller.signal).then((result) => {
      if (!controller.signal.aborted && generation === detailGeneration.current) setDetail(result);
    }).catch((caught) => {
      if (!controller.signal.aborted && generation === detailGeneration.current) {
        setDetailError(caught instanceof Error ? caught.message : "Activity detail is unavailable");
      }
    }).finally(() => {
      if (!controller.signal.aborted && generation === detailGeneration.current) setDetailLoading(false);
    });
    return () => controller.abort();
  }, [caseId, detailVersion, enabled, urlState.selectedActivityId, urlState.snapshot]);

  useEffect(() => () => {
    listController.current?.abort();
    detailController.current?.abort();
  }, []);

  return {
    response,
    items,
    loading,
    loadingMore,
    error,
    reload: () => setReloadVersion((value) => value + 1),
    loadMore,
    detail,
    detailLoading,
    detailError,
    retryDetail: () => setDetailVersion((value) => value + 1),
  };
}
