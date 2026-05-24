import type { CommonHolding } from "../types";
import { formatUsd } from "../format";

interface Props {
  holdings: CommonHolding[];
}

export default function CommonHoldings({ holdings }: Props) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>Common holdings</h2>
        <div className="muted small">Tokens held by 2+ analyzed wallets</div>
      </div>

      {holdings.length === 0 ? (
        <div className="empty-inline">No shared holdings found.</div>
      ) : (
        <div className="holdings-grid">
          {holdings.map((h) => (
            <div key={h.token} className="holding-card">
              <div className="holding-token">{h.token}</div>
              <div className="holding-stats">
                <span>
                  <strong>{h.holder_count}</strong> wallets
                </span>
                <span className="muted">{formatUsd(h.total_value_usd, 0)}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
