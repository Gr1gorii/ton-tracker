import type { WalletGroup } from "../types";
import { shortAddress } from "../format";

interface Props {
  groups: WalletGroup[];
}

function scoreClass(score: number): string {
  if (score >= 86) return "score score-vhigh";
  if (score >= 71) return "score score-high";
  if (score >= 51) return "score score-mid";
  if (score >= 26) return "score score-low";
  return "score score-none";
}

export default function WalletGroups({ groups }: Props) {
  return (
    <section className="section">
      <div className="section-head">
        <h2>Wallet groups</h2>
        <div className="muted small">
          Probabilistic similarity signals — not proof of common ownership
        </div>
      </div>

      {groups.length === 0 ? (
        <div className="empty-inline">No candidate clusters detected.</div>
      ) : (
        <div className="card-grid">
          {groups.map((g) => (
            <div key={g.group_name} className="group-card">
              <div className="group-card-head">
                <span className="badge badge-group">{g.group_name}</span>
                <span
                  className={scoreClass(g.average_connected_score)}
                  title="Average pairwise similarity score"
                >
                  {g.average_connected_score.toFixed(0)}
                </span>
              </div>
              <div className="group-type">{g.group_type}</div>

              <div className="group-row">
                <span className="muted small">Shared tokens:</span>
                <div className="token-chips">
                  {g.shared_tokens.length > 0 ? (
                    g.shared_tokens.map((t) => (
                      <span key={t} className="chip">
                        {t}
                      </span>
                    ))
                  ) : (
                    <span className="muted">—</span>
                  )}
                </div>
              </div>

              <div className="group-row">
                <span className="muted small">
                  Wallets ({g.wallet_list.length}):
                </span>
                <div className="wallet-list">
                  {g.wallet_list.map((addr) => (
                    <span key={addr} className="mono small" title={addr}>
                      {shortAddress(addr)}
                    </span>
                  ))}
                </div>
              </div>

              <p className="group-reason">{g.reason_summary}</p>

              <div className="vyvod-box">
                <span className="vyvod-label">Вывод</span>
                <p>{g["Вывод"]}</p>
              </div>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
