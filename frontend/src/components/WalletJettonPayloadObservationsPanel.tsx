import { useEffect, useRef, useState } from "react";

import { getWalletTransactionJettonPayloadObservations } from "../api";
import type { WalletJettonPayloadObservationsResponse } from "../types";

interface WalletJettonPayloadObservationsPanelProps {
  runId: number;
  transactionHash: string;
  verificationId: string;
}

type ReadState = "idle" | "loading" | "ready" | "error";

export default function WalletJettonPayloadObservationsPanel({
  runId,
  transactionHash,
  verificationId,
}: WalletJettonPayloadObservationsPanelProps) {
  const [state, setState] = useState<ReadState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] =
    useState<WalletJettonPayloadObservationsResponse | null>(null);
  const controller = useRef<AbortController | null>(null);
  const sequence = useRef(0);

  useEffect(
    () => () => {
      sequence.current += 1;
      controller.current?.abort();
    },
    [],
  );

  async function inspectPayloads() {
    const requestSequence = sequence.current + 1;
    sequence.current = requestSequence;
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    setState("loading");
    setError(null);
    try {
      const response = await getWalletTransactionJettonPayloadObservations(
        runId,
        transactionHash,
        nextController.signal,
      );
      if (
        nextController.signal.aborted ||
        sequence.current !== requestSequence
      ) {
        return;
      }
      if (
        response.run_id !== String(runId) ||
        response.verification_id !== verificationId ||
        response.anchor.transaction_hash !== transactionHash ||
        response.source_message_count !==
          response.recognized_message_count +
            response.unrecognized_message_count ||
        response.recognized_message_count !== response.observations.length ||
        response.message_bodies_returned !== false ||
        response.jetton_master_identity_applied !== false ||
        response.jetton_asset_identity_applied !== false ||
        response.eligible_for_cost_basis !== false ||
        response.used_by_pnl !== false
      ) {
        throw new Error("Jetton payload response contract is incoherent.");
      }
      setResult(response);
      setState("ready");
    } catch (caught) {
      if (
        nextController.signal.aborted ||
        sequence.current !== requestSequence
      ) {
        return;
      }
      setError(
        caught instanceof Error
          ? caught.message
          : "Jetton payload observation read failed.",
      );
      setState("error");
    } finally {
      if (sequence.current === requestSequence) controller.current = null;
    }
  }

  return (
    <section
      className="trace-evidence-results jetton-payload-observations"
      aria-labelledby={`jetton-payload-title-${runId}-${verificationId}`}
    >
      <div className="trace-evidence-result-heading">
        <div>
          <span className="section-eyebrow">Provider-free BOC semantics</span>
          <h3 id={`jetton-payload-title-${runId}-${verificationId}`}>
            TEP-74 jetton payload observations
          </h3>
        </div>
        <div className="trace-evidence-validation-badges">
          <span className="source-badge source-real">LOCAL DECODER</span>
          <span className="source-badge source-mock">BODY HIDDEN</span>
          <span className="source-badge source-mock">ASSET UNRESOLVED</span>
        </div>
      </div>

      <p className="trace-evidence-message">
        Decode recognized TEP-74 layouts from the already verified message
        bodies. This action performs no provider request and never returns body
        contents, assigns a jetton master, or promotes the result into PnL.
      </p>

      <div className="jetton-payload-action-row">
        <button
          className="btn btn-secondary"
          type="button"
          disabled={state === "loading"}
          onClick={inspectPayloads}
        >
          {state === "loading"
            ? "Decoding verified payloads"
            : state === "error"
              ? "Retry TEP-74 decoding"
              : result
                ? "Revalidate TEP-74 payloads"
                : "Decode TEP-74 payloads"}
        </button>
        <span>
          Verification #{verificationId} · query IDs are correlation only
        </span>
      </div>

      {error && (
        <div className="trace-evidence-error" role="alert">
          <strong>Jetton payload decoding failed.</strong>
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="jetton-payload-result">
          <div
            className="trace-evidence-metrics"
            aria-label="TEP-74 payload observation counts"
          >
            <PayloadMetric label="Source messages" value={result.source_message_count} />
            <PayloadMetric label="Recognized" value={result.recognized_message_count} />
            <PayloadMetric label="Unrecognized" value={result.unrecognized_message_count} />
            <PayloadMetric label="Operations" value={result.operations.length} />
          </div>

          {result.observations.length === 0 ? (
            <div className="jetton-payload-empty" role="status">
              No recognized TEP-74 payload exists in this verified capture.
              Unknown opcodes remain counted and no semantics are inferred.
            </div>
          ) : (
            <div className="table-wrap trace-evidence-table-wrap">
              <table className="data-table trace-evidence-table jetton-payload-table">
                <caption>
                  Locally decoded payload coordinates. Message bodies, master
                  addresses, and token metadata remain hidden or unresolved.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Operation</th>
                    <th scope="col">Status</th>
                    <th scope="col">Query ID</th>
                    <th scope="col">Amount, base units</th>
                    <th scope="col">Observed contract role</th>
                    <th scope="col">Message</th>
                  </tr>
                </thead>
                <tbody>
                  {result.observations.map((observation) => (
                    <tr key={observation.payload_observation_identity}>
                      <th scope="row">{operationLabel(observation.operation)}</th>
                      <td>{observation.standard_status}</td>
                      <td className="mono">{observation.query_id}</td>
                      <td className="mono">
                        {observation.amount_base_units ?? "n/a"}
                      </td>
                      <td>{roleLabel(observation.contract_account_role)}</td>
                      <td className="mono">{shortHash(observation.message_hash)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          <p className="muted small jetton-payload-note">
            {result.message} Digest {shortHash(result.payload_observations_digest_sha256)}.
          </p>
        </div>
      )}
    </section>
  );
}

function PayloadMetric({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function operationLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function roleLabel(value: string): string {
  return value.replace(/_/g, " ");
}

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}
