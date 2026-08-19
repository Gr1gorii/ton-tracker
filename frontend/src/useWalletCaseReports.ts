import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { CaseReportsUrlState } from "./caseReportsQuery";
import type { WalletCaseReportResponse } from "./walletCaseReport";
import {
  captureWalletCaseReportRevision,
  getWalletCaseReport,
  getWalletCaseReportRevision,
  listWalletCaseReportRevisions,
} from "./walletCaseReportApi";
import type {
  WalletCaseReportRevisionCatalog,
  WalletCaseReportRevisionDetailResponse,
  WalletCaseReportRevisionSummary,
} from "./walletCaseReportRevisions";

export function useWalletCaseReports({
  caseId,
  urlState,
  enabled,
  onSnapshotPinned,
  onRevisionCaptured,
}: {
  caseId: string;
  urlState: CaseReportsUrlState;
  enabled: boolean;
  onSnapshotPinned: (snapshotId: string) => void;
  onRevisionCaptured: (revision: WalletCaseReportRevisionSummary) => void;
}) {
  const [current, setCurrent] = useState<WalletCaseReportResponse | null>(null);
  const [currentScope, setCurrentScope] = useState<string | null>(null);
  const [currentLoading, setCurrentLoading] = useState(false);
  const [currentError, setCurrentError] = useState<string | null>(null);
  const [currentVersion, setCurrentVersion] = useState(0);
  const currentController = useRef<AbortController | null>(null);
  const currentGeneration = useRef(0);
  const currentScopeKey = `${caseId}|${urlState.snapshot ?? "latest"}`;

  const [catalog, setCatalog] = useState<WalletCaseReportRevisionCatalog | null>(null);
  const [catalogScope, setCatalogScope] = useState<string | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [catalogVersion, setCatalogVersion] = useState(0);
  const catalogController = useRef<AbortController | null>(null);
  const catalogGeneration = useRef(0);

  const [detail, setDetail] = useState<WalletCaseReportRevisionDetailResponse | null>(null);
  const [detailScope, setDetailScope] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [detailVersion, setDetailVersion] = useState(0);
  const detailController = useRef<AbortController | null>(null);
  const detailGeneration = useRef(0);
  const detailScopeKey = `${caseId}|${urlState.snapshot ?? "none"}|${urlState.revision ?? "none"}`;

  const [capturing, setCapturing] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const captureController = useRef<AbortController | null>(null);

  useEffect(() => {
    currentController.current?.abort();
    const requestGeneration = ++currentGeneration.current;
    setCurrent(null);
    setCurrentScope(null);
    setCurrentError(null);
    if (!enabled) {
      setCurrentLoading(false);
      return;
    }
    const controller = new AbortController();
    currentController.current = controller;
    setCurrentLoading(true);
    void getWalletCaseReport(caseId, urlState.snapshot, controller.signal)
      .then((response) => {
        if (controller.signal.aborted || requestGeneration !== currentGeneration.current) return;
        setCurrent(response);
        setCurrentScope(currentScopeKey);
        if (urlState.snapshot === null && response.snapshot_public_id !== null) onSnapshotPinned(response.snapshot_public_id);
      })
      .catch((caught) => {
        if (!controller.signal.aborted && requestGeneration === currentGeneration.current) setCurrentError(message(caught, "Wallet Case report is unavailable."));
      })
      .finally(() => {
        if (currentController.current === controller) currentController.current = null;
        if (!controller.signal.aborted && requestGeneration === currentGeneration.current) setCurrentLoading(false);
      });
    return () => controller.abort();
  }, [caseId, currentScopeKey, currentVersion, enabled, onSnapshotPinned, urlState.snapshot]);

  useEffect(() => {
    catalogController.current?.abort();
    const requestGeneration = ++catalogGeneration.current;
    setCatalog(null);
    setCatalogScope(null);
    setCatalogError(null);
    if (!enabled) {
      setCatalogLoading(false);
      return;
    }
    const controller = new AbortController();
    catalogController.current = controller;
    setCatalogLoading(true);
    void listWalletCaseReportRevisions(caseId, 10, null, controller.signal)
      .then((response) => {
        if (controller.signal.aborted || requestGeneration !== catalogGeneration.current) return;
        setCatalog(response);
        setCatalogScope(caseId);
      })
      .catch((caught) => {
        if (!controller.signal.aborted && requestGeneration === catalogGeneration.current) setCatalogError(message(caught, "Saved report history is unavailable."));
      })
      .finally(() => {
        if (catalogController.current === controller) catalogController.current = null;
        if (!controller.signal.aborted && requestGeneration === catalogGeneration.current) setCatalogLoading(false);
      });
    return () => controller.abort();
  }, [caseId, catalogVersion, enabled]);

  useEffect(() => {
    detailController.current?.abort();
    const requestGeneration = ++detailGeneration.current;
    setDetail(null);
    setDetailScope(null);
    setDetailError(null);
    if (!enabled || urlState.revision === null || urlState.snapshot === null) {
      setDetailLoading(false);
      return;
    }
    const controller = new AbortController();
    detailController.current = controller;
    setDetailLoading(true);
    void getWalletCaseReportRevision(caseId, urlState.revision, controller.signal)
      .then((response) => {
        if (controller.signal.aborted || requestGeneration !== detailGeneration.current) return;
        if (response.revision.snapshot_public_id !== urlState.snapshot) throw new Error("Saved report revision does not match the pinned URL snapshot.");
        setDetail(response);
        setDetailScope(detailScopeKey);
      })
      .catch((caught) => {
        if (!controller.signal.aborted && requestGeneration === detailGeneration.current) setDetailError(message(caught, "Saved report revision is unavailable."));
      })
      .finally(() => {
        if (detailController.current === controller) detailController.current = null;
        if (!controller.signal.aborted && requestGeneration === detailGeneration.current) setDetailLoading(false);
      });
    return () => controller.abort();
  }, [caseId, detailScopeKey, detailVersion, enabled, urlState.revision, urlState.snapshot]);

  useEffect(() => {
    captureController.current?.abort();
    captureController.current = null;
    setCapturing(false);
    setCaptureError(null);
  }, [currentScopeKey]);

  useEffect(() => () => {
    currentGeneration.current += 1;
    catalogGeneration.current += 1;
    detailGeneration.current += 1;
    currentController.current?.abort();
    catalogController.current?.abort();
    detailController.current?.abort();
    captureController.current?.abort();
  }, []);

  const capture = useCallback(async () => {
    const snapshot = currentScope === currentScopeKey ? current?.snapshot_public_id ?? null : null;
    if (snapshot === null || captureController.current !== null) return;
    const controller = new AbortController();
    captureController.current = controller;
    setCapturing(true);
    setCaptureError(null);
    try {
      const response = await captureWalletCaseReportRevision(caseId, snapshot, controller.signal);
      if (controller.signal.aborted) return;
      onRevisionCaptured(response.revision);
      setCatalogVersion((value) => value + 1);
    } catch (caught) {
      if (!controller.signal.aborted) setCaptureError(message(caught, "Report revision could not be saved."));
    } finally {
      if (captureController.current === controller) captureController.current = null;
      if (!controller.signal.aborted) setCapturing(false);
    }
  }, [caseId, current, currentScope, currentScopeKey, onRevisionCaptured]);

  const loadMore = useCallback(async () => {
    if (catalogScope !== caseId || catalog === null || !catalog.page.has_more || catalog.page.next_cursor === null || catalogLoading) return;
    const expectedCutoff = catalog.revision_cutoff_public_id;
    const previousIds = new Set(catalog.items.map((item) => item.public_id));
    const controller = new AbortController();
    catalogController.current = controller;
    setCatalogLoading(true);
    setCatalogError(null);
    try {
      const response = await listWalletCaseReportRevisions(caseId, catalog.page.limit, catalog.page.next_cursor, controller.signal);
      if (controller.signal.aborted) return;
      if (
        response.revision_cutoff_public_id !== expectedCutoff
        || response.aggregate.total_revisions !== catalog.aggregate.total_revisions
        || response.items.some((item) => previousIds.has(item.public_id))
      ) {
        throw new Error("Saved report pagination changed scope or repeated a revision.");
      }
      const items = [...catalog.items, ...response.items];
      setCatalog({ ...response, items, aggregate: { ...response.aggregate, returned_count: items.length } });
      setCatalogScope(caseId);
    } catch (caught) {
      if (!controller.signal.aborted) setCatalogError(message(caught, "More saved reports could not be loaded."));
    } finally {
      if (catalogController.current === controller) catalogController.current = null;
      if (!controller.signal.aborted) setCatalogLoading(false);
    }
  }, [caseId, catalog, catalogLoading, catalogScope]);

  return useMemo(() => ({
    current: currentScope === currentScopeKey ? current : null,
    currentLoading,
    currentError,
    reloadCurrent: () => setCurrentVersion((value) => value + 1),
    catalog: catalogScope === caseId ? catalog : null,
    catalogLoading,
    catalogError,
    reloadCatalog: () => setCatalogVersion((value) => value + 1),
    loadMore,
    detail: detailScope === detailScopeKey ? detail : null,
    detailLoading,
    detailError,
    reloadDetail: () => setDetailVersion((value) => value + 1),
    capture,
    capturing,
    captureError,
  }), [
    capture, captureError, capturing, caseId, catalog, catalogError, catalogLoading, catalogScope,
    current, currentError, currentLoading, currentScope, currentScopeKey, detail, detailError,
    detailLoading, detailScope, detailScopeKey, loadMore,
  ]);
}

function message(value: unknown, fallback: string): string {
  return value instanceof Error && value.message.trim() ? value.message : fallback;
}
