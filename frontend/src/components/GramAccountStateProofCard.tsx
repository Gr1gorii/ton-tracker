import { useEffect, useMemo, useState } from "react";
import {
  Check,
  CheckCircle,
  Database,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import {
  getWalletJettonContractVerifications,
  verifyWalletJettonContractRelationship,
} from "../api";
import type {
  WalletBalanceSnapshotRecord,
  WalletJettonContractVerificationCatalogResponse,
  WalletJettonContractVerificationResponse,
} from "../types";
import {
  validateWalletJettonContractVerification,
  validateWalletJettonContractVerificationCatalog,
} from "../walletJettonContractVerification";

interface GramAccountStateProofCardProps {
  runId: number;
  dataMode: "mock" | "real";
  network: "ton-mainnet" | "ton-testnet" | "ton-unknown";
  balances: WalletBalanceSnapshotRecord[];
}

interface JettonPair {
  key: string;
  asset: string;
  wallet: string;
  master: string;
}

export default function GramAccountStateProofCard({
  runId,
  dataMode,
  network,
  balances,
}: GramAccountStateProofCardProps) {
  const pairs = useMemo(() => eligiblePairs(balances), [balances]);
  const supported = dataMode === "real" && (network === "ton-mainnet" || network === "ton-testnet");
  const scopedNetwork = supported ? network : null;
  const [selectedKey, setSelectedKey] = useState(pairs[0]?.key ?? "");
  const [catalog, setCatalog] =
    useState<WalletJettonContractVerificationCatalogResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSelectedKey((current) =>
      pairs.some((pair) => pair.key === current) ? current : pairs[0]?.key ?? "",
    );
  }, [pairs]);

  useEffect(() => {
    setCatalog(null);
    setError(null);
    if (!scopedNetwork) return;
    const controller = new AbortController();
    setLoading(true);
    void getWalletJettonContractVerifications(runId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setCatalog(validateWalletJettonContractVerificationCatalog(value, runId, scopedNetwork));
        }
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [runId, scopedNetwork]);

  const selected = pairs.find((pair) => pair.key === selectedKey) ?? null;
  const verification = selected
    ? catalog?.verifications.find(
        (row) =>
          row.jetton_wallet_account_canonical === selected.wallet &&
          row.jetton_master_account_canonical === selected.master,
      ) ?? null
    : null;

  async function verifySelected() {
    if (!selected || !scopedNetwork || loading) return;
    setLoading(true);
    setError(null);
    try {
      const result = await verifyWalletJettonContractRelationship(runId, selected.wallet, selected.master);
      validateWalletJettonContractVerification(result, runId, scopedNetwork);
      const refreshed = await getWalletJettonContractVerifications(runId);
      setCatalog(validateWalletJettonContractVerificationCatalog(refreshed, runId, scopedNetwork));
    } catch (reason) {
      setError(errorMessage(reason));
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className={verification ? "gram-proof-flow account-proof-flow is-verified" : "gram-proof-flow account-proof-flow"}>
      <header className="gram-proof-flow-header">
        <span className="gram-proof-flow-icon tone-coral"><Database size={25} weight="duotone" /></span>
        <div>
          <small>Account state</small>
          <h2>Jetton wallet identity from verified account state</h2>
          <p>Check stored account-state material, execute getters locally and bind wallet, master, owner and code without overstating canonical-chain trust.</p>
        </div>
        <span className={verification ? "gram-proof-status is-verified" : "gram-proof-status"}>
          {loading ? <SpinnerGap className="spin" size={15} /> : verification ? <CheckCircle size={15} weight="fill" /> : <Database size={15} />}
          {verification ? "Verified" : `${catalog?.verification_count ?? 0} stored`}
        </span>
      </header>

      {!supported ? (
        <AccountNotice error={false} title="Live network-scoped run required">
          Mock or unknown-network data cannot establish account-state inclusion.
        </AccountNotice>
      ) : pairs.length === 0 ? (
        <AccountNotice error={false} title="No eligible jetton account">
          A live TonAPI jetton balance containing canonical wallet and master addresses is required.
        </AccountNotice>
      ) : (
        <>
          <div className="gram-proof-selector account-proof-selector">
            <label htmlFor={`gram-account-proof-${runId}`}>Jetton relation</label>
            <select id={`gram-account-proof-${runId}`} value={selectedKey} disabled={loading} onChange={(event) => { setSelectedKey(event.target.value); setError(null); }}>
              {pairs.map((pair) => <option key={pair.key} value={pair.key}>{pair.asset} · {shortAddress(pair.master)}</option>)}
            </select>
            <span>{scopedNetwork}</span>
          </div>

          {selected && (
            <div className="account-proof-addresses">
              <div><span>Wallet contract</span><code title={selected.wallet}>{shortAddress(selected.wallet)}</code></div>
              <div><span>Jetton master</span><code title={selected.master}>{shortAddress(selected.master)}</code></div>
            </div>
          )}

          {error && <AccountNotice error title="Verification stopped">{error}</AccountNotice>}

          {!verification && (
            <div className="gram-proof-action-row">
              <button className="button-primary" type="button" disabled={!selected || loading} onClick={() => void verifySelected()}>
                {loading ? <SpinnerGap className="spin" /> : <Database />}
                {loading ? "Checking proofs…" : "Verify account state"}
              </button>
              <p>Proof material is checked and stored without exposing raw account-state BOCs in the response.</p>
            </div>
          )}

          {verification && <AccountProofResult verification={verification} />}
        </>
      )}
    </section>
  );
}

function AccountProofResult({ verification }: { verification: WalletJettonContractVerificationResponse }) {
  const hasPersistedMerkleProofs = verification.account_state_inclusion_proofs.length === 2;
  return (
    <div className="gram-proof-result">
      <div className="gram-proof-result-banner">
        <CheckCircle size={20} weight="fill" />
        <div>
          <strong>Account state and jetton relationship verified.</strong>
          <span>
            {hasPersistedMerkleProofs
              ? "Two persisted account Merkle proofs were revalidated. Legacy v1 did not persist the checkpoint policy, so canonical chain inclusion is not claimed."
              : "This legacy record predates persisted account Merkle proofs and did not persist the checkpoint policy; canonical chain inclusion is not claimed."}
          </span>
        </div>
        <span title={`Recorded liteserver trust level ${verification.trust_level}`}>Legacy · non-canonical</span>
      </div>
      <div className="account-proof-checks">
        <span>{hasPersistedMerkleProofs ? <Check weight="bold" /> : <WarningCircle weight="fill" />}{hasPersistedMerkleProofs ? "2 account proofs" : "Legacy proof gap"}</span>
        <span><Check weight="bold" />Local TVM</span>
        <span><Check weight="bold" />Owner + master</span>
        <span><Check weight="bold" />Wallet code</span>
      </div>
      <dl className="gram-proof-facts">
        <div><dt>Observed anchor</dt><dd>#{verification.anchor.seqno}</dd></div>
        <div><dt>Balance units</dt><dd>{verification.wallet_balance_base_units}</dd></div>
        <div><dt>Total supply</dt><dd>{verification.total_supply_base_units}</dd></div>
        <div><dt>Evidence</dt><dd title={verification.evidence_digest_sha256}>{shortAddress(verification.evidence_digest_sha256)}</dd></div>
      </dl>
    </div>
  );
}

function AccountNotice({ title, children, error }: { title: string; children: React.ReactNode; error: boolean }) {
  return (
    <div className={error ? "gram-proof-notice is-error" : "gram-proof-notice"} role={error ? "alert" : "status"}>
      {error ? <WarningCircle size={20} weight="fill" /> : <Database size={20} />}
      <div><strong>{title}</strong><span>{children}</span></div>
    </div>
  );
}

function eligiblePairs(balances: WalletBalanceSnapshotRecord[]): JettonPair[] {
  const pairs = new Map<string, JettonPair>();
  balances.forEach((balance) => {
    const raw = balance.raw;
    if (balance.provider !== "tonapi" || balance.source_status !== "live" || raw?.surface !== "jettons") return;
    const wallet = canonicalAddress(raw.wallet_contract_address);
    const master = canonicalAddress(raw.jetton_address);
    if (!wallet || !master || wallet === master) return;
    const key = `${wallet}|${master}`;
    pairs.set(key, { key, asset: balance.asset, wallet, master });
  });
  return [...pairs.values()];
}

function canonicalAddress(value: unknown): string | null {
  return typeof value === "string" && /^(?:-1|0):[0-9a-f]{64}$/.test(value) ? value : null;
}

function shortAddress(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-8)}`;
}

function errorMessage(reason: unknown): string {
  return reason instanceof Error && reason.message ? reason.message : "Account-state verification failed.";
}
