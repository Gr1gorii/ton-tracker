import { useState, type FormEvent } from "react";
import { inspectWalletNativePnlReadiness } from "../api";
import type {
  WalletNativeActivityPnlReadinessResponse,
  WalletNativeActivityPnlRequirementCode,
} from "../types";
import PreviewReadinessStrip, {
  type PreviewReadinessTone,
} from "./PreviewReadinessStrip";
import { parseSelectedRunIds } from "./selectedRunIds";

interface WalletNativePnlReadinessCardProps {
  targetRunId: number;
}

const requirementLabels: Record<WalletNativeActivityPnlRequirementCode, string> = {
  deduplicated_native_activity: "Deduplicated native activity",
  complete_wallet_history: "Complete wallet history",
  authoritative_trade_semantics: "Authoritative trade semantics",
  jetton_asset_identity: "Jetton asset identity",
  historical_trade_prices: "Historical trade prices",
  transaction_fee_linkage: "Transaction fee linkage",
  acquisition_cost_basis: "Acquisition cost basis",
};

export default function WalletNativePnlReadinessCard({
  targetRunId,
}: WalletNativePnlReadinessCardProps) {
  const [otherRunIds, setOtherRunIds] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] =
    useState<WalletNativeActivityPnlReadinessResponse | null>(null);
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
        await inspectWalletNativePnlReadiness(targetRunId, parsed.runIds),
      );
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Native activity PnL readiness failed.",
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
            Native activity PnL readiness
          </h2>
          <p>
            Merge and deduplicate verified native TON activities, reconcile the
            selected cash flow, and show exactly what still blocks cost basis.
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
            Other run IDs for native flow reconciliation
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
          {loading ? "Reconciling activity" : "Check PnL readiness"}
        </button>
      </form>

      <PreviewReadinessStrip
        tone={readiness.tone}
        label={readiness.label}
        message={readiness.message}
        items={[
          { label: "Target", value: `Run #${targetRunId}` },
          {
            label: "Canonical activities",
            value: result
              ? String(result.deduplicated_activity_count)
              : "Awaiting selection",
          },
          {
            label: "Suppressed repeats",
            value: result
              ? String(result.suppressed_occurrence_count)
              : "Awaiting selection",
          },
          {
            label: "Net native flow",
            value: result ? `${result.flow_summary.net_ton} TON` : "Unavailable",
          },
        ]}
      />

      {result && (
        <div className="native-pnl-results">
          <div className="native-pnl-flow-grid">
            <FlowMetric
              label="Incoming"
              value={`${result.flow_summary.incoming_ton} TON`}
              detail={`${result.flow_summary.incoming_activity_count} canonical activities`}
            />
            <FlowMetric
              label="Outgoing"
              value={`${result.flow_summary.outgoing_ton} TON`}
              detail={`${result.flow_summary.outgoing_activity_count} canonical activities`}
            />
            <FlowMetric
              label="Self"
              value={`${result.flow_summary.self_ton} TON`}
              detail={`${result.flow_summary.self_activity_count} canonical activities`}
            />
            <FlowMetric
              label="Net observed flow"
              value={`${result.flow_summary.net_ton} TON`}
              detail="Incoming minus outgoing; not profit"
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
  result: WalletNativeActivityPnlReadinessResponse | null;
}): { tone: PreviewReadinessTone; label: string; message: string } {
  if (loading) {
    return {
      tone: "running",
      label: "RECONCILING NATIVE ACTIVITY",
      message: "Revalidating ledgers, merging rows, and resolving repeats.",
    };
  }
  if (error) {
    return { tone: "error", label: "READINESS CHECK FAILED", message: error };
  }
  if (result) {
    return {
      tone: "warning",
      label: "NATIVE FLOW READY · PNL LOCKED",
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
