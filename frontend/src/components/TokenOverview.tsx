import type { AnalysisResult } from "../types";
import { formatNum, formatPrice, formatUsd, pnlClass } from "../format";

interface Props {
  result: AnalysisResult;
}

function Card({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
}) {
  return (
    <div className="stat-card">
      <div className="stat-label">{label}</div>
      <div className={`stat-value ${valueClass ?? ""}`}>{value}</div>
      {sub && <div className="stat-sub">{sub}</div>}
    </div>
  );
}

export default function TokenOverview({ result }: Props) {
  const { token, pool, summary, analyzed_window } = result;

  const start = new Date(analyzed_window.start).toLocaleString();
  const end = new Date(analyzed_window.end).toLocaleString();

  return (
    <section className="section">
      <div className="section-head">
        <h2>
          {token.name} <span className="muted">({token.symbol})</span>
        </h2>
        <div className="muted small">
          {pool.base_token}/{pool.quote_token} · {pool.dex}
        </div>
      </div>

      <div className="muted small window-line">
        Window: <strong>{result.time_window}</strong> · {start} → {end}
      </div>

      <div className="stat-grid">
        <Card label="Price" value={formatPrice(token.current_price_usd)} />
        <Card label="Market cap" value={formatUsd(token.market_cap_usd, 0)} />
        <Card label="Liquidity" value={formatUsd(pool.liquidity_usd, 0)} />
        <Card
          label="Volume 24h"
          value={formatUsd(pool.volume_24h_usd, 0)}
        />
        <Card label="Buyers analyzed" value={formatNum(summary.total_buyers)} />
        <Card
          label="Holders / Partial / Exit"
          value={`${summary.holders} / ${summary.partial_sellers} / ${summary.full_exits}`}
        />
        <Card
          label="Interesting"
          value={formatNum(summary.interesting_count)}
          sub="position > $5,000"
        />
        <Card
          label="Whales"
          value={formatNum(summary.whale_count)}
          sub="TON balance > 500"
        />
        <Card
          label="Candidate clusters"
          value={formatNum(summary.group_count)}
          sub="probabilistic"
        />
        <Card
          label="Total realised PnL"
          value={formatUsd(summary.total_realised_pnl_usd)}
          valueClass={pnlClass(summary.total_realised_pnl_usd)}
        />
        <Card
          label="Total unrealised PnL"
          value={formatUsd(summary.total_unrealised_pnl_usd)}
          valueClass={pnlClass(summary.total_unrealised_pnl_usd)}
        />
      </div>
    </section>
  );
}
