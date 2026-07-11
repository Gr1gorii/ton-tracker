import { useEffect, useMemo, useState, type ReactNode } from "react";
import {
  ArrowDownLeft,
  ArrowUpRight,
  ArrowsLeftRight,
  CaretRight,
  Check,
  Clock,
  Coins,
  Eye,
  ListBullets,
  Play,
  SpinnerGap,
  Swap,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  getWalletIngestionRun,
  previewWalletIngestion,
  runWalletIngestion,
} from "../api";
import type {
  TimeWindow,
  WalletIngestionPreviewResponse,
  WalletIngestionRequest,
  WalletIngestionRunResponse,
  WalletIngestionSurface,
} from "../types";
import { useWalletRunCatalog } from "../useWalletRunCatalog";

const surfaceOptions: Array<{
  id: WalletIngestionSurface;
  label: string;
  help: string;
  icon: typeof ArrowsLeftRight;
}> = [
  { id: "transfers", label: "Transfers", help: "Incoming and outgoing assets", icon: ArrowsLeftRight },
  { id: "transactions", label: "Transactions", help: "Ordered account history", icon: ListBullets },
  { id: "swaps", label: "DEX swaps", help: "Recognized protocol activity", icon: Swap },
  { id: "balances", label: "GRAM balance", help: "Native currency snapshot", icon: Coins },
  { id: "jettons", label: "Jettons", help: "Token balance snapshots", icon: Coins },
];

type ResultTab = "summary" | "transfers" | "transactions" | "swaps" | "warnings";

function countRows(run: WalletIngestionRunResponse) {
  return run.transfers.length + run.transactions.length + run.swaps.length + run.balances.length;
}

