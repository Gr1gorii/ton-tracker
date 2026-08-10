import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { createPortal } from "react-dom";
import {
  ArrowClockwise,
  ArrowDown,
  ArrowRight,
  ArrowUp,
  ArrowsDownUp,
  CalendarBlank,
  CheckCircle,
  Clock,
  Funnel,
  Info,
  SpinnerGap,
  Swap,
  WarningCircle,
  X,
} from "@phosphor-icons/react";

import {
  CASE_ACTIVITY_PROTOCOL_IDS,
  canonicalizeCaseActivityFilters,
  caseActivitySearch,
  DEFAULT_CASE_ACTIVITY_FILTERS,
  parseCaseActivitySearch,
  type CaseActivityUrlState,
} from "../caseActivityQuery";
import { caseActivityPath } from "../caseRouting";
import { useWalletCaseActivity } from "../useWalletCaseActivity";
import type { WalletCase } from "../walletCase";
import type {
  WalletCaseActivityDetailResponse,
  WalletCaseActivityAsset,
  WalletCaseActivityFilters,
  WalletCaseActivityItem,
  WalletCaseActivityKind,
} from "../walletCaseActivity";

function readUrlState(): { state: CaseActivityUrlState; error: string | null } {
  try {
    return { state: parseCaseActivitySearch(window.location.search), error: null };
  } catch (caught) {
    return {
      state: { snapshot: null, filters: DEFAULT_CASE_ACTIVITY_FILTERS, selectedActivityId: null },
      error: caught instanceof Error ? caught.message : "Activity URL is invalid",
    };
  }
}

function short(value: string | null | undefined, start = 8, end = 6): string {
  if (!value) return "Not available";
  if (value.length <= start + end + 1) return value;
  return `${value.slice(0, start)}…${value.slice(-end)}`;
}

