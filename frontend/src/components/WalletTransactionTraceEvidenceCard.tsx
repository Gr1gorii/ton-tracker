import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import { getWalletTransactionTraceEvidence } from "../api";
import type {
  WalletTransactionRecord,
  WalletTransactionTraceEvidenceResponse,
} from "../types";
import {
  eligibleTraceTransactions,
  validateWalletTransactionTraceEvidenceResponse,
  type WalletTraceEligibleTransaction,
} from "../walletTraceEvidence";
import PreviewReadinessStrip, {
  type PreviewReadinessTone,
} from "./PreviewReadinessStrip";

interface WalletTransactionTraceEvidenceCardProps {
  runId: number;
  dataMode: "mock" | "real";
  transactions: WalletTransactionRecord[];
}

const FALSE_INVARIANTS = [
  {
    field: "is_blockchain_proof_verified",
    meaning: "The provider response is not a locally verified blockchain proof.",
  },
  {
    field: "is_authoritative_activity_identity",
    meaning: "A matching trace anchor is not authoritative activity identity.",
  },
  {
    field: "semantic_reconstruction_applied",
    meaning: "No transfer or swap semantics are reconstructed.",
  },
  {
    field: "activity_merge_applied",
    meaning: "No activity rows are merged.",
  },
  {
    field: "deduplication_applied",
    meaning: "No row or activity deduplication is applied.",
  },
  {
    field: "eligible_for_cost_basis",
    meaning: "This preview cannot establish acquisition cost basis.",
  },
  {
    field: "used_by_pnl",
    meaning: "Trace evidence is not passed into PnL.",
  },
  {
    field: "is_ownership_proof",
    meaning: "A transaction trace never proves wallet ownership or intent.",
  },
] as const;

