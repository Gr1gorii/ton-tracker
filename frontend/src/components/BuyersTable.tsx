import type { Wallet } from "../types";
import {
  STATUS_LABELS,
  formatNum,
  formatPrice,
  formatSignedUsd,
  formatPct,
  formatUsd,
  pnlClass,
  shortAddress,
} from "../format";

interface Props {
  wallets: Wallet[];
}

function scoreClass(score: number): string {
  if (score >= 86) return "score score-vhigh";
  if (score >= 71) return "score score-high";
  if (score >= 51) return "score score-mid";
  if (score >= 26) return "score score-low";
  return "score score-none";
}

function GroupBadge({ group }: { group: string }) {
  if (!group || group === "none") return <span className="muted">—</span>;
  return <span className="badge badge-group">{group}</span>;
}

export default function BuyersTable({ wallets }: Props) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>Buyer wallets</h2>
        <div className="muted small">{wallets.length} wallets</div>
      </div>

      <div className="table-wrap">
        <table className="data-table">
          <thead>
            <tr>
              <th>Wallet</th>
              <th>Status</th>
              <th className="num">Bought</th>
              <th className="num">Sold</th>
              <th className="num">Holding</th>
              <th className="num">Avg Buy</th>
              <th className="num">Avg Sell</th>
              <th className="num">Realised PnL</th>
              <th className="num">Realised %</th>
              <th className="num">Unrealised PnL</th>
              <th className="num">Unrealised %</th>
              <th className="num">Total PnL</th>
              <th className="num">TON Balance</th>
              <th className="num">Portfolio Value</th>
              <th>Common Tokens</th>
              <th>Group</th>
              <th className="num">Connected Score</th>
              <th>ИНТЕРЕСНО</th>
              <th className="vyvod-col">Вывод</th>
            </tr>
          </thead>
          <tbody>
            {wallets.map((w) => (
              <tr key={w.address}>
                <td className="mono" title={w.address}>
                  {shortAddress(w.address)}
                </td>
                <td>
                  <span className={`badge status-${w.status}`}>
                    {STATUS_LABELS[w.status] ?? w.status}
                  </span>
                </td>
                <td className="num">
                  {formatNum(w.total_bought_qty)}
                  <div className="cell-sub">
                    {formatUsd(w.total_bought_usd)}
                  </div>
                </td>
                <td className="num">
                  {formatNum(w.total_sold_qty)}
                  <div className="cell-sub">{formatUsd(w.total_sold_usd)}</div>
                </td>
                <td className="num">{formatNum(w.current_holding)}</td>
                <td className="num">{formatPrice(w.avg_buy_price_usd)}</td>
                <td className="num">
                  {w.avg_sell_price_usd > 0
                    ? formatPrice(w.avg_sell_price_usd)
                    : "—"}
                </td>
                <td className={`num ${pnlClass(w.realised_pnl_usd)}`}>
                  {formatSignedUsd(w.realised_pnl_usd)}
                </td>
                <td className={`num ${pnlClass(w.realised_pnl_pct)}`}>
                  {formatPct(w.realised_pnl_pct)}
                </td>
                <td className={`num ${pnlClass(w.unrealised_pnl_usd)}`}>
                  {formatSignedUsd(w.unrealised_pnl_usd)}
                </td>
                <td className={`num ${pnlClass(w.unrealised_pnl_pct)}`}>
                  {formatPct(w.unrealised_pnl_pct)}
                </td>
                <td className={`num ${pnlClass(w.total_pnl_usd)}`}>
                  {formatSignedUsd(w.total_pnl_usd)}
                  <div className="cell-sub">{formatPct(w.total_pnl_pct)}</div>
                </td>
                <td className="num">
                  {formatNum(w.ton_balance, 2)}
                  {w.high_ton_balance && (
                    <span className="badge badge-whale" title="TON balance > 500">
                      🐳 whale
                    </span>
                  )}
                </td>
                <td className="num">{formatUsd(w.portfolio_value_usd)}</td>
                <td>
                  <div className="token-chips">
                    {w.common_tokens.map((t) => (
                      <span key={t} className="chip">
                        {t}
                      </span>
                    ))}
                  </div>
                </td>
                <td>
                  <GroupBadge group={w.group} />
                </td>
                <td className="num">
                  <span className={scoreClass(w.connected_score)}>
                    {w.connected_score.toFixed(0)}
                  </span>
                </td>
                <td>
                  {w.interesting ? (
                    <span className="badge badge-interesting">ИНТЕРЕСНО</span>
                  ) : (
                    <span className="muted">—</span>
                  )}
                </td>
                <td className="vyvod-col">
                  <span className="vyvod-text">{w["Вывод"]}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