function formatDate(value: string | null): string {
  if (!value) return "Time unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function dateTimeInput(value: string | null): string {
  if (!value) return "";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";
  const local = new Date(parsed.getTime() - parsed.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toUtc(value: string): string | null {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) throw new Error("Activity time filter is invalid");
  return parsed.toISOString();
}

function kindLabel(kind: WalletCaseActivityKind): string {
  return kind === "transaction" ? "Transaction" : kind === "transfer" ? "Transfer" : "Swap";
}

function kindIcon(kind: WalletCaseActivityKind): ReactNode {
  if (kind === "swap") return <Swap size={20} />;
  return kind === "transfer" ? <ArrowsDownUp size={20} /> : <CheckCircle size={20} />;
}

function itemAmount(item: WalletCaseActivityItem): string {
  if (item.details.kind === "transaction") {
    return item.details.fee_ton === null ? "Fee unavailable" : `${item.details.fee_ton} TON fee`;
  }
  if (item.details.kind === "transfer") {
    const asset = item.assets.find((entry) => entry.role === "asset");
    return item.details.amount === null
      ? "Amount unavailable"
      : `${item.details.amount} ${assetDisplayLabel(asset)}`;
  }
  const input = item.assets.find((entry) => entry.role === "in");
  const output = item.assets.find((entry) => entry.role === "out");
  return `${item.details.amount_in ?? "?"} ${assetDisplayLabel(input)} → ${item.details.amount_out ?? "?"} ${assetDisplayLabel(output)}`;
}

function assetDisplayLabel(asset: WalletCaseActivityAsset | undefined): string {
  if (!asset) return "asset";
  const reported = asset.symbol ?? (asset.standard === "unknown" ? "asset" : asset.standard);
  return asset.identity_status === "unavailable"
    ? `reported as ${reported} · identity unavailable`
    : reported;
}

function evidenceLabel(item: WalletCaseActivityItem): string {
  return item.provenance.data_origin === "demo_fixture"
    ? "Demo fixture · not evidence"
    : "Normalized provider observation";
}

export default function GramCaseActivity({ walletCase }: { walletCase: WalletCase }) {
  const initial = useMemo(readUrlState, []);
  const [urlState, setUrlState] = useState(initial.state);
  const [queryError, setQueryError] = useState(initial.error);
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [draft, setDraft] = useState<WalletCaseActivityFilters>(initial.state.filters);
  const [draftError, setDraftError] = useState<string | null>(null);
  const lastDetailTrigger = useRef<HTMLElement | null>(null);
  const openedDetailInSession = useRef(false);
  const activityHeadingRef = useRef<HTMLHeadingElement>(null);
  const previousSelectedActivityId = useRef(initial.state.selectedActivityId);

  const replacePinnedSnapshot = useCallback((snapshotId: string) => {
    setUrlState((current) => {
      if (current.snapshot !== null) return current;
      const next = { ...current, snapshot: snapshotId };
      window.history.replaceState({}, "", `${caseActivityPath(walletCase.public_id)}${caseActivitySearch(next)}`);
      return next;
    });
  }, [walletCase.public_id]);

  const controller = useWalletCaseActivity({
    caseId: walletCase.public_id,
    urlState,
    onSnapshotPinned: replacePinnedSnapshot,
    enabled: queryError === null,
  });

  const commitUrlState = useCallback((next: CaseActivityUrlState, replace = false) => {
    const canonicalNext = { ...next, filters: canonicalizeCaseActivityFilters(next.filters) };
    const path = `${caseActivityPath(walletCase.public_id)}${caseActivitySearch(canonicalNext)}`;
    window.history[replace ? "replaceState" : "pushState"]({}, "", path);
    setQueryError(null);
    setUrlState(canonicalNext);
    setDraft(canonicalNext.filters);
  }, [walletCase.public_id]);

  useEffect(() => {
    function restore() {
      const next = readUrlState();
      setQueryError(next.error);
      setUrlState(next.state);
      setDraft(next.state.filters);
      setDraftError(null);
    }
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    if (previousSelectedActivityId.current !== null && urlState.selectedActivityId === null) {
      const trigger = lastDetailTrigger.current;
      if (trigger?.isConnected) trigger.focus();
      else activityHeadingRef.current?.focus();
      lastDetailTrigger.current = null;
      openedDetailInSession.current = false;
    }
    previousSelectedActivityId.current = urlState.selectedActivityId;
  }, [urlState.selectedActivityId]);

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    setDraftError(null);
    try {
      const fromAt = toUtc(draft.from_at ?? "");
      const toAt = toUtc(draft.to_at ?? "");
      if ((fromAt === null) !== (toAt === null) || (fromAt && toAt && Date.parse(fromAt) >= Date.parse(toAt))) {
        throw new Error("Choose both Activity bounds and keep the end after the start.");
      }
      const nextFilters = { ...draft, from_at: fromAt, to_at: toAt };
      const snapshot = controller.response?.snapshot?.public_id ?? urlState.snapshot;
      commitUrlState({ snapshot, filters: nextFilters, selectedActivityId: null });
      setFiltersOpen(false);
    } catch (caught) {
      setDraftError(caught instanceof Error ? caught.message : "Activity filters are invalid");
    }
  }

  function clearFilters() {
    const snapshot = controller.response?.snapshot?.public_id ?? urlState.snapshot;
    commitUrlState({ snapshot, filters: DEFAULT_CASE_ACTIVITY_FILTERS, selectedActivityId: null });
    setFiltersOpen(false);
    setDraftError(null);
  }

  function openDetail(event: MouseEvent<HTMLAnchorElement>, activityId: string) {
    if (
      event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
      event.shiftKey || event.altKey
    ) return;
    event.preventDefault();
    const snapshot = controller.response?.snapshot?.public_id ?? urlState.snapshot;
    if (!snapshot) return;
    lastDetailTrigger.current = event.currentTarget;
    openedDetailInSession.current = true;
    commitUrlState({ ...urlState, snapshot, selectedActivityId: activityId });
  }

  const closeDetail = useCallback(() => {
    if (openedDetailInSession.current) {
      window.history.back();
      return;
    }
    commitUrlState({ ...urlState, selectedActivityId: null }, true);
  }, [commitUrlState, urlState]);

  const applyContextFilter = useCallback((filter: Pick<WalletCaseActivityFilters, "asset_id" | "protocol_id" | "counterparty">) => {
    const snapshot = controller.response?.snapshot?.public_id ?? urlState.snapshot;
    lastDetailTrigger.current = null;
    openedDetailInSession.current = false;
    commitUrlState({
      snapshot,
      filters: { ...urlState.filters, ...filter },
      selectedActivityId: null,
    });
    setFiltersOpen(false);
  }, [commitUrlState, controller.response?.snapshot?.public_id, urlState]);

  if (queryError) {
    return (
      <section className="case-state-panel is-error" role="alert">
        <WarningCircle size={27} weight="fill" />
        <div><h2>Activity URL is invalid</h2><p>{queryError}</p></div>
        <button type="button" className="button-secondary" onClick={() => commitUrlState({ snapshot: null, filters: DEFAULT_CASE_ACTIVITY_FILTERS, selectedActivityId: null }, true)}>
          Reset Activity view <ArrowClockwise size={17} />
        </button>
      </section>
    );
  }

  const response = controller.response;
  const snapshot = response?.snapshot ?? null;
  const selectedSnapshot = snapshot?.public_id ?? urlState.snapshot;

  return (
    <div className="case-activity-page">
      <section className="case-activity-toolbar" aria-labelledby="case-activity-title">
        <div>
          <span className="eyebrow">Snapshot Activity</span>
          <h2 ref={activityHeadingRef} tabIndex={-1} id="case-activity-title">Observed rows, without evidence inflation</h2>
          <p>Server-side filters and pagination stay pinned to one usable snapshot. Demo fixtures are never presented as chain evidence.</p>
        </div>
        <div className="case-activity-toolbar-actions">
          <button type="button" className="button-secondary" onClick={() => setFiltersOpen((value) => !value)} aria-expanded={filtersOpen} aria-controls="case-activity-filters">
            <Funnel size={17} /> Filters
          </button>
          <button type="button" className="button-secondary" onClick={controller.reload} disabled={controller.loading}>
            <ArrowClockwise className={controller.loading ? "spin" : undefined} size={17} /> Refresh
          </button>
        </div>
      </section>

      {filtersOpen && (
        <form id="case-activity-filters" className="case-activity-filters" onSubmit={applyFilters}>
          <fieldset><legend>Row type</legend>{(["transaction", "transfer", "swap"] as const).map((value) => <FilterCheck key={value} label={kindLabel(value)} checked={draft.kinds.includes(value)} onChange={(checked) => setDraft((current) => ({ ...current, kinds: toggle(current.kinds, value, checked) }))} />)}</fieldset>
          <fieldset><legend>Direction</legend>{(["in", "out", "unknown"] as const).map((value) => <FilterCheck key={value} label={value === "in" ? "Incoming" : value === "out" ? "Outgoing" : "Unknown"} checked={draft.directions.includes(value)} onChange={(checked) => setDraft((current) => ({ ...current, directions: toggle(current.directions, value, checked) }))} />)}</fieldset>
          <fieldset><legend>Outcome</legend>{(["success", "failed", "unknown"] as const).map((value) => <FilterCheck key={value} label={value} checked={draft.outcomes.includes(value)} onChange={(checked) => setDraft((current) => ({ ...current, outcomes: toggle(current.outcomes, value, checked) }))} />)}</fieldset>
          <label>Sort<select value={draft.sort} onChange={(event) => setDraft((current) => ({ ...current, sort: event.target.value as "newest" | "oldest" }))}><option value="newest">Newest first</option><option value="oldest">Oldest first</option></select></label>
          <label>From<input type="datetime-local" value={dateTimeInput(draft.from_at)} onChange={(event) => setDraft((current) => ({ ...current, from_at: event.target.value || null }))} /></label>
          <label>To<input type="datetime-local" value={dateTimeInput(draft.to_at)} onChange={(event) => setDraft((current) => ({ ...current, to_at: event.target.value || null }))} /></label>
          <label>Server asset ID<input value={draft.asset_id ?? ""} pattern="asset_[0-9a-f]{64}" placeholder="asset_…" onChange={(event) => setDraft((current) => ({ ...current, asset_id: event.target.value || null }))} /><small>Use the immutable server asset ID, never a ticker symbol.</small></label>
          <label>Protocol<select value={draft.protocol_id ?? ""} onChange={(event) => setDraft((current) => ({ ...current, protocol_id: event.target.value || null }))}><option value="">Any recognized protocol</option>{CASE_ACTIVITY_PROTOCOL_IDS.map((protocolId) => <option key={protocolId} value={protocolId}>{protocolId.replace(/_/g, " ")}</option>)}</select></label>
          <label>Canonical counterparty<input minLength={66} maxLength={76} value={draft.counterparty ?? ""} onChange={(event) => setDraft((current) => ({ ...current, counterparty: event.target.value || null }))} /></label>
          <fieldset><legend>Data origin</legend><FilterCheck label="Demo fixture" checked={draft.data_origins.includes("demo_fixture")} onChange={(checked) => setDraft((current) => ({ ...current, data_origins: toggle(current.data_origins, "demo_fixture", checked) }))} /><FilterCheck label="Provider observed" checked={draft.data_origins.includes("provider_observed")} onChange={(checked) => setDraft((current) => ({ ...current, data_origins: toggle(current.data_origins, "provider_observed", checked) }))} /></fieldset>
          {draftError && <p className="case-filter-error" role="alert">{draftError}</p>}
          <div className="case-filter-actions"><button type="button" className="button-secondary" onClick={clearFilters}>Clear</button><button type="submit" className="button-primary">Apply filters</button></div>
        </form>
      )}

      {snapshot && response && (
        <section className="case-activity-provenance" aria-label="Activity snapshot provenance">
          <div><small>Pinned snapshot</small><strong title={snapshot.public_id}>{short(snapshot.public_id)}</strong></div>
          <div><small>Published</small><strong>{formatDate(snapshot.completed_at)} · {snapshot.state}</strong></div>
          <div><small>Recorded source</small><strong>{snapshot.provider} · {snapshot.data_mode === "mock" ? "demo fixture" : "live provider"}</strong></div>
          <div><small>Requested interval</small><strong>{formatDate(snapshot.requested_period.start_at)} — {formatDate(snapshot.requested_period.end_at)}</strong></div>
          <div><small>Observed extent</small><strong>{response.observed_period ? `${formatDate(response.observed_period.start_at)} — ${formatDate(response.observed_period.end_at)}` : "No timestamped rows"}</strong></div>
          <div><small>Coverage</small><strong>{snapshot.coverage.state.replace(/_/g, " ")}</strong></div>
          <div><small>Rows after deduplication</small><strong>{response.aggregate.total_items}</strong></div>
        </section>
      )}

      {snapshot && response && (
        <div className="case-activity-boundary" role="note"><Info size={18} /><p>This Activity aggregate uses its own cross-sync observation deduplication basis ({response.aggregate.source_sync_count} source sync{response.aggregate.source_sync_count === 1 ? "" : "s"}). Summary remains based on the latest usable sync only. Neither view proves complete wallet history.</p></div>
      )}

      {controller.error && <div className="case-inline-error" role="alert"><WarningCircle size={18} weight="fill" /><span>{controller.error}</span><button type="button" onClick={controller.reload}>Try again</button></div>}

      {controller.loading ? (
        <section className="case-state-panel" aria-live="polite"><SpinnerGap className="spin" size={25} /><div><h2>Loading Activity</h2><p>Reading the pinned, server-filtered snapshot…</p></div></section>
      ) : !response ? null : response.snapshot === null ? (
        <section className="case-activity-empty"><Clock size={28} /><h2>No usable snapshot yet</h2><p>Run a bounded synchronization from Summary. Activity will remain empty until a partial or successful snapshot is published.</p></section>
      ) : (
        <>
          <section className="case-activity-aggregate" aria-label="Activity aggregate">
            <ActivityMetric label="Transactions" value={response.aggregate.transactions} />
            <ActivityMetric label="Transfers" value={response.aggregate.transfers} />
            <ActivityMetric label="Swaps" value={response.aggregate.swaps} />
            <ActivityMetric label="Failed transactions" value={response.aggregate.failed_transactions} warning={response.aggregate.failed_transactions > 0} />
            <ActivityMetric label="Duplicates suppressed" value={response.aggregate.suppressed_duplicate_observations} />
            <ActivityMetric label="Identity conflicts omitted" value={response.aggregate.conflicted_identity_count} warning={response.aggregate.conflicted_identity_count > 0} />
          </section>

          {controller.items.length === 0 ? (
            <section className="case-activity-empty"><Funnel size={28} /><h2>No rows match these filters</h2><p>The pinned snapshot remains available. Clear or change filters to inspect other observations.</p><button type="button" className="button-secondary" onClick={clearFilters}>Clear filters</button></section>
          ) : (
            <section className="case-activity-results" aria-labelledby="activity-results-title">
              <header><div><span className="eyebrow">Filtered result</span><h2 id="activity-results-title">{response.aggregate.total_items} Activity rows</h2></div><span>{controller.items.length} loaded</span></header>
              <ul>{controller.items.map((item) => {
                const detailState = { ...urlState, snapshot: selectedSnapshot, selectedActivityId: item.public_id };
                return <li key={item.public_id}><a href={`${caseActivityPath(walletCase.public_id)}${caseActivitySearch(detailState)}`} onClick={(event) => openDetail(event, item.public_id)} aria-label={`Open ${kindLabel(item.kind)} Activity detail`}><span className={`case-activity-kind is-${item.kind}`}>{kindIcon(item.kind)}</span><span className="case-activity-row-main"><strong>{itemAmount(item)}</strong><small>{item.counterparty ? short(item.counterparty.display_address) : "No counterparty"}</small></span><span><strong>{kindLabel(item.kind)}</strong><small>{item.outcome ?? "Outcome unavailable"}</small></span><span><strong>{formatDate(item.occurred_at)}</strong><small>{item.logical_time ? `LT ${item.logical_time}` : "Logical time unavailable"}</small></span><span className={`case-evidence-chip is-${item.provenance.data_origin}`}>{evidenceLabel(item)}</span><ArrowRight size={17} /></a></li>;
              })}</ul>
              {response.page.has_more && <button type="button" className="button-secondary case-load-more" onClick={() => void controller.loadMore()} disabled={controller.loadingMore}>{controller.loadingMore ? <SpinnerGap className="spin" size={17} /> : <ArrowDown size={17} />} Load more</button>}
            </section>
          )}

          {(response.gaps.length > 0 || response.limitations.length > 0) && (
            <section className="case-activity-caveats"><header><WarningCircle size={20} /><div><span className="eyebrow">Coverage boundaries</span><h2>Gaps and limitations</h2></div></header><ul>{response.gaps.map((gap) => <li key={`gap-${gap.code}-${gap.surface ?? "all"}`}><strong>{gap.code.replace(/_/g, " ")}</strong><span>{gap.message}</span></li>)}{response.limitations.map((item) => <li key={`limit-${item.code}`}><strong>{item.code.replace(/_/g, " ")}</strong><span>{item.message}</span></li>)}</ul></section>
          )}
        </>
      )}

      {urlState.selectedActivityId && urlState.snapshot && (
        <ActivityDetailDialog controller={controller} onClose={closeDetail} onApplyFilter={applyContextFilter} />
      )}
    </div>
  );
}