export default function WalletTransactionTraceEvidenceCard({
  runId,
  dataMode,
  transactions,
}: WalletTransactionTraceEvidenceCardProps) {
  const eligibleTransactions = useMemo(
    () => eligibleTraceTransactions(transactions),
    [transactions],
  );
  const [selectedHash, setSelectedHash] = useState(
    () => eligibleTransactions[0]?.transactionHash ?? "",
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] =
    useState<WalletTransactionTraceEvidenceResponse | null>(null);
  const requestSequence = useRef(0);
  const controller = useRef<AbortController | null>(null);

  const selectedTransaction =
    eligibleTransactions.find(
      (transaction) => transaction.transactionHash === selectedHash,
    ) ?? eligibleTransactions[0] ?? null;
  const canInspect =
    dataMode === "real" && selectedTransaction !== null && !loading;
  const titleId = `transaction-trace-evidence-title-${runId}`;
  const selectId = `transaction-trace-evidence-anchor-${runId}`;
  const helpId = `${selectId}-help`;
  const readiness = traceReadiness({
    dataMode,
    eligibleCount: eligibleTransactions.length,
    loading,
    error,
    result,
  });

  useEffect(() => {
    const nextHash = selectedTransaction?.transactionHash ?? "";
    if (selectedHash === nextHash) return;
    invalidateRequest();
    setSelectedHash(nextHash);
    setError(null);
    setResult(null);
  }, [selectedHash, selectedTransaction?.transactionHash]);

  useEffect(
    () => () => {
      requestSequence.current += 1;
      controller.current?.abort();
    },
    [],
  );

  function invalidateRequest() {
    requestSequence.current += 1;
    controller.current?.abort();
    controller.current = null;
    setLoading(false);
  }

  function handleAnchorChange(nextHash: string) {
    invalidateRequest();
    setSelectedHash(nextHash);
    setError(null);
    setResult(null);
  }

  async function handleInspect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (dataMode !== "real" || selectedTransaction === null) return;

    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setLoading(true);
    setError(null);

    try {
      const response = await getWalletTransactionTraceEvidence(
        runId,
        selectedTransaction.transactionHash,
        nextController.signal,
      );
      const validated = validateWalletTransactionTraceEvidenceResponse(
        response,
        {
          runId,
          transactionHash: selectedTransaction.transactionHash,
          logicalTime: selectedTransaction.logicalTime,
          accountCanonical: selectedTransaction.accountCanonical,
        },
      );
      if (requestSequence.current !== sequence) return;
      setResult(validated);
    } catch (caught) {
      if (
        nextController.signal.aborted ||
        requestSequence.current !== sequence
      ) {
        return;
      }
      setError(
        caught instanceof Error
          ? caught.message
          : "Unknown transaction trace evidence error.",
      );
    } finally {
      if (requestSequence.current === sequence) {
        controller.current = null;
        setLoading(false);
      }
    }
  }

  return (
    <section
      className="intelligence-table-block trace-evidence-card"
      aria-labelledby={titleId}
      aria-busy={loading}
    >
      <div className="table-toolbar trace-evidence-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Explicit provider preview</span>
          <h2 id={titleId}>Transaction trace evidence</h2>
          <p>
            Choose one stored low-level transaction from run #{runId}, then
            explicitly request a provider-indexed trace summary. Nothing is
            fetched automatically, persisted, merged, reconstructed, or sent to
            PnL.
          </p>
        </div>
        <div className="table-meta" aria-label="Permanent trace limitations">
          <span className="badge badge-mock">NON-AUTHORITATIVE</span>
          <span className="badge badge-mock">NOT PNL</span>
          <span className="badge badge-mock">NO OWNERSHIP PROOF</span>
        </div>
      </div>

      <div className="trace-evidence-safety" role="note">
        <strong>Trace match is provider evidence only.</strong>
        <span>
          Even an exact stored-anchor match does not prove chain state locally,
          reconstruct transfer or swap semantics, establish full history, or
          authorize cost-basis use.
        </span>
      </div>

      <form className="trace-evidence-form" onSubmit={handleInspect}>
        <div className="field">
          <label className="field-label" htmlFor={selectId}>
            Stored transaction anchor
          </label>
          <select
            id={selectId}
            className="text-input"
            value={selectedTransaction?.transactionHash ?? ""}
            disabled={
              dataMode !== "real" || eligibleTransactions.length === 0
            }
            aria-describedby={helpId}
            onChange={(event) => handleAnchorChange(event.target.value)}
          >
            {eligibleTransactions.length === 0 ? (
              <option value="">No eligible live transaction anchor</option>
            ) : (
              eligibleTransactions.map((transaction) => (
                <option
                  key={transaction.transactionHash}
                  value={transaction.transactionHash}
                >
                  {shortHash(transaction.transactionHash)} · LT {transaction.logicalTime}
                </option>
              ))
            )}
          </select>
          <small id={helpId} className="trace-evidence-help">
            {traceSelectionHelp(
              dataMode,
              transactions.length,
              eligibleTransactions.length,
            )}
          </small>
          {selectedTransaction && dataMode === "real" && (
            <code className="trace-evidence-selected-hash">
              {selectedTransaction.transactionHash}
            </code>
          )}
        </div>
        <button className="btn btn-primary" type="submit" disabled={!canInspect}>
          {loading
            ? "Inspecting trace evidence"
            : error
              ? "Retry trace evidence"
              : result
                ? "Inspect again"
                : "Inspect trace evidence"}
        </button>
      </form>

      <PreviewReadinessStrip
        tone={readiness.tone}
        label={readiness.label}
        message={readiness.message}
        items={[
          { label: "Run", value: `#${runId}` },
          {
            label: "Eligible anchors",
            value: `${eligibleTransactions.length}/${transactions.length}`,
          },
          { label: "Provider read", value: "Manual only" },
        ]}
      />

      {error && (
        <div className="trace-evidence-error" role="alert">
          <strong>Trace evidence preview failed.</strong>
          <span>{error}</span>
          {result && <small>The last successful result remains visible.</small>}
        </div>
      )}

      {result && <TraceEvidenceResult result={result} />}

      <TraceInvariantTable />
    </section>
  );
}

