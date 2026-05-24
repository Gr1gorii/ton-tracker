import type { Wallet } from "../types";
import {
  STATUS_LABELS,
  formatSignedUsd,
  formatUsd,
  pnlClass,
  shortAddress,
} from "../format";

interface Props {
  wallets: Wallet[];
}

export default function InterestingWallets({ wallets }: Props) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>
          Interesting wallets{" "}
          <span className="badge badge-interesting">ИНТЕРЕСНО</span>
        </h2>
        <div className="muted small">A token position worth more than $5,000</div>
      </div>

      {wallets.length === 0 ? (
        <div className="empty-inline">No interesting wallets in this window.</div>
      ) : (
        <div className="card-grid">
          {wallets.map((w) => (
            <div key={w.address} className="interesting-card">
              <div className="interesting-head">
                <span className="mono" title={w.address}>
                  {shortAddress(w.address)}
                </span>
                <div className="interesting-badges">
                  <span className={`badge status-${w.status}`}>
                    {STATUS_LABELS[w.status] ?? w.status}
                  </span>
                  {w.high_ton_balance && (
                    <span className="badge badge-whale">🐳 whale</span>
                  )}
                </div>
              </div>

              <div className="interesting-stats">
                <div>
                  <span className="muted small">Top position</span>
                  <div className="big">
                    {formatUsd(w.max_position_value_usd, 0)}
                  </div>
                </div>
                <div>
                  <span className="muted small">Portfolio</span>
                  <div className="big">
                    {formatUsd(w.portfolio_value_usd, 0)}
                  </div>
                </div>
                <div>
                  <span className="muted small">Total PnL</span>
                  <div className={`big ${pnlClass(w.total_pnl_usd)}`}>
                    {formatSignedUsd(w.total_pnl_usd)}
                  </div>
                </div>
              </div>

              <div className="token-chips">
                {w.positions.map((p) => (
                  <span key={p.symbol} className="chip">
                    {p.symbol} · {formatUsd(p.value_usd, 0)}
                  </span>
                ))}
              </div>

              <p className="vyvod-text small">{w["Вывод"]}</p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