function toggle<T>(values: T[], value: T, checked: boolean): T[] {
  return checked ? [...values, value] : values.filter((item) => item !== value);
}

function FilterCheck({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="case-filter-check"><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><span>{label}</span></label>;
}

function ActivityMetric({ label, value, warning = false }: { label: string; value: number; warning?: boolean }) {
  return <article className={warning ? "is-warning" : undefined}><small>{label}</small><strong>{value}</strong></article>;
}

function ActivityDetailDialog({
  controller,
  onClose,
  onApplyFilter,
}: {
  controller: ReturnType<typeof useWalletCaseActivity>;
  onClose: () => void;
  onApplyFilter: (filter: Pick<WalletCaseActivityFilters, "asset_id" | "protocol_id" | "counterparty">) => void;
}) {
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  useEffect(() => {
    closeRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const backdrop = dialogRef.current?.parentElement;
    const background = [...document.body.children].filter((element) => element !== backdrop);
    const previousBackgroundState = background.map((element) => ({
      element,
      inert: element.getAttribute("inert"),
      ariaHidden: element.getAttribute("aria-hidden"),
    }));
    background.forEach((element) => {
      element.setAttribute("inert", "");
      element.setAttribute("aria-hidden", "true");
    });
    function containFocus(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [])].filter((element) => element.getAttribute("aria-hidden") !== "true");
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && (document.activeElement === first || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (document.activeElement === last || !dialogRef.current?.contains(document.activeElement))) {
        event.preventDefault();
        first.focus();
      }
    }
    window.addEventListener("keydown", containFocus);
    return () => {
      document.body.style.overflow = previousOverflow;
      previousBackgroundState.forEach(({ element, inert, ariaHidden }) => {
        if (inert === null) element.removeAttribute("inert");
        else element.setAttribute("inert", inert);
        if (ariaHidden === null) element.removeAttribute("aria-hidden");
        else element.setAttribute("aria-hidden", ariaHidden);
      });
      window.removeEventListener("keydown", containFocus);
    };
  }, [onClose]);
  return createPortal(
    <div className="case-detail-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section ref={dialogRef} className="case-activity-dialog" role="dialog" aria-modal="true" aria-labelledby="activity-detail-title">
        <header><div><span className="eyebrow">Sanitized provenance</span><h2 id="activity-detail-title">Activity detail</h2></div><button ref={closeRef} type="button" aria-label="Close Activity detail" onClick={onClose}><X size={20} /></button></header>
        {controller.detailLoading ? <div className="case-detail-loading" role="status"><SpinnerGap className="spin" size={22} /> Loading detail…</div> : controller.detailError ? <div className="case-inline-error" role="alert"><WarningCircle size={18} /><span>{controller.detailError}</span><button type="button" onClick={controller.retryDetail}>Try again</button></div> : controller.detail ? <ActivityDetailContent detail={controller.detail} onApplyFilter={onApplyFilter} /> : null}
      </section>
    </div>,
    document.body,
  );
}