function TraceEvidenceResult({
  result,
}: {
  result: WalletTransactionTraceEvidenceResponse;
}) {
  const summary = result.summary;
  return (
    <div className="trace-evidence-results">
      <div className="trace-evidence-contract-strip" role="status">
        <div>
          <span>Contract</span>
          <strong>{result.contract_version}</strong>
        </div>
        <div>
          <span>Trace state</span>
          <strong>
            <span
              className={`source-badge ${
                result.trace_state === "finalized"
                  ? "source-real"
                  : "source-mock"
              }`}
            >
              {result.trace_state.toUpperCase()}
            </span>
          </strong>
        </div>
        <div>
          <span>Source</span>
          <strong>{result.provider} · {result.source_status}</strong>
        </div>
      </div>

      <p className="trace-evidence-message">{result.message}</p>

      <div className="trace-evidence-metrics" aria-label="Trace summary counts">
        <TraceMetric label="Transactions" value={summary.transaction_count} />
        <TraceMetric label="Unique accounts" value={summary.unique_account_count} />
        <TraceMetric label="Maximum depth" value={summary.max_depth} />
        <TraceMetric label="Out messages" value={summary.out_message_count} />
        <TraceMetric
          label="Pending internal"
          value={summary.pending_internal_message_count}
        />
        <TraceMetric
          label="Successful"
          value={summary.successful_transaction_count}
        />
        <TraceMetric label="Failed" value={summary.failed_transaction_count} />
        <TraceMetric label="Aborted" value={summary.aborted_transaction_count} />
      </div>

      <details className="trace-evidence-details">
        <summary>
          <span>Exact stored anchor and provider trace root</span>
          <span>{result.anchor.matches_stored_transaction ? "MATCHED" : "UNMATCHED"}</span>
        </summary>
        <div className="table-wrap trace-evidence-table-wrap">
          <table className="data-table trace-evidence-table">
            <caption>
              Exact provider-indexed trace anchor for stored run #{result.run_id}.
            </caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Sanitized value</th>
              </tr>
            </thead>
            <tbody>
              <TraceDetailRow
                label="Stored transaction hash"
                value={result.anchor.transaction_hash}
                mono
              />
              <TraceDetailRow
                label="Stored logical time"
                value={result.anchor.logical_time}
                mono
              />
              <TraceDetailRow
                label="Stored canonical account"
                value={result.anchor.account_canonical}
                mono
              />
              <TraceDetailRow
                label="Provider trace root hash"
                value={summary.root_transaction_hash}
                mono
              />
              <TraceDetailRow
                label="Matches stored transaction"
                value="TRUE"
              />
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function TraceInvariantTable() {
  return (
    <div className="table-wrap trace-invariant-table-wrap">
      <table className="data-table trace-invariant-table">
        <caption>
          Permanent safety invariants. Counts and a matching provider trace can
          never change these v0.23.0 values.
        </caption>
        <thead>
          <tr>
            <th scope="col">Contract flag</th>
            <th scope="col">Value</th>
            <th scope="col">Meaning</th>
          </tr>
        </thead>
        <tbody>
          {FALSE_INVARIANTS.map((invariant) => (
            <tr key={invariant.field}>
              <th scope="row">
                <code>{invariant.field}</code>
              </th>
              <td>
                <span className="source-badge source-mock">FALSE</span>
              </td>
              <td>{invariant.meaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TraceMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TraceDetailRow({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <tr>
      <th scope="row">{label}</th>
      <td className={mono ? "mono" : undefined}>{value}</td>
    </tr>
  );
}

function traceReadiness({
  dataMode,
  eligibleCount,
  loading,
  error,
  result,
}: {
  dataMode: "mock" | "real";
  eligibleCount: number;
  loading: boolean;
  error: string | null;
  result: WalletTransactionTraceEvidenceResponse | null;
}): { tone: PreviewReadinessTone; label: string; message: string } {
  if (dataMode === "mock") {
    return {
      tone: "warning",
      label: "REAL STORED RUN REQUIRED",
      message: "Mock runs never trigger a transaction trace provider request.",
    };
  }
  if (eligibleCount === 0) {
    return {
      tone: "warning",
      label: "NO ELIGIBLE TRACE ANCHOR",
      message: "No coherent live TonAPI transaction identity can be inspected.",
    };
  }
  if (loading) {
    return {
      tone: "running",
      label: result ? "REFRESHING TRACE EVIDENCE" : "INSPECTING TRACE EVIDENCE",
      message: result
        ? "The last successful response remains visible during this explicit refresh."
        : "Reading one provider-indexed trace summary without persistence.",
    };
  }
  if (error) {
    return {
      tone: "warning",
      label: result ? "LAST TRACE RESULT PRESERVED" : "TRACE RESULT UNAVAILABLE",
      message: result
        ? "The explicit retry failed; the prior successful result remains scoped to this anchor."
        : "The explicit provider request failed and produced no trace result.",
    };
  }
  if (result) {
    return {
      tone: result.trace_state === "finalized" ? "fresh" : "warning",
      label:
        result.trace_state === "finalized"
          ? "FINALIZED PROVIDER TRACE"
          : "PENDING PROVIDER TRACE",
      message:
        result.trace_state === "finalized"
          ? "The sanitized provider trace matches this stored transaction anchor. Safety flags remain false."
          : "The provider trace still has pending internal messages. Safety flags remain false.",
    };
  }
  return {
    tone: "ready",
    label: "EXPLICIT REQUEST REQUIRED",
    message: "No trace request has been sent. Choose an anchor and inspect it manually.",
  };
}

function traceSelectionHelp(
  dataMode: "mock" | "real",
  transactionCount: number,
  eligibleCount: number,
): string {
  if (dataMode === "mock") {
    return "Mock mode is non-networked here; the inspect action stays disabled.";
  }
  if (transactionCount === 0) {
    return "This run contains no stored low-level transaction rows.";
  }
  if (eligibleCount === 0) {
    return "Stored rows lack a coherent live TonAPI account + LT + hash anchor.";
  }
  return `${eligibleCount} of ${transactionCount} stored transactions can be selected. No request is sent until Inspect.`;
}

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}
