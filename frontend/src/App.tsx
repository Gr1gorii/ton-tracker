import { lazy, Suspense, useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  ArrowRight,
  ArrowsClockwise,
  Atom,
  ChartDonut,
  ChartLineUp,
  CheckCircle,
  Coins,
  Database,
  DownloadSimple,
  FileText,
  Fingerprint,
  Gauge,
  HardDrives,
  MagnifyingGlass,
  Moon,
  Planet,
  ShieldCheck,
  SpinnerGap,
  Sparkle,
  Swap,
  Sun,
  Wallet,
  WarningCircle,
} from "@phosphor-icons/react";
import {
  getProvidersStatus,
  walletCanonicalReportCsvExportUrl,
  walletCanonicalReportExportUrl,
  walletRunExportCsvUrl,
  walletRunExportUrl,
} from "./api";
import type { ProviderStatusInfo, ProvidersStatus, WalletIngestionRunResponse } from "./types";
import GramActivityWorkspace from "./components/GramActivityWorkspace";
import atmosphere from "./assets/gram-scope-atmosphere.jpg";

const RELEASE_LABEL = "v0.32.0";
const CHART_COLORS = ["#4f6df5", "#ff7769", "#55c8be", "#9b7de4", "#f2a65a"];
const GramRunCharts = lazy(() => import("./components/GramRunCharts"));

type Theme = "light" | "dark";
type SectionId = "overview" | "activity" | "proofs" | "assets" | "reports" | "sources";

const sections: Array<{
  id: SectionId;
  label: string;
  description: string;
  icon: typeof Gauge;
}> = [
  { id: "overview", label: "Overview", description: "Wallet at a glance", icon: Gauge },
  { id: "activity", label: "Activity", description: "Transfers, swaps and runs", icon: ChartLineUp },
  { id: "proofs", label: "Proofs", description: "Cryptographic evidence", icon: ShieldCheck },
  { id: "assets", label: "Assets & DEX", description: "Jettons and protocols", icon: ChartDonut },
  { id: "reports", label: "Reports", description: "Canonical exports", icon: FileText },
  { id: "sources", label: "Data sources", description: "Providers and tools", icon: HardDrives },
];