function formatDate(value?: string | null) {
  if (!value) return "Unknown time";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function shortHash(value?: string | null) {
  if (!value) return "—";
  return value.length > 18 ? `${value.slice(0, 9)}…${value.slice(-7)}` : value;
}

function displayAsset(value?: string | null) {
  if (!value) return "";
  return value === "TON" ? "GRAM" : value;
}

function displayMessage(value: string) {
  return value
    .split("native TON").join("native GRAM")
    .split("TON/jetton").join("GRAM/jetton");
}

export default function GramActivityWorkspace({
  accountAddress,
  onAccountAddressChange,
  activeRun,
  onRunResultChange,
}: {
  accountAddress: string;
  onAccountAddressChange: (value: string) => void;
  activeRun: WalletIngestionRunResponse | null;
  onRunResultChange: (result: WalletIngestionRunResponse | null) => void;
}) {
  const [timeWindow, setTimeWindow] = useState<TimeWindow>("24h");
  const [customStart, setCustomStart] = useState("");
  const [customEnd, setCustomEnd] = useState("");
  const [surfaces, setSurfaces] = useState<WalletIngestionSurface[]>(surfaceOptions.map((item) => item.id));
  const [preview, setPreview] = useState<WalletIngestionPreviewResponse | null>(null);
  const [loading, setLoading] = useState<"preview" | "run" | "load" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<ResultTab>("summary");
  const catalog = useWalletRunCatalog();

  const payload = useMemo((): WalletIngestionRequest | null => {
    const wallet = accountAddress.trim();
    if (!wallet || surfaces.length === 0) return null;
    if (timeWindow === "custom") {
      if (!customStart || !customEnd) return null;
      const start = new Date(customStart);
      const end = new Date(customEnd);
      if (Number.isNaN(start.valueOf()) || Number.isNaN(end.valueOf()) || start >= end) return null;
      return { wallet_address: wallet, time_window: timeWindow, custom_start: start.toISOString(), custom_end: end.toISOString(), surfaces };
    }
    return { wallet_address: wallet, time_window: timeWindow, surfaces };
  }, [accountAddress, customEnd, customStart, surfaces, timeWindow]);

  useEffect(() => {
    setError(null);
  }, [accountAddress, customEnd, customStart, surfaces, timeWindow]);

  function toggleSurface(id: WalletIngestionSurface) {
    setSurfaces((current) => current.includes(id) ? (current.length === 1 ? current : current.filter((item) => item !== id)) : [...current, id]);
    setPreview(null);
  }

  function validate() {
    if (!accountAddress.trim()) return "Enter a TON wallet address first.";
    if (timeWindow === "custom" && (!customStart || !customEnd)) return "Choose both dates for a custom window.";
    if (!payload) return "Check the wallet address and time range.";
    return null;
  }

  async function handlePreview() {
    const validation = validate();
    if (validation || !payload) return setError(validation);
    setLoading("preview");
    setError(null);
    try {
      const result = await previewWalletIngestion(payload);
      setPreview(result);
      onRunResultChange(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not preview wallet coverage.");
    } finally {
      setLoading(null);
    }
  }

  async function handleRun() {
    const validation = validate();
    if (validation || !payload) return setError(validation);
    setLoading("run");
    setError(null);
    try {
      const result = await runWalletIngestion(payload);
      setPreview(null);
      onRunResultChange(result);
      setTab("summary");
      await catalog.refresh();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create the evidence run.");
    } finally {
      setLoading(null);
    }
  }

  async function loadRun(id: string) {
    const runId = Number(id);
    if (!Number.isSafeInteger(runId) || runId <= 0) return;
    setLoading("load");
    setError(null);
    try {
      const result = await getWalletIngestionRun(runId);
      onAccountAddressChange(result.wallet_address);
      onRunResultChange(result);
      setPreview(null);
      setTab("summary");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : `Could not open run #${id}.`);
    } finally {
      setLoading(null);
    }
  }

  return (
    <div className="activity-workspace">
      <section className="activity-builder">
        <div className="activity-builder-main">
          <header className="activity-card-head">
            <span className="step-number">1</span>
            <div><h2>Choose what to inspect</h2><p>Keep the scope small or include every surface for a complete wallet view.</p></div>
          </header>

          <label className="clean-field">
            <span>Wallet address</span>
            <input value={accountAddress} onChange={(event) => onAccountAddressChange(event.target.value)} placeholder="EQ… or UQ…" />
          </label>

          <div className="scope-row">
            <div>
              <span className="clean-label">Time window</span>
              <div className="window-picker" role="group" aria-label="Time window">
                {(["24h", "3d", "7d", "custom"] as TimeWindow[]).map((value) => (
                  <button key={value} type="button" className={timeWindow === value ? "is-active" : ""} onClick={() => setTimeWindow(value)}>{value === "custom" ? "Custom" : value}</button>
                ))}
              </div>
            </div>
            {timeWindow === "custom" && (
              <div className="custom-range">
                <label><span>From</span><input type="datetime-local" value={customStart} onChange={(event) => setCustomStart(event.target.value)} /></label>
                <label><span>To</span><input type="datetime-local" value={customEnd} onChange={(event) => setCustomEnd(event.target.value)} /></label>
              </div>
            )}
          </div>

          <div>
            <span className="clean-label">Data surfaces</span>
            <div className="surface-picker">
              {surfaceOptions.map((surface) => {
                const Icon = surface.icon;
                const selected = surfaces.includes(surface.id);
                return (
                  <button key={surface.id} type="button" className={selected ? "surface-option is-selected" : "surface-option"} onClick={() => toggleSurface(surface.id)} aria-pressed={selected}>
                    <span><Icon size={20} /></span><div><strong>{surface.label}</strong><small>{surface.help}</small></div>{selected && <Check size={17} weight="bold" />}
                  </button>
                );
              })}
            </div>
          </div>

          {error && <div className="activity-error" role="alert"><WarningCircle size={18} weight="fill" />{error}</div>}

          <div className="activity-actions">
            <button type="button" className="button-secondary" onClick={handlePreview} disabled={Boolean(loading)}>
              {loading === "preview" ? <SpinnerGap className="spin" size={18} /> : <Eye size={18} />} Preview coverage
            </button>
            <button type="button" className="button-primary" onClick={handleRun} disabled={Boolean(loading)}>
              {loading === "run" ? <SpinnerGap className="spin" size={18} /> : <Play size={18} weight="fill" />} Create evidence run
            </button>
          </div>
        </div>

        <aside className="recent-runs">
          <header><div><span className="eyebrow">Recent work</span><h2>Saved runs</h2></div><Clock size={20} /></header>
          {catalog.loading && !catalog.runs.length ? <p className="runs-empty">Loading saved runs…</p> : catalog.runs.length ? (
            <div className="run-list">
              {catalog.runs.map((run) => (
                <button key={run.run_id} type="button" onClick={() => loadRun(run.run_id)} disabled={Boolean(loading)}>
                  <span className={`run-mode mode-${run.data_mode}`} />
                  <div><strong>Run #{run.run_id}</strong><small>{run.wallet_hint} · {run.time_window}</small></div>
                  <CaretRight size={16} />
                </button>
              ))}
            </div>
          ) : <p className="runs-empty">No saved runs yet. Your first persisted run will appear here.</p>}
        </aside>
      </section>

      {preview && <CoveragePreview preview={preview} onCreateRun={handleRun} loading={loading === "run"} />}
      {activeRun && <RunResult run={activeRun} tab={tab} onTabChange={setTab} />}
      {!preview && !activeRun && (
        <section className="activity-onboarding">
          <span className="step-number">2</span>
          <div><h2>Preview, then persist</h2><p>Preview shows source coverage without saving a run. Create an evidence run when the requested scope looks right.</p></div>
          <div className="onboarding-flow"><span>Wallet scope</span><CaretRight size={16} /><span>Provider coverage</span><CaretRight size={16} /><span>Canonical run</span></div>
        </section>
      )}
    </div>
  );
}

function CoveragePreview({ preview, onCreateRun, loading }: { preview: WalletIngestionPreviewResponse; onCreateRun: () => void; loading: boolean }) {
  return (
    <section className="coverage-card">
      <header className="result-heading"><div><span className="result-status is-ready"><Check size={15} weight="bold" />Coverage ready</span><h2>Providers can return this scope</h2><p>{displayMessage(preview.message)}</p></div><button className="button-primary" type="button" onClick={onCreateRun} disabled={loading}>{loading ? <SpinnerGap className="spin" size={18} /> : <Play size={18} weight="fill" />}Persist this run</button></header>
      <div className="coverage-grid">
        {preview.provider_coverage.map((item) => (
          <article key={item.provider}><span className={`coverage-dot status-${item.source_status}`} /><div><strong>{item.provider}</strong><small>{item.normalized_count} normalized rows</small></div><b>{item.source_status}</b></article>
        ))}
      </div>
      {preview.warnings.length > 0 && <div className="coverage-warning"><WarningCircle size={18} />{preview.warnings.join(" ")}</div>}
    </section>
  );
}

function RunResult({ run, tab, onTabChange }: { run: WalletIngestionRunResponse; tab: ResultTab; onTabChange: (tab: ResultTab) => void }) {
  const tabs: Array<[ResultTab, string, number | null]> = [
    ["summary", "Summary", null],
    ["transfers", "Transfers", run.transfers.length],
    ["transactions", "Transactions", run.transactions.length],
    ["swaps", "Swaps", run.swaps.length],
    ["warnings", "Warnings", run.warnings.length],
  ];
  return (
    <section className="run-result-card">
      <header className="result-heading">
        <div><span className="result-status is-ready"><Check size={15} weight="bold" />Run #{run.run_id} ready</span><h2>{countRows(run)} source-labelled records</h2><p>{displayMessage(run.message)}</p></div>
        <div className="run-facts"><span><small>Network</small>{run.wallet_identity.network}</span><span><small>Mode</small>{run.data_mode}</span><span><small>Status</small>{run.status}</span></div>
      </header>
      <div className="result-tabs" role="tablist" aria-label="Run result views">
        {tabs.map(([id, label, count]) => <button key={id} type="button" role="tab" aria-selected={tab === id} className={tab === id ? "is-active" : ""} onClick={() => onTabChange(id)}>{label}{count !== null && <span>{count}</span>}</button>)}
      </div>
      <div className="result-body">
        {tab === "summary" && <RunSummary run={run} />}
        {tab === "transfers" && <TransferRows run={run} />}
        {tab === "transactions" && <TransactionRows run={run} />}
        {tab === "swaps" && <SwapRows run={run} />}
        {tab === "warnings" && <WarningRows run={run} />}
      </div>
    </section>
  );
}

function RunSummary({ run }: { run: WalletIngestionRunResponse }) {
  const summary = run.activity_summary;
  const metrics = [
    ["Transfers", summary?.counts.transfers ?? run.transfers.length],
    ["Transactions", summary?.counts.transactions ?? run.transactions.length],
    ["DEX swaps", summary?.counts.swaps ?? run.swaps.length],
    ["Balance snapshots", summary?.counts.balances ?? run.balances.length],
  ];
  return (
    <div className="run-summary">
      <div className="run-summary-metrics">{metrics.map(([label, value]) => <article key={label}><span>{label}</span><strong>{value}</strong></article>)}</div>
      <div className="run-summary-notes"><article><span>Canonical wallet</span><strong>{run.wallet_identity.canonical_address ?? run.wallet_address}</strong></article><article><span>Captured</span><strong>{formatDate(run.created_at)}</strong></article><article><span>Requested surfaces</span><strong>{run.requested_surfaces.join(", ")}</strong></article></div>
    </div>
  );
}

function ResultTable({ columns, children, empty }: { columns: string[]; children: ReactNode; empty: boolean }) {
  if (empty) return <div className="result-empty">No records were returned for this surface.</div>;
  return <div className="clean-table-wrap"><table className="clean-table"><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{children}</tbody></table></div>;
}

function TransferRows({ run }: { run: WalletIngestionRunResponse }) {
  return <ResultTable columns={["Direction", "Asset", "Amount", "Counterparty", "Time"]} empty={!run.transfers.length}>{run.transfers.slice(0, 100).map((item, index) => <tr key={`${item.tx_hash}-${index}`}><td><span className={`direction-badge is-${item.direction}`}>{item.direction === "in" ? <ArrowDownLeft size={15} /> : <ArrowUpRight size={15} />}{item.direction}</span></td><td><strong>{item.asset === "TON" ? "GRAM" : item.asset}</strong></td><td>{item.amount ?? "—"}</td><td>{shortHash(item.counterparty)}</td><td>{formatDate(item.timestamp)}</td></tr>)}</ResultTable>;
}

function TransactionRows({ run }: { run: WalletIngestionRunResponse }) {
  return <ResultTable columns={["Transaction", "Status", "Fee (GRAM)", "Provider", "Time"]} empty={!run.transactions.length}>{run.transactions.slice(0, 100).map((item) => <tr key={`${item.tx_hash}-${item.logical_time}`}><td><strong>{shortHash(item.tx_hash)}</strong></td><td><span className={`record-status is-${item.success}`}>{item.success}</span></td><td>{item.fee_ton ?? "—"}</td><td>{item.provider}</td><td>{formatDate(item.timestamp)}</td></tr>)}</ResultTable>;
}

function SwapRows({ run }: { run: WalletIngestionRunResponse }) {
  return <ResultTable columns={["Protocol", "Sent", "Received", "Estimate", "Time"]} empty={!run.swaps.length}>{run.swaps.slice(0, 100).map((item, index) => <tr key={`${item.tx_hash}-${index}`}><td><strong>{item.dex_protocol.provider_label ?? item.dex ?? "Unknown"}</strong></td><td>{item.amount_in ?? "—"} {displayAsset(item.token_in)}</td><td>{item.amount_out ?? "—"} {displayAsset(item.token_out)}</td><td>{item.estimated_usd ? `$${item.estimated_usd}` : "—"}</td><td>{formatDate(item.timestamp)}</td></tr>)}</ResultTable>;
}

function WarningRows({ run }: { run: WalletIngestionRunResponse }) {
  if (!run.warnings.length) return <div className="result-empty is-positive"><Check size={20} />No run warnings were reported.</div>;
  return <div className="warning-list">{run.warnings.map((warning, index) => <article key={`${warning.evidence_key}-${index}`}><WarningCircle size={19} weight="fill" /><div><strong>{warning.severity}</strong><p>{warning.message}</p></div>{warning.provider && <span>{warning.provider}</span>}</article>)}</div>;
}
