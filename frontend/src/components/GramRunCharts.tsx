import { Atom, ChartDonut, ChartLineUp, ListMagnifyingGlass } from "@phosphor-icons/react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { type ReactNode, useMemo } from "react";
import type { WalletIngestionRunResponse } from "../types";

const CHART_COLORS = ["#4f6df5", "#ff7769", "#55c8be", "#9b7de4", "#f2a65a"];

export default function GramRunCharts({ run, nextStep }: { run: WalletIngestionRunResponse; nextStep: ReactNode }) {
  const counts = run.activity_summary?.counts;
  const totalRecords = counts ? counts.transfers + counts.transactions + counts.swaps + counts.balances : 0;
  const activityMix = counts
    ? [
        { name: "Transfers", value: counts.transfers },
        { name: "Transactions", value: counts.transactions },
        { name: "Swaps", value: counts.swaps },
        { name: "Balances", value: counts.balances },
      ].filter((item) => item.value > 0)
    : [];
  const flowData = useMemo(() => {
    const buckets = new Map<string, { label: string; incoming: number; outgoing: number; swaps: number }>();
    const bucketFor = (timestamp?: string | null) => {
      const label = timestamp ? new Date(timestamp).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : "Unknown";
      if (!buckets.has(label)) buckets.set(label, { label, incoming: 0, outgoing: 0, swaps: 0 });
      return buckets.get(label)!;
    };
    run.transfers.forEach((item) => {
      const bucket = bucketFor(item.timestamp);
      if (item.direction === "in") bucket.incoming += 1;
      if (item.direction === "out") bucket.outgoing += 1;
    });
    run.swaps.forEach((item) => { bucketFor(item.timestamp).swaps += 1; });
    return Array.from(buckets.values()).slice(-8);
  }, [run]);
  const protocols = run.activity_summary?.swaps_by_dex ?? [];

  return (
    <>
      <div className="overview-grid">
        <article className="chart-card chart-wide">
          <ChartHeader title="Activity over time" subtitle="Observed records in the active run" />
          {flowData.length ? (
            <div className="chart-frame">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={flowData} margin={{ left: -18, right: 8, top: 12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 5" vertical={false} stroke="var(--chart-grid)" />
                  <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: "var(--text-muted)", fontSize: 11 }} />
                  <YAxis allowDecimals={false} tickLine={false} axisLine={false} tick={{ fill: "var(--text-muted)", fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "var(--surface-elevated)", border: "1px solid var(--border)", borderRadius: 12, color: "var(--text)" }} />
                  <Area type="monotone" dataKey="incoming" stackId="1" stroke="#55c8be" fill="#55c8be" fillOpacity={0.24} />
                  <Area type="monotone" dataKey="outgoing" stackId="1" stroke="#ff7769" fill="#ff7769" fillOpacity={0.2} />
                  <Area type="monotone" dataKey="swaps" stackId="1" stroke="#4f6df5" fill="#4f6df5" fillOpacity={0.18} />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : <ChartEmpty icon={<ChartLineUp size={28} />} text="No timestamped activity in this run." />}
          <div className="chart-legend"><span><i className="legend-aqua" />Incoming</span><span><i className="legend-coral" />Outgoing</span><span><i className="legend-blue" />Swaps</span></div>
        </article>

        <article className="chart-card">
          <ChartHeader title="Activity mix" subtitle="How the current evidence is distributed" />
          {activityMix.length ? (
            <div className="donut-wrap">
              <ResponsiveContainer width="100%" height={210}>
                <PieChart>
                  <Pie data={activityMix} dataKey="value" nameKey="name" innerRadius={60} outerRadius={88} paddingAngle={3}>
                    {activityMix.map((item, index) => <Cell key={item.name} fill={CHART_COLORS[index % CHART_COLORS.length]} />)}
                  </Pie>
                  <Tooltip contentStyle={{ background: "var(--surface-elevated)", border: "1px solid var(--border)", borderRadius: 12, color: "var(--text)" }} />
                </PieChart>
              </ResponsiveContainer>
              <strong>{totalRecords}<small>records</small></strong>
            </div>
          ) : <ChartEmpty icon={<ChartDonut size={28} />} text="No activity distribution yet." />}
          <div className="mix-list">
            {activityMix.map((item, index) => <span key={item.name}><i style={{ background: CHART_COLORS[index % CHART_COLORS.length] }} />{item.name}<strong>{item.value}</strong></span>)}
          </div>
        </article>
      </div>

      <div className="overview-grid secondary-grid">
        <article className="chart-card">
          <ChartHeader title="DEX protocols" subtitle="Recognized swap observations" />
          {protocols.length ? (
            <div className="bar-chart-frame">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={protocols} layout="vertical" margin={{ left: 8, right: 18 }}>
                  <XAxis type="number" hide allowDecimals={false} />
                  <YAxis type="category" dataKey="dex" width={88} tickLine={false} axisLine={false} tick={{ fill: "var(--text-muted)", fontSize: 11 }} />
                  <Tooltip contentStyle={{ background: "var(--surface-elevated)", border: "1px solid var(--border)", borderRadius: 12, color: "var(--text)" }} />
                  <Bar dataKey="count" fill="#4f6df5" radius={[0, 7, 7, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : <ChartEmpty icon={<Atom size={28} />} text="DEX distribution appears when the run includes recognized swaps." />}
        </article>
        {nextStep}
      </div>
    </>
  );
}

function ChartHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return <header className="chart-header"><div><h2>{title}</h2><p>{subtitle}</p></div><ListMagnifyingGlass size={21} /></header>;
}

function ChartEmpty({ icon, text }: { icon: ReactNode; text: string }) {
  return <div className="chart-empty"><span>{icon}</span><p>{text}</p></div>;
}