function initialTheme(): Theme {
  const saved = window.localStorage.getItem("gram-scope-theme");
  if (saved === "light" || saved === "dark") return saved;
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function shortAddress(value: string): string {
  if (!value) return "No wallet selected";
  if (value.length <= 18) return value;
  return `${value.slice(0, 9)}…${value.slice(-7)}`;
}

function formatTokenAmount(value?: string | null): string {
  if (!value) return "—";
  const number = Number(value);
  if (!Number.isFinite(number)) return value;
  return number.toLocaleString(undefined, { maximumFractionDigits: 6 });
}

function providerItems(providers: ProvidersStatus | null) {
  if (!providers) return [];
  const items: Array<[string, ProviderStatusInfo | undefined]> = [
    ["GeckoTerminal", providers.geckoterminal],
    ["STON.fi", providers.stonfi],
    ["TonAPI", providers.tonapi],
    ["Wallet activity", providers.wallet_activity],
    ["Bitquery", providers.bitquery],
    ["TON provider", providers.ton_provider],
  ];
  return items.filter((item): item is [string, ProviderStatusInfo] => Boolean(item[1]));
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(initialTheme);
  const [entered, setEntered] = useState(false);
  const [activeSection, setActiveSection] = useState<SectionId>("overview");
  const [workspaceAccount, setWorkspaceAccount] = useState("");
  const [activeRun, setActiveRun] = useState<WalletIngestionRunResponse | null>(null);
  const [providers, setProviders] = useState<ProvidersStatus | null>(null);
  const [providersError, setProvidersError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("gram-scope-theme", theme);
  }, [theme]);

  useEffect(() => {
    getProvidersStatus()
      .then(setProviders)
      .catch((error) => {
        setProvidersError(error instanceof Error ? error.message : "Provider status unavailable");
      });
  }, []);

  const handleRunChange = useCallback((result: WalletIngestionRunResponse | null) => {
    setActiveRun(result);
  }, []);

  function enterWorkspace(address: string) {
    setWorkspaceAccount(address.trim());
    setEntered(true);
    setActiveSection("overview");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function navigate(section: SectionId) {
    setActiveSection(section);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function openActivity() {
    navigate("activity");
  }

  if (!entered) {
    return (
      <Landing
        theme={theme}
        onThemeChange={setTheme}
        onEnter={enterWorkspace}
        atmosphere={atmosphere}
      />
    );
  }

  const providersList = providerItems(providers);
  const availableProviders = providersList.filter(([, item]) => item.available).length;
  const dataMode = providers?.data_mode ?? "unknown";

  return (
    <div className="gram-app-shell">
      <aside className="gram-sidebar">
        <Brand compact />
        <nav className="gram-nav" aria-label="Primary workspace navigation">
          {sections.map((section) => {
            const Icon = section.icon;
            return (
              <button
                key={section.id}
                type="button"
                className={activeSection === section.id ? "gram-nav-item is-active" : "gram-nav-item"}
                aria-current={activeSection === section.id ? "page" : undefined}
                onClick={() => navigate(section.id)}
              >
                <Icon size={20} weight={activeSection === section.id ? "fill" : "regular"} />
                <span>
                  <strong>{section.label}</strong>
                  <small>{section.description}</small>
                </span>
              </button>
            );
          })}
        </nav>

        <div className="gram-sidebar-foot">
          <div className={`mode-indicator mode-${dataMode}`}>
            <span aria-hidden="true" />
            {dataMode === "real" ? "Live provider mode" : dataMode === "mock" ? "Safe preview mode" : "Checking data mode"}
          </div>
          <small>{RELEASE_LABEL} · TON blockchain</small>
        </div>
      </aside>

      <div className="gram-main-frame">
        <header className="gram-topbar">
          <div className="mobile-brand"><Brand compact /></div>
          <WalletSearch value={workspaceAccount} onChange={setWorkspaceAccount} onSubmit={openActivity} />
          <div className="topbar-actions">
            <span className="provider-pill">
              <span className={availableProviders > 0 ? "status-dot is-live" : "status-dot"} />
              {providers ? `${availableProviders}/${providersList.length} sources` : "Checking sources"}
            </span>
            <ThemeToggle theme={theme} onChange={setTheme} />
          </div>
        </header>

        <nav className="gram-mobile-nav" aria-label="Mobile workspace navigation">
          {sections.map((section) => {
            const Icon = section.icon;
            return (
              <button
                key={section.id}
                type="button"
                className={activeSection === section.id ? "is-active" : ""}
                onClick={() => navigate(section.id)}
              >
                <Icon size={18} weight={activeSection === section.id ? "fill" : "regular"} />
                {section.label}
              </button>
            );
          })}
        </nav>

        <main className="gram-page">
          {dataMode !== "real" && (
            <div className="context-banner" role="status">
              <WarningCircle size={19} weight="fill" />
              <span>
                {dataMode === "mock"
                  ? "Production data is disabled. The interface remains fail-closed until real providers are enabled."
                  : "Provider status is still loading. Evidence-dependent actions stay unavailable until verified."}
              </span>
            </div>
          )}

          <section hidden={activeSection !== "overview"}>
            <Overview
              account={workspaceAccount}
              activeRun={activeRun}
              dataMode={dataMode}
              availableProviders={availableProviders}
              providerTotal={providersList.length}
              onOpenActivity={openActivity}
              onRun={openActivity}
            />
          </section>

          <section hidden={activeSection !== "activity"}>
            <PageHeading
              eyebrow="Wallet activity"
              title="Build the evidence trail"
              description="Choose the time window and surfaces, preview coverage, then persist one source-labelled run."
            />
            <GramActivityWorkspace
              accountAddress={workspaceAccount}
              onAccountAddressChange={setWorkspaceAccount}
              activeRun={activeRun}
              onRunResultChange={handleRunChange}
            />
          </section>

          <section hidden={activeSection !== "proofs"}>
            <ProofsView activeRun={activeRun} onOpenActivity={openActivity} />
          </section>

          <section hidden={activeSection !== "assets"}>
            <AssetsView activeRun={activeRun} onOpenActivity={openActivity} />
          </section>

          <section hidden={activeSection !== "reports"}>
            <ReportsView activeRun={activeRun} onOpenActivity={openActivity} />
          </section>

          <section hidden={activeSection !== "sources"}>
            <SourcesView providers={providers} error={providersError} />
          </section>
        </main>
      </div>
    </div>
  );
}

function Landing({
  theme,
  onThemeChange,
  onEnter,
  atmosphere: background,
}: {
  theme: Theme;
  onThemeChange: (theme: Theme) => void;
  onEnter: (address: string) => void;
  atmosphere: string;
}) {
  const [address, setAddress] = useState("");
  const [error, setError] = useState<string | null>(null);

  function submit(event: FormEvent) {
    event.preventDefault();
    if (!address.trim()) {
      setError("Enter a TON wallet address to start.");
      return;
    }
    onEnter(address);
  }

  return (
    <div className="gram-landing" style={{ "--atmosphere": `url(${background})` } as React.CSSProperties}>
      <div className="landing-atmosphere" aria-hidden="true" />
      <header className="landing-header">
        <Brand />
        <div className="landing-nav-note">Wallet intelligence for the TON blockchain</div>
        <ThemeToggle theme={theme} onChange={onThemeChange} />
      </header>

      <main className="landing-main">
        <div className="landing-kicker"><Sparkle size={17} weight="fill" /> Evidence, without the noise</div>
        <h1>See the full story behind every <em>GRAM</em> wallet.</h1>
        <p className="landing-lead">
          Follow activity, verify on-chain evidence and turn complex wallet history into a clear, canonical report.
        </p>

        <form className="landing-search" onSubmit={submit} noValidate>
          <MagnifyingGlass size={24} />
          <input
            value={address}
            onChange={(event) => {
              setAddress(event.target.value);
              setError(null);
            }}
            placeholder="Paste a TON wallet address"
            aria-label="TON wallet address"
            aria-describedby={error ? "landing-address-error" : undefined}
          />
          <button type="submit">Explore wallet <ArrowRight size={18} weight="bold" /></button>
        </form>
        {error && <p className="landing-error" id="landing-address-error">{error}</p>}
        <button className="browse-link" type="button" onClick={() => onEnter("")}>
          Open workspace without an address
        </button>

        <div className="landing-value-grid">
          <LandingValue icon={<ShieldCheck size={24} weight="duotone" />} title="Proof-first" text="Block inclusion, account state and wallet ownership stay separate and explicit." />
          <LandingValue icon={<Database size={24} weight="duotone" />} title="One canonical ledger" text="Reports, clustering and exports share the same evidence-aware source of truth." />
          <LandingValue icon={<Atom size={24} weight="duotone" />} title="Protocol-aware" text="Recognized DEX identities make swaps easier to understand without overclaiming." />
        </div>
      </main>

      <footer className="landing-footer">
        <span>GRAM is the native currency</span>
        <span>TON remains the blockchain</span>
        <span>{RELEASE_LABEL}</span>
      </footer>
    </div>
  );
}

function LandingValue({ icon, title, text }: { icon: ReactNode; title: string; text: string }) {
  return (
    <article className="landing-value">
      <span>{icon}</span>
      <div><strong>{title}</strong><p>{text}</p></div>
    </article>
  );
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <div className={compact ? "gram-brand is-compact" : "gram-brand"} aria-label="GRAM Scope">
      <span className="gram-brand-mark"><Planet size={compact ? 22 : 25} weight="duotone" /></span>
      <span><strong>GRAM Scope</strong>{!compact && <small>Wallet intelligence</small>}</span>
    </div>
  );
}

function ThemeToggle({ theme, onChange }: { theme: Theme; onChange: (theme: Theme) => void }) {
  const next = theme === "light" ? "dark" : "light";
  return (
    <button className="theme-toggle" type="button" onClick={() => onChange(next)} aria-label={`Switch to ${next} theme`}>
      {theme === "light" ? <Moon size={19} /> : <Sun size={19} />}
    </button>
  );
}

function WalletSearch({ value, onChange, onSubmit }: { value: string; onChange: (value: string) => void; onSubmit: () => void }) {
  function submit(event: FormEvent) {
    event.preventDefault();
    onSubmit();
  }
  return (
    <form className="topbar-search" onSubmit={submit}>
      <MagnifyingGlass size={19} />
      <input value={value} onChange={(event) => onChange(event.target.value)} placeholder="Search another TON wallet" aria-label="Search wallet" />
      <kbd>↵</kbd>
    </form>
  );
}

function PageHeading({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: ReactNode }) {
  return (
    <div className="page-heading">
      <div><span>{eyebrow}</span><h1>{title}</h1><p>{description}</p></div>
      {action}
    </div>
  );
}

function Overview({
  account,
  activeRun,
  dataMode,
  availableProviders,
  providerTotal,
  onOpenActivity,
  onRun,
}: {
  account: string;
  activeRun: WalletIngestionRunResponse | null;
  dataMode: string;
  availableProviders: number;
  providerTotal: number;
  onOpenActivity: () => void;
  onRun: () => void;
}) {
  const counts = activeRun?.activity_summary?.counts;
  const totalRecords = counts ? counts.transfers + counts.transactions + counts.swaps + counts.balances : 0;
  const portfolio = activeRun?.activity_summary?.balances.portfolio?.total_balance_usd;

  if (!activeRun) {
    return (
      <GeneralOverview
        account={account}
        dataMode={dataMode}
        availableProviders={availableProviders}
        providerTotal={providerTotal}
        onOpenActivity={onRun}
      />
    );
  }

  return (
    <>
      <PageHeading
        eyebrow="Wallet overview"
        title={account ? `A clearer view of ${shortAddress(account)}` : "Start with one wallet"}
        description={account ? "Your analysis is organized by activity, evidence, assets and canonical outputs." : "Add a TON wallet address above, then create an evidence-aware run."}
        action={<button className="button-primary" type="button" onClick={activeRun ? onOpenActivity : onRun}>{activeRun ? "Open activity" : "Start analysis"}<ArrowRight size={18} /></button>}
      />

      <div className="metric-grid">
        <Metric icon={<Database size={21} />} label="Records in active run" value={activeRun ? String(totalRecords) : "—"} detail={activeRun ? `Run #${activeRun.run_id}` : "No persisted run loaded"} tone="blue" />
        <Metric icon={<Wallet size={21} />} label="Portfolio snapshot" value={portfolio ? `$${Number(portfolio).toLocaleString(undefined, { maximumFractionDigits: 2 })}` : "—"} detail={portfolio ? "Provider-priced assets" : "Available after balance coverage"} tone="coral" />
        <Metric icon={<HardDrives size={21} />} label="Available sources" value={providerTotal ? `${availableProviders}/${providerTotal}` : "—"} detail={dataMode === "real" ? "Live provider mode" : "Configuration required"} tone="aqua" />
        <Metric icon={<ShieldCheck size={21} />} label="Evidence state" value={activeRun ? (activeRun.status === "success" ? "Ready" : activeRun.status) : "Not started"} detail={activeRun ? `${activeRun.warnings.length} run warnings` : "Fail-closed by default"} tone="lilac" />
      </div>

      <Suspense fallback={<div className="charts-loading"><SpinnerGap className="spin" size={24} />Preparing wallet charts…</div>}>
        <GramRunCharts
          run={activeRun}
          nextStep={<NextStepCard activeRun={activeRun} account={account} onOpenActivity={onOpenActivity} onRun={onRun} />}
        />
      </Suspense>
    </>
  );
}

function GeneralOverview({
  account,
  dataMode,
  availableProviders,
  providerTotal,
  onOpenActivity,
}: {
  account: string;
  dataMode: string;
  availableProviders: number;
  providerTotal: number;
  onOpenActivity: () => void;
}) {
  const capabilities = [
    { icon: <ChartLineUp size={24} weight="duotone" />, tone: "blue", title: "Activity map", text: "Transfers, transactions, DEX swaps and balance snapshots stay organized by one selected wallet and time window." },
    { icon: <ShieldCheck size={24} weight="duotone" />, tone: "lilac", title: "Proof center", text: "Provider observations, block inclusion, account state and ownership verification are shown as separate evidence levels." },
    { icon: <Atom size={24} weight="duotone" />, tone: "aqua", title: "Asset & DEX context", text: "GRAM, jettons and recognized protocols are grouped so users can understand what moved and where." },
    { icon: <FileText size={24} weight="duotone" />, tone: "coral", title: "Canonical outputs", text: "Ledger exports and reports use the same normalized source instead of rebuilding different answers for every screen." },
  ];
  return (
    <>
      <PageHeading
        eyebrow="Workspace overview"
        title="Everything you need to understand a TON wallet"
        description="GRAM Scope turns fragmented blockchain activity into a guided path: choose a wallet, check source coverage, review evidence and export one canonical result."
        action={<button className="button-primary" type="button" onClick={onOpenActivity}>{account ? "Inspect selected wallet" : "Choose a wallet"}<ArrowRight size={18} /></button>}
      />

      <section className="overview-intro-card">
        <div className="overview-intro-copy">
          <span className="eyebrow">How it works</span>
          <h2>From one address to an answer you can audit.</h2>
          <p>The interface keeps the investigative sequence short and visible. Nothing is silently upgraded from “observed” to “verified.”</p>
          {account && <div className="selected-wallet"><Wallet size={19} /><span><small>Selected wallet</small><strong>{shortAddress(account)}</strong></span></div>}
        </div>
        <ol className="overview-flow">
          <li><span>01</span><div><strong>Scope</strong><small>Wallet, period and data surfaces</small></div></li>
          <li><span>02</span><div><strong>Preview</strong><small>Provider coverage before persistence</small></div></li>
          <li><span>03</span><div><strong>Review</strong><small>Activity, identities and warnings</small></div></li>
          <li><span>04</span><div><strong>Export</strong><small>Canonical ledger and report</small></div></li>
        </ol>
      </section>

      <div className="capability-grid">
        {capabilities.map((item) => <article className="capability-card" key={item.title}><span className={`tone-${item.tone}`}>{item.icon}</span><h2>{item.title}</h2><p>{item.text}</p></article>)}
      </div>

      <section className="workspace-status-card">
        <div><span className={`large-status-dot mode-${dataMode}`} /><div><span className="eyebrow">Workspace status</span><h2>{dataMode === "real" ? "Live provider mode is active" : "Safe preview mode is active"}</h2><p>{dataMode === "real" ? "New runs can use configured live sources; proof-dependent outputs still remain explicit." : "You can explore the complete workflow while production-only evidence stays fail-closed."}</p></div></div>
        <dl><div><dt>Sources online</dt><dd>{providerTotal ? `${availableProviders} of ${providerTotal}` : "Checking"}</dd></div><div><dt>Native currency</dt><dd>GRAM</dd></div><div><dt>Blockchain</dt><dd>TON</dd></div><div><dt>Release</dt><dd>{RELEASE_LABEL}</dd></div></dl>
      </section>
    </>
  );
}

function Metric({ icon, label, value, detail, tone }: { icon: ReactNode; label: string; value: string; detail: string; tone: string }) {
  return <article className="metric-card"><span className={`metric-icon tone-${tone}`}>{icon}</span><div><span>{label}</span><strong>{value}</strong><small>{detail}</small></div></article>;
}

function NextStepCard({ activeRun, account, onOpenActivity, onRun }: { activeRun: WalletIngestionRunResponse | null; account: string; onOpenActivity: () => void; onRun: () => void }) {
  return (
    <article className="next-step-card">
      <span className="next-step-icon">{activeRun ? <CheckCircle size={26} weight="fill" /> : <Sparkle size={26} weight="fill" />}</span>
      <div><span className="eyebrow">Recommended next step</span><h2>{activeRun ? "Review proof coverage" : account ? "Create your first evidence run" : "Choose a wallet"}</h2><p>{activeRun ? `Run #${activeRun.run_id} is loaded. Inspect its canonical identity, trace evidence and warnings before exporting.` : account ? "Preview provider coverage, choose the surfaces you need and persist the result when it is ready." : "Paste a TON wallet address in the search field to organize the workspace around it."}</p></div>
      <button className="button-secondary" type="button" onClick={activeRun ? onOpenActivity : onRun} disabled={!account && !activeRun}>{activeRun ? "Inspect run" : "Open activity"}<ArrowRight size={17} /></button>
    </article>
  );
}

function ProofsView({ activeRun, onOpenActivity }: { activeRun: WalletIngestionRunResponse | null; onOpenActivity: () => void }) {
  const proofItems = [
    { icon: <Fingerprint size={24} />, title: "Wallet ownership", text: "Signature challenge binds a connected wallet to the requested address.", status: "Challenge available" },
    { icon: <ShieldCheck size={24} />, title: "Transaction inclusion", text: "BoC evidence can be anchored to the block and checked against the stored transaction.", status: "Cryptographic path" },
    { icon: <Database size={24} />, title: "Account state", text: "Account-state evidence is verified against the selected block context.", status: "Cryptographic path" },
  ];
  return (
    <>
      <PageHeading eyebrow="Proof center" title="Separate observation from verification" description="A provider response is useful evidence, but the interface never presents it as a blockchain or ownership proof without the matching cryptographic path." action={<button className="button-primary" type="button" onClick={onOpenActivity}>Inspect active run <ArrowRight size={18} /></button>} />
      <div className="proof-grid">
        {proofItems.map((item) => <article className="proof-card" key={item.title}><span>{item.icon}</span><div><small>{item.status}</small><h2>{item.title}</h2><p>{item.text}</p></div><CheckCircle size={21} weight="fill" /></article>)}
      </div>
      <article className="evidence-summary-card">
        <div><span className="eyebrow">Selected evidence scope</span><h2>{activeRun ? `Run #${activeRun.run_id}` : "No run selected"}</h2><p>{activeRun ? activeRun.message : "Create or open a persisted run in Activity to inspect transaction-level trace evidence and canonical identities."}</p></div>
        <dl>
          <div><dt>Network</dt><dd>{activeRun?.wallet_identity.network ?? "—"}</dd></div>
          <div><dt>Transactions</dt><dd>{activeRun?.transactions.length ?? "—"}</dd></div>
          <div><dt>Warnings</dt><dd>{activeRun?.warnings.length ?? "—"}</dd></div>
          <div><dt>Data mode</dt><dd>{activeRun?.data_mode ?? "—"}</dd></div>
        </dl>
      </article>
    </>
  );
}

function AssetsView({ activeRun, onOpenActivity }: { activeRun: WalletIngestionRunResponse | null; onOpenActivity: () => void }) {
  if (!activeRun) {
    return (
      <>
        <PageHeading eyebrow="Assets & protocols" title="Understand what moved — and where" description="Create or open a wallet run first. This section will group native GRAM, jettons and recognized DEX activity without mixing observation with proof." action={<button className="button-primary" type="button" onClick={onOpenActivity}>Open activity <ArrowRight size={18} /></button>} />
        <section className="clean-empty-state"><span><Atom size={30} weight="duotone" /></span><h2>No wallet activity selected</h2><p>Asset balances and protocol distribution will appear here after a run is loaded.</p></section>
      </>
    );
  }
  const transferAssets = activeRun.activity_summary?.transfers_by_asset ?? [];
  const dexRows = activeRun.activity_summary?.swaps_by_dex ?? [];
  const nativeBalance = activeRun.balances.find((item) => item.asset === "TON" || item.asset === "GRAM");
  const jettonBalances = activeRun.balances.filter((item) => item.asset !== "TON" && item.asset !== "GRAM");
  return (
    <>
      <PageHeading eyebrow="Assets & protocols" title="Understand what moved — and where" description="Native currency, jettons and recognized DEX activity from the active source-labelled run." />
      <div className="asset-metrics">
        <Metric icon={<Wallet size={21} />} label="Native balance" value={nativeBalance?.balance ? `${formatTokenAmount(nativeBalance.balance)} GRAM` : "—"} detail={nativeBalance ? `Snapshot from ${nativeBalance.provider}` : "No native balance snapshot"} tone="blue" />
        <Metric icon={<Coins size={21} />} label="Jetton snapshots" value={String(jettonBalances.length)} detail="Distinct returned balance rows" tone="coral" />
        <Metric icon={<Swap size={21} />} label="DEX swaps" value={String(activeRun.swaps.length)} detail={`${dexRows.length} recognized labels`} tone="aqua" />
      </div>
      <div className="asset-grid">
        <article className="asset-table-card">
          <header><div><h2>Asset movement</h2><p>Counts and net amounts reported for this run.</p></div><ArrowsClockwise size={21} /></header>
          {transferAssets.length ? <div className="asset-list">{transferAssets.map((asset) => <div key={asset.asset}><span className="asset-symbol">{asset.asset === "TON" ? "G" : asset.asset.slice(0, 2).toUpperCase()}</span><div><strong>{asset.asset === "TON" ? "GRAM" : asset.asset}</strong><small>{asset.in_count} in · {asset.out_count} out</small></div><span><small>Net amount</small><strong>{asset.net_amount}</strong></span></div>)}</div> : <div className="mini-empty">No transfer assets in this run.</div>}
        </article>
        <article className="asset-table-card">
          <header><div><h2>DEX distribution</h2><p>Provider-recognized protocol labels.</p></div><Atom size={21} /></header>
          {dexRows.length ? <div className="protocol-list">{dexRows.map((row, index) => <div key={row.dex}><span><i style={{ background: CHART_COLORS[index % CHART_COLORS.length] }} />{row.dex}</span><strong>{row.count}<small>swaps</small></strong></div>)}</div> : <div className="mini-empty">No recognized DEX swaps in this run.</div>}
        </article>
      </div>
      <article className="asset-table-card balance-card">
        <header><div><h2>Balance snapshots</h2><p>Source-labelled snapshots; they are not historical cost basis.</p></div><Database size={21} /></header>
        {activeRun.balances.length ? <div className="clean-table-wrap"><table className="clean-table"><thead><tr><th>Asset</th><th>Balance</th><th>USD value</th><th>Provider</th><th>Captured</th></tr></thead><tbody>{activeRun.balances.map((item, index) => <tr key={`${item.asset}-${index}`}><td><strong>{item.asset === "TON" ? "GRAM" : item.asset}</strong></td><td>{formatTokenAmount(item.balance)}</td><td>{item.balance_usd ? `$${formatTokenAmount(item.balance_usd)}` : "—"}</td><td>{item.provider}</td><td>{item.snapshot_at ? new Date(item.snapshot_at).toLocaleString() : "—"}</td></tr>)}</tbody></table></div> : <div className="mini-empty">No balance snapshots in this run.</div>}
      </article>
    </>
  );
}

function SourcesView({ providers, error }: { providers: ProvidersStatus | null; error: string | null }) {
  const items = providerItems(providers);
  return (
    <>
      <PageHeading eyebrow="Data sources" title="Know exactly what the system can see" description="Every provider keeps its own availability and limitation message, so a missing source never looks like complete coverage." />
      {error && <div className="activity-error" role="alert"><WarningCircle size={18} weight="fill" />{error}</div>}
      <div className="source-grid">
        {items.length ? items.map(([name, provider]) => (
          <article className="source-card" key={name}>
            <header><span className={provider.available ? "source-icon is-live" : "source-icon"}><HardDrives size={21} /></span><span className={provider.available ? "source-state is-live" : "source-state"}>{provider.available ? "Available" : "Unavailable"}</span></header>
            <h2>{name}</h2><p>{provider.message}</p>
            <footer><span className={provider.configured ? "configured" : ""}>{provider.configured ? "Configured" : "Not configured"}</span></footer>
          </article>
        )) : <div className="clean-empty-state source-empty"><SpinnerGap className="spin" size={28} /><h2>Checking providers</h2><p>Source health will appear as soon as the backend responds.</p></div>}
      </div>
      <section className="source-policy-card"><ShieldCheck size={27} weight="duotone" /><div><span className="eyebrow">Evidence policy</span><h2>Unavailable means unavailable.</h2><p>GRAM Scope does not fill missing live data with invented rows. Preview data, provider observations and cryptographic proof remain visibly distinct throughout the product.</p></div></section>
    </>
  );
}

function ReportsView({ activeRun, onOpenActivity }: { activeRun: WalletIngestionRunResponse | null; onOpenActivity: () => void }) {
  return (
    <>
      <PageHeading eyebrow="Canonical outputs" title="One ledger, every downstream answer" description="Reports and exports use the canonical ledger so the same normalized evidence flows into every downstream surface." action={!activeRun ? <button className="button-primary" type="button" onClick={onOpenActivity}>Select a run <ArrowRight size={18} /></button> : undefined} />
      <div className="report-grid">
        <ReportCard icon={<Database size={24} />} title="Canonical ledger" text="Normalized source-labelled activity for downstream analysis." run={activeRun} jsonUrl={activeRun ? walletRunExportUrl(activeRun.run_id) : undefined} csvUrl={activeRun ? walletRunExportCsvUrl(activeRun.run_id) : undefined} />
        <ReportCard icon={<FileText size={24} />} title="Canonical report" text="Evidence-aware summary built from the same ledger contract." run={activeRun} jsonUrl={activeRun ? walletCanonicalReportExportUrl(activeRun.run_id) : undefined} csvUrl={activeRun ? walletCanonicalReportCsvExportUrl(activeRun.run_id) : undefined} />
      </div>
    </>
  );
}

function ReportCard({ icon, title, text, run, jsonUrl, csvUrl }: { icon: ReactNode; title: string; text: string; run: WalletIngestionRunResponse | null; jsonUrl?: string; csvUrl?: string }) {
  return (
    <article className="report-card">
      <span>{icon}</span><div><small>{run ? `Run #${run.run_id}` : "Run required"}</small><h2>{title}</h2><p>{text}</p></div>
      <div className="report-actions">
        {jsonUrl ? <a href={jsonUrl}><DownloadSimple size={17} />JSON</a> : <button disabled><DownloadSimple size={17} />JSON</button>}
        {csvUrl ? <a href={csvUrl}><DownloadSimple size={17} />CSV</a> : <button disabled><DownloadSimple size={17} />CSV</button>}
      </div>
    </article>
  );
}
