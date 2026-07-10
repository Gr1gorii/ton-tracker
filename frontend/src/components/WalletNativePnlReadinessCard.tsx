import { useState, type FormEvent } from "react";
import { inspectWalletMultiAssetPnlReadiness } from "../api";
import type {
  WalletMultiAssetPnlReadinessResponse,
  WalletMultiAssetPnlRequirementCode,
} from "../types";
import PreviewReadinessStrip, {
  type PreviewReadinessTone,
} from "./PreviewReadinessStrip";
import { parseSelectedRunIds } from "./selectedRunIds";

interface WalletNativePnlReadinessCardProps {
  targetRunId: number;
}

const requirementLabels: Record<WalletMultiAssetPnlRequirementCode, string> = {
  deduplicated_native_activity: "Deduplicated native activity",
  verified_jetton_payload_semantics: "Verified jetton payload semantics",
  provider_scoped_jetton_asset_evidence: "Provider-scoped jetton asset evidence",
  exact_transaction_fee_evidence: "Exact transaction fee evidence",
  complete_wallet_history: "Complete wallet history",
  authoritative_trade_semantics: "Authoritative trade semantics",
  historical_trade_prices: "Historical trade prices",
  transaction_fee_allocation: "Transaction fee allocation",
  acquisition_lots_and_cost_basis: "Acquisition lots and cost basis",
};

