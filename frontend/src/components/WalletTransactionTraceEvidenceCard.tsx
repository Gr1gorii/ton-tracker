import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  getPersistedWalletTransactionTraceEvidence,
  getWalletTransactionTraceBocVerification,
  getWalletTransactionTraceEvidence,
  persistWalletTransactionTraceEvidence,
  verifyWalletTransactionTraceBocs,
} from "../api";
import type {
  WalletPersistedTransactionTraceEvidenceResponse,
  WalletTraceBocVerificationResponse,
  WalletTransactionRecord,
  WalletTransactionTraceEvidenceResponse,
} from "../types";
import {
  eligibleTraceTransactions,
  validatePersistedWalletTransactionTraceEvidenceResponse,
  validateWalletTransactionTraceBocVerificationResponse,
  validateWalletTransactionTraceEvidenceResponse,
  type WalletPersistedTraceEvidenceExpectedAnchor,
  type WalletTraceBocVerificationExpectedAnchor,
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

type PersistedReadState = "idle" | "loading" | "empty" | "ready" | "error";

const FALSE_INVARIANTS = [
  {
    field: "raw_boc_persisted",
    meaning: "Raw BOC bytes are never stored in this evidence record.",
  },
  {
    field: "message_body_persisted",
    meaning: "Message bodies and decoded payloads are never stored.",
  },
  {
    field: "is_blockchain_proof_verified",
    meaning: "Stored provider structure is not locally verified blockchain proof.",
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
    meaning: "Persisted trace evidence cannot establish acquisition cost basis.",
  },
  {
    field: "used_by_pnl",
    meaning:
      "Trace evidence is not passed into a PnL calculation; a separately built native ledger may feed the readiness gate.",
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
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  const [previewResult, setPreviewResult] =
    useState<WalletTransactionTraceEvidenceResponse | null>(null);
  const [persistedReadState, setPersistedReadState] =
    useState<PersistedReadState>("idle");
  const [persistedReadError, setPersistedReadError] = useState<string | null>(
    null,
  );
  const [persistedResult, setPersistedResult] =
    useState<WalletPersistedTransactionTraceEvidenceResponse | null>(null);
  const [captureLoading, setCaptureLoading] = useState(false);
  const [captureError, setCaptureError] = useState<string | null>(null);
  const [bocReadState, setBocReadState] =
    useState<PersistedReadState>("idle");
  const [bocReadError, setBocReadError] = useState<string | null>(null);
  const [bocResult, setBocResult] =
    useState<WalletTraceBocVerificationResponse | null>(null);
  const [bocVerifyLoading, setBocVerifyLoading] = useState(false);
  const [bocVerifyError, setBocVerifyError] = useState<string | null>(null);
  const previewSequence = useRef(0);
  const persistedSequence = useRef(0);
  const bocSequence = useRef(0);
  const previewController = useRef<AbortController | null>(null);
  const persistedController = useRef<AbortController | null>(null);
  const bocController = useRef<AbortController | null>(null);

  const selectedTransaction =
    eligibleTransactions.find(
      (transaction) => transaction.transactionHash === selectedHash,
    ) ?? eligibleTransactions[0] ?? null;
  const scopeKey = traceScopeKey(runId, dataMode, selectedTransaction);
  const activeScopeKey = useRef(scopeKey);
  activeScopeKey.current = scopeKey;
  const visiblePreviewResult =
    previewResult &&
    traceResultMatchesScope(previewResult, runId, selectedTransaction)
      ? previewResult
      : null;
  const visiblePersistedResult =
    persistedResult &&
    persistedResultMatchesScope(persistedResult, runId, selectedTransaction)
      ? persistedResult
      : null;
  const visibleBocResult =
    bocResult &&
    visiblePersistedResult &&
    bocResult.run_id === String(runId) &&
    bocResult.capture_id === visiblePersistedResult.capture_id &&
    bocResult.anchor.transaction_hash === selectedTransaction?.transactionHash
      ? bocResult
      : null;
  const busy =
    previewLoading ||
    persistedReadState === "loading" ||
    captureLoading ||
    bocReadState === "loading" ||
    bocVerifyLoading;
  const canInspect =
    dataMode === "real" &&
    selectedTransaction !== null &&
    !busy;
  const canVerifyBocs =
    dataMode === "real" &&
    selectedTransaction !== null &&
    visiblePersistedResult !== null &&
    bocReadState === "empty" &&
    visibleBocResult === null &&
    !busy;
  const canCapture =
    dataMode === "real" &&
    selectedTransaction !== null &&
    visiblePreviewResult?.trace_state === "finalized" &&
    persistedReadState === "empty" &&
    visiblePersistedResult === null &&
    !busy;
  const titleId = `transaction-trace-evidence-title-${runId}`;
  const selectId = `transaction-trace-evidence-anchor-${runId}`;
  const helpId = `${selectId}-help`;
  const readiness = persistedReadiness({
    dataMode,
    eligibleCount: eligibleTransactions.length,
    readState: persistedReadState,
    readError: persistedReadError,
    captureLoading,
    captureError,
    result: visiblePersistedResult,
  });

  useEffect(() => {
    const nextHash = selectedTransaction?.transactionHash ?? "";
    if (selectedHash === nextHash) return;
    invalidateAllRequests();
    setSelectedHash(nextHash);
    resetScopedState();
  }, [selectedHash, selectedTransaction?.transactionHash]);

  useEffect(() => {
    invalidateAllRequests();
    setPreviewLoading(false);
    setPreviewError(null);
    setPreviewResult(null);
    setPersistedReadError(null);
    setPersistedResult(null);
    setCaptureLoading(false);
    setCaptureError(null);
    setBocReadState("idle");
    setBocReadError(null);
    setBocResult(null);
    setBocVerifyLoading(false);
    setBocVerifyError(null);

    if (dataMode !== "real" || selectedTransaction === null) {
      setPersistedReadState("idle");
      return;
    }

    const expected = expectedAnchor(runId, selectedTransaction);
    void readPersistedEvidence(expected, scopeKey);
  }, [scopeKey]);

  useEffect(
    () => () => {
      invalidateAllRequests();
    },
    [],
  );

  function invalidateAllRequests() {
    previewSequence.current += 1;
    persistedSequence.current += 1;
    bocSequence.current += 1;
    previewController.current?.abort();
    persistedController.current?.abort();
    bocController.current?.abort();
    previewController.current = null;
    persistedController.current = null;
    bocController.current = null;
  }

  function resetScopedState() {
    setPreviewLoading(false);
    setPreviewError(null);
    setPreviewResult(null);
    setPersistedReadState("idle");
    setPersistedReadError(null);
    setPersistedResult(null);
    setCaptureLoading(false);
    setCaptureError(null);
    setBocReadState("idle");
    setBocReadError(null);
    setBocResult(null);
    setBocVerifyLoading(false);
    setBocVerifyError(null);
  }

  async function readPersistedEvidence(
    expected: WalletPersistedTraceEvidenceExpectedAnchor,
    expectedScopeKey: string,
  ) {
    const sequence = persistedSequence.current + 1;
    persistedSequence.current = sequence;
    persistedController.current?.abort();
    const nextController = new AbortController();
    persistedController.current = nextController;
    setPersistedReadState("loading");
    setPersistedReadError(null);
    setCaptureError(null);

    try {
      const response = await getPersistedWalletTransactionTraceEvidence(
        expected.runId,
        expected.transactionHash,
        nextController.signal,
      );
      if (
        nextController.signal.aborted ||
        persistedSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      if (response === null) {
        setPersistedResult(null);
        setPersistedReadState("empty");
        return;
      }
      const validated = validatePersistedWalletTransactionTraceEvidenceResponse(
        response,
        expected,
      );
      if (
        persistedSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setPersistedResult(validated);
      setPersistedReadState("ready");
      void readBocVerification(validated, expectedScopeKey);
    } catch (caught) {
      if (
        nextController.signal.aborted ||
        persistedSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setPersistedReadError(errorMessage(caught, "Unknown saved evidence read error."));
      setPersistedReadState("error");
    } finally {
      if (persistedSequence.current === sequence) {
        persistedController.current = null;
      }
    }
  }

  async function readBocVerification(
    persisted: WalletPersistedTransactionTraceEvidenceResponse,
    expectedScopeKey: string,
  ) {
    const sequence = bocSequence.current + 1;
    bocSequence.current = sequence;
    bocController.current?.abort();
    const nextController = new AbortController();
    bocController.current = nextController;
    setBocReadState("loading");
    setBocReadError(null);
    setBocVerifyError(null);
    const expected = expectedBocAnchor(persisted);
    try {
      const response = await getWalletTransactionTraceBocVerification(
        expected.runId,
        expected.transactionHash,
        nextController.signal,
      );
      if (
        nextController.signal.aborted ||
        bocSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      if (response === null) {
        setBocResult(null);
        setBocReadState("empty");
        return;
      }
      const validated = validateWalletTransactionTraceBocVerificationResponse(
        response,
        expected,
      );
      setBocResult(validated);
      setBocReadState("ready");
    } catch (caught) {
      if (
        nextController.signal.aborted ||
        bocSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setBocReadError(
        errorMessage(caught, "Unknown local transaction BOC read error."),
      );
      setBocReadState("error");
    } finally {
      if (bocSequence.current === sequence) bocController.current = null;
    }
  }

  function handleAnchorChange(nextHash: string) {
    invalidateAllRequests();
    setSelectedHash(nextHash);
    resetScopedState();
  }

  function handleReadRetry() {
    if (dataMode !== "real" || selectedTransaction === null) return;
    void readPersistedEvidence(
      expectedAnchor(runId, selectedTransaction),
      scopeKey,
    );
  }

  function handleBocReadRetry() {
    if (visiblePersistedResult === null) return;
    void readBocVerification(visiblePersistedResult, scopeKey);
  }

  async function handleInspect(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canInspect || selectedTransaction === null) return;

    const sequence = previewSequence.current + 1;
    previewSequence.current = sequence;
    previewController.current?.abort();
    const nextController = new AbortController();
    previewController.current = nextController;
    const expectedScopeKey = scopeKey;
    setPreviewLoading(true);
    setPreviewError(null);

    try {
      const response = await getWalletTransactionTraceEvidence(
        runId,
        selectedTransaction.transactionHash,
        nextController.signal,
      );
      const validated = validateWalletTransactionTraceEvidenceResponse(response, {
        runId,
        transactionHash: selectedTransaction.transactionHash,
        logicalTime: selectedTransaction.logicalTime,
        accountCanonical: selectedTransaction.accountCanonical,
      });
      if (
        previewSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setPreviewResult(validated);
    } catch (caught) {
      if (
        nextController.signal.aborted ||
        previewSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setPreviewError(errorMessage(caught, "Unknown transaction trace preview error."));
    } finally {
      if (previewSequence.current === sequence) {
        previewController.current = null;
        setPreviewLoading(false);
      }
    }
  }

  async function handleCapture() {
    if (!canCapture || selectedTransaction === null) return;

    const sequence = persistedSequence.current + 1;
    persistedSequence.current = sequence;
    persistedController.current?.abort();
    const nextController = new AbortController();
    persistedController.current = nextController;
    const expectedScopeKey = scopeKey;
    const expected = expectedAnchor(runId, selectedTransaction);
    setCaptureLoading(true);
    setCaptureError(null);

    try {
      const response = await persistWalletTransactionTraceEvidence(
        runId,
        selectedTransaction.transactionHash,
        nextController.signal,
      );
      const validated = validatePersistedWalletTransactionTraceEvidenceResponse(
        response,
        expected,
      );
      if (
        persistedSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setPersistedResult(validated);
      setPersistedReadState("ready");
      void readBocVerification(validated, expectedScopeKey);
    } catch (caught) {
      if (
        nextController.signal.aborted ||
        persistedSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setCaptureError(errorMessage(caught, "Unknown trace evidence capture error."));
    } finally {
      if (persistedSequence.current === sequence) {
        persistedController.current = null;
        setCaptureLoading(false);
      }
    }
  }

  async function handleVerifyBocs() {
    if (
      !canVerifyBocs ||
      selectedTransaction === null ||
      visiblePersistedResult === null
    ) {
      return;
    }
    const sequence = bocSequence.current + 1;
    bocSequence.current = sequence;
    bocController.current?.abort();
    const nextController = new AbortController();
    bocController.current = nextController;
    const expectedScopeKey = scopeKey;
    const expected = expectedBocAnchor(visiblePersistedResult);
    setBocVerifyLoading(true);
    setBocVerifyError(null);
    try {
      const response = await verifyWalletTransactionTraceBocs(
        runId,
        selectedTransaction.transactionHash,
        nextController.signal,
      );
      const validated = validateWalletTransactionTraceBocVerificationResponse(
        response,
        expected,
      );
      if (
        nextController.signal.aborted ||
        bocSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setBocResult(validated);
      setBocReadState("ready");
    } catch (caught) {
      if (
        nextController.signal.aborted ||
        bocSequence.current !== sequence ||
        activeScopeKey.current !== expectedScopeKey
      ) {
        return;
      }
      setBocVerifyError(
        errorMessage(caught, "Unknown local transaction BOC verification error."),
      );
    } finally {
      if (bocSequence.current === sequence) {
        bocController.current = null;
        setBocVerifyLoading(false);
      }
    }
  }

  return (
    <section
      className="intelligence-table-block trace-evidence-card"
      aria-labelledby={titleId}
      aria-busy={busy}
    >
      <div className="table-toolbar trace-evidence-toolbar">
        <div className="table-toolbar-main">
          <span className="section-eyebrow">Persisted low-level trace evidence</span>
          <h2 id={titleId}>Transaction trace evidence</h2>
          <p>
            Saved evidence is read automatically from local storage without a
            provider call. Live preview and immutable capture remain separate,
            explicit actions. Only a separately built and fully revalidated
            native ledger can feed the multi-run readiness gate, never a PnL
            calculation by itself.
          </p>
        </div>
        <div className="table-meta" aria-label="Permanent trace limitations">
          <span className="badge badge-mock">STORED ≠ VERIFIED</span>
          <span className="badge badge-mock">LOCAL BOC ≠ CHAIN PROOF</span>
          <span className="badge badge-mock">NON-AUTHORITATIVE</span>
          <span className="badge badge-mock">NOT PNL</span>
          <span className="badge badge-mock">NO OWNERSHIP PROOF</span>
        </div>
      </div>

      <div className="trace-evidence-safety" role="note">
        <strong>Local BOC verification is not a chain inclusion proof.</strong>
        <span>
          The optional local pass reparses every transaction BOC and checks cell
          hashes, bounded headers, message edges and body hashes. It does not
          prove chain state, reconstruct semantics, ownership, or cost basis.
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
            disabled={dataMode !== "real" || eligibleTransactions.length === 0}
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
        <div className="trace-evidence-actions">
          <button className="btn btn-primary" type="submit" disabled={!canInspect}>
            {previewLoading
              ? "Reading live trace preview"
              : previewError
                ? "Retry live trace preview"
                : previewResult
                  ? "Refresh live trace preview"
                  : "Preview live trace"}
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            disabled={!canCapture}
            onClick={handleCapture}
          >
            {captureButtonLabel({
              captureLoading,
              persistedResult: visiblePersistedResult,
              previewResult: visiblePreviewResult,
              readState: persistedReadState,
            })}
          </button>
          <button
            className="btn btn-secondary"
            type="button"
            disabled={!canVerifyBocs}
            onClick={handleVerifyBocs}
          >
            {bocVerifyLoading
              ? "Verifying transaction BOCs"
              : visibleBocResult
                ? "Transaction BOCs verified"
                : bocReadState === "loading"
                  ? "Checking local BOC record"
                  : "Verify transaction BOCs"}
          </button>
        </div>
      </form>

      <PreviewReadinessStrip
        tone={readiness.tone}
        label={readiness.label}
        message={readiness.message}
        items={[
          { label: "Run", value: `#${runId}` },
          {
            label: "Saved record",
            value: visiblePersistedResult
              ? `#${visiblePersistedResult.capture_id}`
              : savedStateLabel(persistedReadState),
          },
          { label: "Provider actions", value: "Manual only" },
        ]}
      />

      {persistedReadError && (
        <div className="trace-evidence-error" role="alert">
          <strong>Saved trace evidence read failed.</strong>
          <span>{persistedReadError}</span>
          <button className="btn btn-secondary" type="button" onClick={handleReadRetry}>
            Retry saved evidence read
          </button>
        </div>
      )}

      {captureError && (
        <div className="trace-evidence-error" role="alert">
          <strong>Trace evidence was not saved.</strong>
          <span>{captureError}</span>
          {visiblePersistedResult && (
            <small>The last confirmed immutable record remains visible.</small>
          )}
        </div>
      )}

      {bocReadError && (
        <div className="trace-evidence-error" role="alert">
          <strong>Local BOC verification read failed.</strong>
          <span>{bocReadError}</span>
          <button className="btn btn-secondary" type="button" onClick={handleBocReadRetry}>
            Retry local BOC read
          </button>
        </div>
      )}

      {bocVerifyError && (
        <div className="trace-evidence-error" role="alert">
          <strong>Transaction BOCs were not verified.</strong>
          <span>{bocVerifyError}</span>
          {visiblePersistedResult && (
            <small>The saved trace graph remains unchanged.</small>
          )}
        </div>
      )}

      {visiblePersistedResult && (
        <PersistedTraceEvidenceResult result={visiblePersistedResult} />
      )}

      {visibleBocResult && (
        <BocVerificationResult result={visibleBocResult} />
      )}

      {previewLoading && (
        <div className="trace-evidence-operation-status" role="status">
          Reading one provider-indexed preview. Nothing is stored by this action.
        </div>
      )}

      {previewError && (
        <div className="trace-evidence-error" role="alert">
          <strong>Live trace preview failed.</strong>
          <span>{previewError}</span>
          {visiblePreviewResult && (
            <small>The last live preview remains visible.</small>
          )}
          {visiblePersistedResult && (
            <small>The saved immutable record is unchanged.</small>
          )}
        </div>
      )}

      {visiblePreviewResult && (
        <TraceEvidencePreviewResult result={visiblePreviewResult} />
      )}

      <TraceInvariantTable />
    </section>
  );
}

function PersistedTraceEvidenceResult({
  result,
}: {
  result: WalletPersistedTransactionTraceEvidenceResponse;
}) {
  const summary = result.summary;
  return (
    <div className="trace-evidence-results trace-evidence-persisted-results">
      <div className="trace-evidence-result-heading">
        <div>
          <span className="section-eyebrow">Saved immutable evidence record</span>
          <h3>Finalized at capture</h3>
        </div>
        <div className="trace-evidence-validation-badges">
          <span className="source-badge source-real">PROVIDER STRUCTURE VALIDATED</span>
          <span className="source-badge source-real">LOCAL GRAPH REVALIDATED</span>
          <span className="source-badge source-real">IMMUTABLE RECORD</span>
        </div>
      </div>

      <div className="trace-evidence-contract-strip trace-evidence-persisted-strip">
        <div>
          <span>Contract</span>
          <strong>{result.contract_version}</strong>
        </div>
        <div>
          <span>Capture ID</span>
          <strong>#{result.capture_id}</strong>
        </div>
        <div>
          <span>Trace state</span>
          <strong><span className="source-badge source-real">FINALIZED AT CAPTURE</span></strong>
        </div>
        <div>
          <span>Captured</span>
          <strong><time dateTime={result.captured_at}>{result.captured_at}</time></strong>
        </div>
      </div>

      <p className="trace-evidence-message">{result.message}</p>

      <div className="trace-evidence-metrics" aria-label="Persisted trace graph counts">
        <TraceMetric label="Transactions" value={summary.transaction_count} />
        <TraceMetric label="Messages" value={summary.message_count} />
        <TraceMetric label="Unique accounts" value={summary.unique_account_count} />
        <TraceMetric label="Maximum depth" value={summary.max_depth} />
        <TraceMetric label="Remaining out" value={summary.remaining_out_message_count} />
        <TraceMetric label="Successful" value={summary.successful_transaction_count} />
        <TraceMetric label="Failed" value={summary.failed_transaction_count} />
        <TraceMetric label="Aborted" value={summary.aborted_transaction_count} />
      </div>

      <details className="trace-evidence-details">
        <summary>
          <span>Stored anchor, message graph, and evidence digest</span>
          <span>REVALIDATED</span>
        </summary>
        <div className="table-wrap trace-evidence-table-wrap">
          <table className="data-table trace-evidence-table">
            <caption>
              Sanitized immutable trace evidence for stored run #{result.run_id} on {result.network}.
            </caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Stored value</th>
              </tr>
            </thead>
            <tbody>
              <TraceDetailRow label="Transaction hash" value={result.anchor.transaction_hash} mono />
              <TraceDetailRow label="Logical time" value={result.anchor.logical_time} mono />
              <TraceDetailRow label="Canonical account" value={result.anchor.account_canonical} mono />
              <TraceDetailRow label="Trace root hash" value={summary.root_transaction_hash} mono />
              <TraceDetailRow label="Evidence SHA-256" value={result.evidence_digest_sha256} mono />
              <TraceDetailRow label="Root inbound messages" value={String(summary.root_inbound_message_count)} />
              <TraceDetailRow label="Child internal messages" value={String(summary.child_internal_message_count)} />
              <TraceDetailRow label="Remaining outbound messages" value={String(summary.remaining_out_message_count)} />
              <TraceDetailRow label="Internal messages" value={String(summary.internal_message_count)} />
              <TraceDetailRow label="External-in messages" value={String(summary.external_in_message_count)} />
              <TraceDetailRow label="External-out messages" value={String(summary.external_out_message_count)} />
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function BocVerificationResult({
  result,
}: {
  result: WalletTraceBocVerificationResponse;
}) {
  const summary = result.summary;
  return (
    <div className="trace-evidence-results trace-evidence-boc-results">
      <div className="trace-evidence-result-heading">
        <div>
          <span className="section-eyebrow">Local BOC verification record</span>
          <h3>Transaction cells and messages matched</h3>
        </div>
        <div className="trace-evidence-validation-badges">
          <span className="source-badge source-real">BOCS DESERIALIZED</span>
          <span className="source-badge source-real">CELL HASHES MATCHED</span>
          <span className="source-badge source-real">MESSAGE EDGES MATCHED</span>
        </div>
      </div>

      <div className="trace-evidence-contract-strip trace-evidence-persisted-strip">
        <div><span>Contract</span><strong>{result.contract_version}</strong></div>
        <div><span>Verification ID</span><strong>#{result.verification_id}</strong></div>
        <div><span>Verifier</span><strong>{result.verifier.name} {result.verifier.version}</strong></div>
        <div><span>Verified</span><strong><time dateTime={result.verified_at}>{result.verified_at}</time></strong></div>
      </div>

      <p className="trace-evidence-message">{result.message}</p>
      <div className="trace-evidence-metrics" aria-label="Local BOC verification counts">
        <TraceMetric label="Transactions" value={summary.transaction_count} />
        <TraceMetric label="Messages" value={summary.message_count} />
        <TraceMetric label="BOC bytes" value={summary.total_boc_bytes} />
        <TraceMetric label="Body hashes" value={summary.body_hash_count} />
        <TraceMetric label="32-bit opcodes" value={summary.opcode_count} />
        <TraceMetric label="Normalized ext-in" value={summary.normalized_external_in_hash_count} />
      </div>

      <details className="trace-evidence-details">
        <summary>
          <span>Per-transaction local verification digests</span>
          <span>RAW BOC HIDDEN</span>
        </summary>
        <div className="table-wrap trace-evidence-table-wrap">
          <table className="data-table trace-evidence-table">
            <caption>
              Locally reparsed transaction cells for capture #{result.capture_id};
              raw BOCs and message bodies are intentionally not returned.
            </caption>
            <thead>
              <tr>
                <th scope="col">Preorder</th>
                <th scope="col">Transaction hash</th>
                <th scope="col">BOC bytes</th>
                <th scope="col">Messages</th>
                <th scope="col">Body hashes</th>
                <th scope="col">Evidence SHA-256</th>
              </tr>
            </thead>
            <tbody>
              {result.transactions.map((transaction) => (
                <tr key={transaction.preorder_index}>
                  <th scope="row">{transaction.preorder_index}</th>
                  <td className="mono">{transaction.transaction_hash}</td>
                  <td>{transaction.transaction_boc_bytes}</td>
                  <td>{transaction.message_count}</td>
                  <td>{transaction.body_hash_count}</td>
                  <td className="mono">{transaction.message_evidence_digest_sha256}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  );
}

function TraceEvidencePreviewResult({
  result,
}: {
  result: WalletTransactionTraceEvidenceResponse;
}) {
  const summary = result.summary;
  return (
    <div className="trace-evidence-results trace-evidence-preview-results">
      <div className="trace-evidence-result-heading">
        <div>
          <span className="section-eyebrow">Live provider preview · not stored</span>
          <h3>{result.trace_state === "finalized" ? "Finalized preview" : "Pending preview"}</h3>
        </div>
      </div>
      <div className="trace-evidence-contract-strip">
        <div>
          <span>Contract</span>
          <strong>{result.contract_version}</strong>
        </div>
        <div>
          <span>Trace state</span>
          <strong>
            <span className={`source-badge ${result.trace_state === "finalized" ? "source-real" : "source-mock"}`}>
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

      <div className="trace-evidence-metrics" aria-label="Trace preview summary counts">
        <TraceMetric label="Transactions" value={summary.transaction_count} />
        <TraceMetric label="Unique accounts" value={summary.unique_account_count} />
        <TraceMetric label="Maximum depth" value={summary.max_depth} />
        <TraceMetric label="Out messages" value={summary.out_message_count} />
        <TraceMetric label="Pending internal" value={summary.pending_internal_message_count} />
        <TraceMetric label="Successful" value={summary.successful_transaction_count} />
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
            <caption>Exact provider-indexed preview anchor for stored run #{result.run_id}.</caption>
            <thead>
              <tr>
                <th scope="col">Field</th>
                <th scope="col">Sanitized value</th>
              </tr>
            </thead>
            <tbody>
              <TraceDetailRow label="Stored transaction hash" value={result.anchor.transaction_hash} mono />
              <TraceDetailRow label="Stored logical time" value={result.anchor.logical_time} mono />
              <TraceDetailRow label="Stored canonical account" value={result.anchor.account_canonical} mono />
              <TraceDetailRow label="Provider trace root hash" value={summary.root_transaction_hash} mono />
              <TraceDetailRow label="Matches stored transaction" value="TRUE" />
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
          Permanent safety invariants. Preview, persistence, and local graph
          revalidation can never change these v0.23.1 values.
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
              <th scope="row"><code>{invariant.field}</code></th>
              <td><span className="source-badge source-mock">FALSE</span></td>
              <td>{invariant.meaning}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TraceMetric({ label, value }: { label: string; value: number }) {
  return <div><span>{label}</span><strong>{value}</strong></div>;
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
  return <tr><th scope="row">{label}</th><td className={mono ? "mono" : undefined}>{value}</td></tr>;
}

function persistedReadiness({
  dataMode,
  eligibleCount,
  readState,
  readError,
  captureLoading,
  captureError,
  result,
}: {
  dataMode: "mock" | "real";
  eligibleCount: number;
  readState: PersistedReadState;
  readError: string | null;
  captureLoading: boolean;
  captureError: string | null;
  result: WalletPersistedTransactionTraceEvidenceResponse | null;
}): { tone: PreviewReadinessTone; label: string; message: string } {
  if (dataMode === "mock") {
    return { tone: "warning", label: "REAL STORED RUN REQUIRED", message: "Mock runs never read, capture, or persist transaction trace evidence." };
  }
  if (eligibleCount === 0) {
    return { tone: "warning", label: "NO ELIGIBLE TRACE ANCHOR", message: "No coherent live TonAPI transaction identity can be inspected or captured." };
  }
  if (captureLoading) {
    return { tone: "running", label: "CAPTURING AND SAVING", message: "One explicit provider capture is being validated and committed as an immutable record." };
  }
  if (readState === "loading" || readState === "idle") {
    return { tone: "running", label: "READING SAVED EVIDENCE", message: "Checking local storage only. No provider request is made by this readback." };
  }
  if (readError) {
    return { tone: "warning", label: "SAVED EVIDENCE READ FAILED", message: "Stored state is unknown. Retry the database-only read before capture." };
  }
  if (captureError) {
    return result
      ? { tone: "warning", label: "LAST SAVED RECORD PRESERVED", message: "The capture failed; the prior immutable record remains unchanged." }
      : { tone: "warning", label: "EVIDENCE NOT SAVED", message: "The explicit capture failed. No immutable record was accepted." };
  }
  if (result) {
    return { tone: "ready", label: "SAVED IMMUTABLE TRACE EVIDENCE", message: "The finalized-at-capture graph passed local contract revalidation. All authority and PnL flags remain false." };
  }
  return { tone: "ready", label: "NO SAVED TRACE EVIDENCE", message: "The database read completed. Preview first, then explicitly capture only a finalized provider trace." };
}

function captureButtonLabel({
  captureLoading,
  persistedResult,
  previewResult,
  readState,
}: {
  captureLoading: boolean;
  persistedResult: WalletPersistedTransactionTraceEvidenceResponse | null;
  previewResult: WalletTransactionTraceEvidenceResponse | null;
  readState: PersistedReadState;
}): string {
  if (captureLoading) return "Capturing and saving evidence";
  if (persistedResult) return "Immutable evidence saved";
  if (readState === "loading" || readState === "idle") return "Checking saved evidence";
  if (readState === "error") return "Saved state unavailable";
  if (!previewResult) return "Preview finalized trace to save";
  if (previewResult.trace_state === "pending") return "Finalized trace required to save";
  return "Capture and store evidence";
}

function savedStateLabel(readState: PersistedReadState): string {
  if (readState === "loading" || readState === "idle") return "Checking";
  if (readState === "empty") return "None";
  if (readState === "error") return "Unavailable";
  return "Available";
}

function traceSelectionHelp(
  dataMode: "mock" | "real",
  transactionCount: number,
  eligibleCount: number,
): string {
  if (dataMode === "mock") return "Mock mode is non-networked here; both provider actions stay disabled.";
  if (transactionCount === 0) return "This run contains no stored low-level transaction rows.";
  if (eligibleCount === 0) return "Stored rows lack a coherent live TonAPI network + account + LT + hash anchor.";
  return `${eligibleCount} of ${transactionCount} stored transactions can be selected. Saved evidence is read locally; provider actions remain explicit.`;
}

function expectedAnchor(
  runId: number,
  transaction: WalletTraceEligibleTransaction,
): WalletPersistedTraceEvidenceExpectedAnchor {
  return {
    runId,
    transactionHash: transaction.transactionHash,
    logicalTime: transaction.logicalTime,
    accountCanonical: transaction.accountCanonical,
    network: transaction.network,
  };
}

function expectedBocAnchor(
  persisted: WalletPersistedTransactionTraceEvidenceResponse,
): WalletTraceBocVerificationExpectedAnchor {
  return {
    runId: Number(persisted.run_id),
    transactionHash: persisted.anchor.transaction_hash,
    logicalTime: persisted.anchor.logical_time,
    accountCanonical: persisted.anchor.account_canonical,
    network: persisted.network,
    captureId: persisted.capture_id,
    captureEvidenceDigest: persisted.evidence_digest_sha256,
    transactionCount: persisted.summary.transaction_count,
    messageCount: persisted.summary.message_count,
  };
}

function traceScopeKey(
  runId: number,
  dataMode: "mock" | "real",
  transaction: WalletTraceEligibleTransaction | null,
): string {
  if (transaction === null) return `${runId}|${dataMode}|none`;
  return [runId, dataMode, transaction.network, transaction.accountCanonical, transaction.logicalTime, transaction.transactionHash].join("|");
}

function traceResultMatchesScope(
  result: {
    run_id: string;
    anchor: {
      transaction_hash: string;
      logical_time: string;
      account_canonical: string;
    };
  },
  runId: number,
  transaction: WalletTraceEligibleTransaction | null,
): boolean {
  return (
    transaction !== null &&
    result.run_id === String(runId) &&
    result.anchor.transaction_hash === transaction.transactionHash &&
    result.anchor.logical_time === transaction.logicalTime &&
    result.anchor.account_canonical === transaction.accountCanonical
  );
}

function persistedResultMatchesScope(
  result: WalletPersistedTransactionTraceEvidenceResponse,
  runId: number,
  transaction: WalletTraceEligibleTransaction | null,
): boolean {
  return (
    traceResultMatchesScope(result, runId, transaction) &&
    transaction !== null &&
    result.network === transaction.network
  );
}

function errorMessage(caught: unknown, fallback: string): string {
  return caught instanceof Error ? caught.message : fallback;
}

function shortHash(value: string): string {
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}