function ActivityDetailContent({
  detail,
  onApplyFilter,
}: {
  detail: WalletCaseActivityDetailResponse;
  onApplyFilter: (filter: Pick<WalletCaseActivityFilters, "asset_id" | "protocol_id" | "counterparty">) => void;
}) {
  const item = detail.item;
  const filterableAssets = item.assets.filter((asset) => asset.asset_id !== null);
  const protocolId = item.protocol?.status === "recognized" ? item.protocol.id : null;
  const counterparty = item.counterparty?.canonical_address ?? null;
  return (
    <div className="case-detail-content">
      <div className="case-detail-lead">
        <span className={`case-activity-kind is-${item.kind}`}>{kindIcon(item.kind)}</span>
        <div><strong>{itemAmount(item)}</strong><span>{formatDate(item.occurred_at)}</span></div>
        <span className={`case-evidence-chip is-${item.provenance.data_origin}`}>{evidenceLabel(item)}</span>
      </div>
      {(filterableAssets.length > 0 || protocolId || counterparty) && (
        <section className="case-detail-filter-actions" aria-label="Filter Activity from this row">
          <h3>Explore matching rows</h3>
          <div>
            {filterableAssets.map((asset) => <button type="button" key={`${asset.role}-${asset.asset_id}`} onClick={() => onApplyFilter({ asset_id: asset.asset_id, protocol_id: null, counterparty: null })}>Asset: {asset.symbol ?? asset.standard}</button>)}
            {protocolId && <button type="button" onClick={() => onApplyFilter({ asset_id: null, protocol_id: protocolId, counterparty: null })}>Protocol: {item.protocol?.label ?? protocolId}</button>}
            {counterparty && <button type="button" onClick={() => onApplyFilter({ asset_id: null, protocol_id: null, counterparty })}>Counterparty: {short(item.counterparty?.display_address)}</button>}
          </div>
        </section>
      )}
      {item.assets.length > 0 && <ActivityAssetIdentity assets={item.assets} />}
      <dl className="case-definition-list">
        <div><dt>Activity ID</dt><dd><code>{item.public_id}</code></dd></div>
        <div><dt>Snapshot</dt><dd><code>{detail.snapshot_public_id}</code></dd></div>
        <div><dt>Direction</dt><dd>{item.direction ?? "Not available"}</dd></div>
        <div><dt>Outcome</dt><dd>{item.outcome ?? "Not available"}</dd></div>
        <div><dt>Counterparty</dt><dd>{item.counterparty?.display_address ?? "Not available"}</dd></div>
        <div><dt>Transaction hash</dt><dd>{item.transaction.hash ? <code>{item.transaction.hash}</code> : "Not available"}</dd></div>
        <div><dt>Provider</dt><dd>{item.provenance.provider}</dd></div>
        <div><dt>Identity assurance</dt><dd>{item.provenance.identity_assurance.replace(/_/g, " ")}</dd></div>
        <div><dt>Deduplication basis</dt><dd>{item.provenance.deduplication_basis.replace(/_/g, " ")}</dd></div>
        <div><dt>Observations</dt><dd>{item.provenance.observation_count} ({item.provenance.suppressed_count} suppressed)</dd></div>
      </dl>
      <section className="case-source-observations">
        <h3>Source observations</h3>
        {detail.source_observations.length ? <ul>{detail.source_observations.map((source, index) => <li key={`${source.sync_public_id}-${index}`}><span>{source.data_origin === "demo_fixture" ? "Demo fixture" : "Provider observed"}</span><strong>{source.provider}</strong><small>{formatDate(source.observed_at)} · {source.source_status}</small></li>)}</ul> : <p>No expanded source observations were returned.</p>}
        {detail.sources_truncated && <p className="case-source-truncated">Only the first 50 sanitized observations are shown.</p>}
      </section>
      {item.limitations.length > 0 && <section className="case-item-limitations"><h3>Item limitations</h3><ul>{item.limitations.map((limitation) => <li key={limitation.code}>{limitation.message}</li>)}</ul></section>}
    </div>
  );
}

function ActivityAssetIdentity({ assets }: { assets: WalletCaseActivityAsset[] }) {
  return (
    <section className="case-detail-assets" aria-label="Asset identity">
      <h3>Asset identity</h3>
      {assets.map((asset, index) => (
        <div className="case-detail-asset" key={`${asset.role}-${asset.asset_id ?? index}`}>
          <strong>{asset.symbol ? `Reported as ${asset.symbol}` : `Asset ${index + 1}`}</strong>
          <dl className="case-definition-list">
            <div><dt>Role</dt><dd>{asset.role}</dd></div>
            <div><dt>Identity status</dt><dd>{asset.identity_status.replace(/_/g, " ")}</dd></div>
            <div><dt>Standard</dt><dd>{asset.standard}</dd></div>
            <div><dt>Server asset ID</dt><dd>{asset.asset_id ? <code>{asset.asset_id}</code> : "Not available"}</dd></div>
            <div><dt>Canonical contract</dt><dd>{asset.contract_address ? <code>{asset.contract_address}</code> : "Not available"}</dd></div>
          </dl>
        </div>
      ))}
    </section>
  );
}