export default function WalletNativePnlReadinessCard({
  targetRunId,
}: WalletNativePnlReadinessCardProps) {
  const [otherRunIds, setOtherRunIds] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] =
    useState<WalletMultiAssetPnlReadinessResponse | null>(null);
  const inputId = `native-pnl-runs-${targetRunId}`;
  const readiness = pnlReadiness({ loading, error, result });

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parseSelectedRunIds(otherRunIds, targetRunId);
    if ("error" in parsed) {
      setError(parsed.error);
      setResult(null);
      return;
    }
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await inspectWalletMultiAssetPnlReadiness(targetRunId, parsed.runIds),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Multi-asset PnL readiness failed.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <section
      className="intelligence-table-block native-pnl-readiness-card"
      aria-labelledby={`native-pnl-title-${targetRunId}`}
    >
      <div className="table-toolbar native-pnl-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Multi-run evidence gate</span>
          <h2 id={`native-pnl-title-${targetRunId}`}>
            Multi-asset PnL readiness
          </h2>
          <p>
            Revalidate native TON activity and verified TEP-74 observations,
            then reconcile provider snapshot asset matches and exact fees.
          </p>
        </div>
        <div className="table-meta" aria-label="PnL readiness limitations">
          <span className="badge badge-real">BOC-VERIFIED INPUT</span>
          <span className="badge badge-mock">PNL LOCKED</span>
        </div>
      </div>

      <form
        className="wallet-ingestion-form wallet-query-card native-pnl-form"
        onSubmit={handleSubmit}
      >
        <div className="field">
          <label className="field-label" htmlFor={inputId}>
            Other run IDs for evidence reconciliation
          </label>
          <input
            id={inputId}
            className="text-input"
            type="text"
            value={otherRunIds}
            disabled={loading}
            maxLength={512}
            placeholder="e.g. 32, 33"
            onChange={(event) => {
              setOtherRunIds(event.target.value);
              setError(null);
              setResult(null);
            }}
          />
          <small className="interval-coverage-help">
            Run #{targetRunId} is included automatically. Every selected run
            must belong to the same canonical wallet and network.
          </small>
        </div>
        <button
          className="btn btn-primary"
          type="submit"
          disabled={loading || otherRunIds.trim() === ""}
        >
          {loading ? "Reconciling evidence" : "Check multi-asset readiness"}
        </button>
      </form>

      <PreviewReadinessStrip
        tone={readiness.tone}
        label={readiness.label}
        message={readiness.message}
        items={[
          { label: "Target", value: `Run #${targetRunId}` },
          {
            label: "Canonical native",
            value: result
              ? String(result.native_flow_summary.activity_count)
              : "Awaiting selection",
          },
          {
            label: "Verified jetton",
            value: result
              ? String(
                  result.jetton_evidence_summary
                    .deduplicated_payload_observation_count,
                )
              : "Awaiting selection",
          },
          {
            label: "Net native flow",
            value: result
              ? `${result.native_flow_summary.net_ton} TON`
              : "Unavailable",
          },
        ]}
      />

      {result && (
        <div className="native-pnl-results">
          <div className="native-pnl-flow-grid">
            <FlowMetric
              label="Incoming"
              value={`${result.native_flow_summary.incoming_ton} TON`}
              detail={`${result.native_flow_summary.incoming_activity_count} canonical activities`}
            />
            <FlowMetric
              label="Outgoing"
              value={`${result.native_flow_summary.outgoing_ton} TON`}
              detail={`${result.native_flow_summary.outgoing_activity_count} canonical activities`}
            />
            <FlowMetric
              label="Self"
              value={`${result.native_flow_summary.self_ton} TON`}
              detail={`${result.native_flow_summary.self_activity_count} canonical activities`}
            />
            <FlowMetric
              label="Net observed flow"
              value={`${result.native_flow_summary.net_ton} TON`}
              detail="Incoming minus outgoing; not profit"
            />
          </div>

          <div className="native-pnl-flow-grid multi-asset-evidence-grid">
            <FlowMetric
              label="Recognized payloads"
              value={String(
                result.jetton_evidence_summary
                  .deduplicated_payload_observation_count,
              )}
              detail={`${result.jetton_evidence_summary.suppressed_payload_occurrence_count} repeated occurrences suppressed`}
            />
            <FlowMetric
              label="Asset matches"
              value={String(
                result.jetton_evidence_summary.asset_matched_observation_count,
              )}
              detail="Provider snapshot evidence; not local master proof"
            />
            <FlowMetric
              label="Fee matches"
              value={String(
                result.jetton_evidence_summary.fee_linked_observation_count,
              )}
              detail="Exact transaction hash matches"
            />
            <FlowMetric
              label="Linked fees"
              value={`${result.jetton_evidence_summary.linked_fee_ton} TON`}
              detail="Evidence only; not allocated to lots"
            />
          </div>

          <div className="native-pnl-gate" role="note">
            <div>
              <span>Calculation state</span>
              <strong>PNL REMAINS LOCKED</strong>
            </div>
            <p>{result.message}</p>
          </div>

          <ul className="native-pnl-requirements" aria-label="PnL requirements">
            {result.requirements.map((requirement) => (
              <li
                key={requirement.code}
                className={requirement.available ? "is-ready" : "is-blocked"}
              >
                <span aria-hidden="true">
                  {requirement.available ? "✓" : "×"}
                </span>
                <div>
                  <strong>{requirementLabels[requirement.code]}</strong>
                  <p>{requirement.reason ?? "Evidence requirement satisfied."}</p>
                </div>
              </li>
            ))}
          </ul>

          {result.evidence.length > 0 && (
            <div className="table-wrap multi-asset-evidence-table-wrap">
              <table className="data-table multi-asset-evidence-table">
                <caption>
                  Deduplicated verified jetton observations with bounded asset
                  and fee evidence. No row is a trade or cost-basis lot.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Operation</th>
                    <th scope="col">Occurrences</th>
                    <th scope="col">Asset evidence</th>
                    <th scope="col">Fee evidence</th>
                  </tr>
                </thead>
                <tbody>
                  {result.evidence.map((row) => (
                    <tr key={row.payload_observation_identity}>
                      <th scope="row">{row.operation.replace(/_/g, " ")}</th>
                      <td>{row.occurrence_count}</td>
                      <td>
                        {row.asset_binding_status === "provider_snapshot_match"
                          ? `${row.asset_symbol ?? "master matched"} · provider snapshot`
                          : "unavailable"}
                      </td>
                      <td>
                        {row.transaction_fee_evidence_status ===
                        "exact_transaction_match"
                          ? `${row.transaction_fee_ton} TON · unallocated`
                          : "unavailable"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="muted small native-pnl-digest">
            Contract {result.contract_version} · analysis digest {" "}
            <code>{shortDigest(result.analysis_digest_sha256)}</code>
          </p>
        </div>
      )}
    </section>
  );
}

function FlowMetric({
  label,
  value,
  detail,
}: {
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <div className="native-pnl-flow-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </div>
  );
}

function pnlReadiness({
  loading,
  error,
  result,
}: {
  loading: boolean;
  error: string | null;
  result: WalletMultiAssetPnlReadinessResponse | null;
}): { tone: PreviewReadinessTone; label: string; message: string } {
  if (loading) {
    return {
      tone: "running",
      label: "RECONCILING MULTI-ASSET EVIDENCE",
      message: "Revalidating native ledgers, BOCs, asset snapshots, and fees.",
    };
  }
  if (error) {
    return { tone: "error", label: "READINESS CHECK FAILED", message: error };
  }
  if (result) {
    return {
      tone: "warning",
      label: "EVIDENCE RECONCILED · PNL LOCKED",
      message: `${result.selected_run_ids.length} runs reconciled. ${result.blocked_requirement_codes.length} evidence requirements remain blocked.`,
    };
  }
  return {
    tone: "warning",
    label: "RUNS REQUIRED",
    message: "Select at least one additional stored run with a native ledger.",
  };
}

function shortDigest(value: string): string {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}
