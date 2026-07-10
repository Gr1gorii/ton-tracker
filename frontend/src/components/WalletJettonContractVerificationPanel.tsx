import { useEffect, useMemo, useState } from "react";

import {
  getWalletJettonContractVerifications,
  verifyWalletJettonContractRelationship,
} from "../api";
import type {
  WalletBalanceSnapshotRecord,
  WalletJettonContractVerificationCatalogResponse,
} from "../types";
import {
  validateWalletJettonContractVerification,
  validateWalletJettonContractVerificationCatalog,
} from "../walletJettonContractVerification";

interface JettonPair {
  key: string;
  asset: string;
  wallet: string;
  master: string;
}

interface WalletJettonContractVerificationPanelProps {
  runId: number;
  dataMode: "mock" | "real";
  network: "ton-mainnet" | "ton-testnet" | "ton-unknown";
  balances: WalletBalanceSnapshotRecord[];
}

function canonicalAddress(value: unknown): string | null {
  return typeof value === "string" && /^(?:-1|0):[0-9a-f]{64}$/.test(value)
    ? value
    : null;
}

function eligiblePairs(balances: WalletBalanceSnapshotRecord[]): JettonPair[] {
  const pairs = new Map<string, JettonPair>();
  balances.forEach((balance) => {
    const raw = balance.raw;
    if (
      balance.provider !== "tonapi" ||
      balance.source_status !== "live" ||
      raw?.surface !== "jettons"
    ) {
      return;
    }
    const wallet = canonicalAddress(raw.wallet_contract_address);
    const master = canonicalAddress(raw.jetton_address);
    if (!wallet || !master || wallet === master) return;
    const key = `${wallet}|${master}`;
    pairs.set(key, { key, asset: balance.asset, wallet, master });
  });
  return [...pairs.values()];
}

function shortAddress(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-8)}`;
}

export default function WalletJettonContractVerificationPanel({
  runId,
  dataMode,
  network,
  balances,
}: WalletJettonContractVerificationPanelProps) {
  const pairs = useMemo(() => eligiblePairs(balances), [balances]);
  const supported =
    dataMode === "real" &&
    (network === "ton-mainnet" || network === "ton-testnet");
  const scopedNetwork = supported ? network : null;
  const [selectedKey, setSelectedKey] = useState(pairs[0]?.key ?? "");
  const [catalog, setCatalog] =
    useState<WalletJettonContractVerificationCatalogResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedKey((current) =>
      pairs.some((pair) => pair.key === current)
        ? current
        : (pairs[0]?.key ?? ""),
    );
  }, [pairs]);

  useEffect(() => {
    setCatalog(null);
    setError(null);
    if (!scopedNetwork) return;
    const controller = new AbortController();
    setLoading(true);
    getWalletJettonContractVerifications(runId, controller.signal)
      .then((value) => {
        setCatalog(
          validateWalletJettonContractVerificationCatalog(
            value,
            runId,
            scopedNetwork,
          ),
        );
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setError(
          reason instanceof Error
            ? reason.message
            : "Jetton contract verification read failed.",
        );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId, scopedNetwork]);

  const selected = pairs.find((pair) => pair.key === selectedKey) ?? null;

  async function verifySelected() {
    if (!selected || !scopedNetwork || loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await verifyWalletJettonContractRelationship(
        runId,
        selected.wallet,
        selected.master,
      );
      validateWalletJettonContractVerification(
        result,
        runId,
        scopedNetwork,
      );
      const refreshed = await getWalletJettonContractVerifications(runId);
      setCatalog(
        validateWalletJettonContractVerificationCatalog(
          refreshed,
          runId,
          scopedNetwork,
        ),
      );
    } catch (reason) {
      setError(
        reason instanceof Error
          ? reason.message
          : "Jetton contract proof verification failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="jetton-contract-panel" aria-labelledby="jetton-contract-title">
      <div className="jetton-contract-heading">
        <div>
          <span className="section-eyebrow">Contract identity · v0.27</span>
          <h2 id="jetton-contract-title">Verified jetton contracts</h2>
          <p>
            Select a persisted TonAPI balance relation, then verify its wallet,
            master, owner and code against proof-checked account state with local
            TVM getter execution.
          </p>
        </div>
        <span className="badge badge-provider">
          {catalog?.verification_count ?? 0} verified
        </span>
      </div>

      {!supported ? (
        <div className="state-box empty-box">
          <strong>Real network-scoped run required.</strong>
          <p>Mock and unscoped runs cannot establish jetton contract identity.</p>
        </div>
      ) : pairs.length === 0 ? (
        <div className="state-box empty-box">
          <strong>No eligible jetton relation.</strong>
          <p>
            This run needs a live TonAPI jetton balance snapshot containing both
            canonical wallet-contract and master addresses.
          </p>
        </div>
      ) : (
        <div className="jetton-contract-controls">
          <label>
            <span>Jetton relation</span>
            <select
              value={selectedKey}
              onChange={(event) => setSelectedKey(event.target.value)}
              disabled={loading}
            >
              {pairs.map((pair) => (
                <option key={pair.key} value={pair.key}>
                  {pair.asset} · {shortAddress(pair.master)}
                </option>
              ))}
            </select>
          </label>
          {selected && (
            <div className="jetton-contract-addresses">
              <span>Wallet {shortAddress(selected.wallet)}</span>
              <span>Master {shortAddress(selected.master)}</span>
            </div>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => void verifySelected()}
            disabled={!selected || loading}
          >
            {loading ? "Checking proofs…" : "Verify selected contract"}
          </button>
        </div>
      )}

      {error && (
        <div className="state-box error-box" role="alert">
          <strong>Verification unavailable.</strong>
          <p>{error}</p>
        </div>
      )}

      {catalog && catalog.verifications.length > 0 && (
        <div className="jetton-verification-grid">
          {catalog.verifications.map((row) => (
            <article
              className="jetton-verification-card"
              key={row.verification_id}
            >
              <div className="jetton-verification-card-title">
                <div>
                  <span className="section-eyebrow">{row.network}</span>
                  <h3>{shortAddress(row.jetton_master_account_canonical)}</h3>
                </div>
                <span className="source-badge source-live">Verified</span>
              </div>
              <dl>
                <div><dt>Owner + master</dt><dd>Matched</dd></div>
                <div><dt>Derived wallet</dt><dd>Matched</dd></div>
                <div><dt>Wallet code</dt><dd>Consistent</dd></div>
                <div><dt>Anchor</dt><dd>#{row.anchor.seqno}</dd></div>
                <div><dt>Trust level</dt><dd>{row.trust_level}</dd></div>
                <div><dt>Balance, base units</dt><dd>{row.wallet_balance_base_units}</dd></div>
              </dl>
              <p className="muted small">
                Account-state proof checked: yes. Full checkpoint chain: {row.masterchain_checkpoint_chain_verified ? "yes" : "not claimed"}.
                Cost basis and PnL remain disabled.
              </p>
              <code title={row.evidence_digest_sha256}>
                Evidence {row.evidence_digest_sha256.slice(0, 16)}…
              </code>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
