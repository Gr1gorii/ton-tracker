import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  CheckCircle,
  Cube,
  Fingerprint,
  SpinnerGap,
  WarningCircle,
} from "@phosphor-icons/react";

import {
  getPersistedWalletTransactionTraceEvidence,
  getWalletTransactionInclusionProofs,
  getWalletTransactionTraceBocVerification,
  persistWalletTransactionTraceEvidence,
  proveWalletTransactionInclusion,
  verifyWalletTransactionTraceBocs,
} from "../api";
import type {
  WalletPersistedTransactionTraceEvidenceResponse,
  WalletTraceBocVerificationResponse,
  WalletTransactionInclusionCatalogResponse,
  WalletTransactionRecord,
} from "../types";
import {
  eligibleTraceTransactions,
  validatePersistedWalletTransactionTraceEvidenceResponse,
  validateWalletTransactionTraceBocVerificationResponse,
  type WalletTraceEligibleTransaction,
} from "../walletTraceEvidence";
import { validateWalletTransactionInclusionCatalog } from "../walletTransactionInclusion";

interface GramTransactionProofCardProps {
  runId: number;
  dataMode: "mock" | "real";
  transactions: WalletTransactionRecord[];
}

type FlowState = "idle" | "loading" | "ready" | "error";

export default function GramTransactionProofCard({
  runId,
  dataMode,
  transactions,
}: GramTransactionProofCardProps) {
  const eligible = useMemo(
    () => eligibleTraceTransactions(transactions).slice(0, 100),
    [transactions],
  );
  const [selectedHash, setSelectedHash] = useState(eligible[0]?.transactionHash ?? "");
  const selected =
    eligible.find((row) => row.transactionHash === selectedHash) ?? eligible[0] ?? null;
  const [capture, setCapture] =
    useState<WalletPersistedTransactionTraceEvidenceResponse | null>(null);
  const [boc, setBoc] = useState<WalletTraceBocVerificationResponse | null>(null);
  const [inclusion, setInclusion] =
    useState<WalletTransactionInclusionCatalogResponse | null>(null);
  const [state, setState] = useState<FlowState>("idle");
  const [workingStep, setWorkingStep] = useState<"capture" | "boc" | "inclusion" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);
  const actionSequence = useRef(0);
  const actionController = useRef<AbortController | null>(null);
  const scopeKey = `${runId}:${dataMode}:${selected?.transactionHash ?? "none"}`;
  const activeScopeKey = useRef(scopeKey);
  activeScopeKey.current = scopeKey;

  useEffect(() => {
    const next = selected?.transactionHash ?? "";
    if (next !== selectedHash) setSelectedHash(next);
  }, [selected, selectedHash]);

  useEffect(() => {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    const controller = new AbortController();
    actionSequence.current += 1;
    actionController.current?.abort();
    actionController.current = null;
    setWorkingStep(null);
    setCapture(null);
    setBoc(null);
    setInclusion(null);
    setError(null);

    if (dataMode !== "real" || !selected) {
      setState("idle");
      return cleanupRequests;
    }

    setState("loading");
    void hydrateEvidence(selected, controller.signal)
      .then((result) => {
        if (controller.signal.aborted || requestSequence.current !== sequence) return;
        setCapture(result.capture);
        setBoc(result.boc);
        setInclusion(result.inclusion);
        setState("ready");
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted || requestSequence.current !== sequence) return;
        setError(errorMessage(reason, "Could not read stored transaction evidence."));
        setState("error");
      });
    return cleanupRequests;

    function cleanupRequests() {
      controller.abort();
      actionSequence.current += 1;
      actionController.current?.abort();
      actionController.current = null;
    }
  }, [runId, dataMode, selected?.transactionHash]);

  const completedSteps = inclusion ? 3 : boc ? 2 : capture ? 1 : 0;
  const supported = dataMode === "real" && selected !== null;
  const busy = state === "loading" || workingStep !== null;
  const primaryProof = inclusion?.proofs[0] ?? null;
  const trustLevel = inclusion
    ? inclusion.proofs.reduce<0 | 1>((level, proof) => Math.max(level, proof.trust_level) as 0 | 1, 0)
    : null;

  async function hydrateEvidence(
    transaction: WalletTraceEligibleTransaction,
    signal: AbortSignal,
  ) {
    const expected = expectedAnchor(transaction);
    const rawCapture = await getPersistedWalletTransactionTraceEvidence(
      runId,
      transaction.transactionHash,
      signal,
    );
    if (!rawCapture) return { capture: null, boc: null, inclusion: null };
    const storedCapture = validatePersistedWalletTransactionTraceEvidenceResponse(
      rawCapture,
      expected,
    );
    const rawBoc = await getWalletTransactionTraceBocVerification(
      runId,
      transaction.transactionHash,
      signal,
    );
    if (!rawBoc) return { capture: storedCapture, boc: null, inclusion: null };
    const storedBoc = validateWalletTransactionTraceBocVerificationResponse(rawBoc, {
      ...expected,
      captureId: storedCapture.capture_id,
      captureEvidenceDigest: storedCapture.evidence_digest_sha256,
      transactionCount: storedCapture.summary.transaction_count,
      messageCount: storedCapture.summary.message_count,
    });
    const rawInclusion = await getWalletTransactionInclusionProofs(
      runId,
      transaction.transactionHash,
      signal,
    );
    return {
      capture: storedCapture,
      boc: storedBoc,
      inclusion: rawInclusion
        ? validateWalletTransactionInclusionCatalog(rawInclusion, storedBoc)
        : null,
    };
  }

  async function runStep(step: "capture" | "boc" | "inclusion") {
    if (!selected || busy) return;
    const expectedScope = scopeKey;
    const sequence = actionSequence.current + 1;
    actionSequence.current = sequence;
    actionController.current?.abort();
    const controller = new AbortController();
    actionController.current = controller;
    setWorkingStep(step);
    setError(null);
    try {
      const expected = expectedAnchor(selected);
      if (step === "capture") {
        const raw = await persistWalletTransactionTraceEvidence(runId, selected.transactionHash, controller.signal);
        if (!actionIsCurrent()) return;
        setCapture(validatePersistedWalletTransactionTraceEvidenceResponse(raw, expected));
      } else if (step === "boc" && capture) {
        const raw = await verifyWalletTransactionTraceBocs(runId, selected.transactionHash, controller.signal);
        if (!actionIsCurrent()) return;
        setBoc(validateWalletTransactionTraceBocVerificationResponse(raw, {
          ...expected,
          captureId: capture.capture_id,
          captureEvidenceDigest: capture.evidence_digest_sha256,
          transactionCount: capture.summary.transaction_count,
          messageCount: capture.summary.message_count,
        }));
      } else if (step === "inclusion" && boc) {
        const raw = await proveWalletTransactionInclusion(runId, selected.transactionHash, controller.signal);
        if (!actionIsCurrent()) return;
        setInclusion(validateWalletTransactionInclusionCatalog(raw, boc));
      }
      if (!actionIsCurrent()) return;
      setState("ready");
    } catch (reason) {
      if (!actionIsCurrent() || controller.signal.aborted) return;
      setError(errorMessage(reason, "The proof step failed."));
      setState("error");
    } finally {
      if (actionIsCurrent()) {
        actionController.current = null;
        setWorkingStep(null);
      }
    }

    function actionIsCurrent() {
      return (
        !controller.signal.aborted &&
        actionSequence.current === sequence &&
        activeScopeKey.current === expectedScope
      );
    }
  }

  return (
    <section className={inclusion ? "gram-proof-flow is-verified" : "gram-proof-flow"}>
      <header className="gram-proof-flow-header">
        <span className="gram-proof-flow-icon"><Cube size={25} weight="duotone" /></span>
        <div>
          <small>Transaction evidence</small>
          <h2>From provider trace to block inclusion</h2>
          <p>Three explicit steps bind locally decoded transaction cells to exact shard blocks. Stored evidence is revalidated before it is shown.</p>
        </div>
        <span className={inclusion ? "gram-proof-status is-verified" : "gram-proof-status"}>
          {inclusion ? <CheckCircle size={15} weight="fill" /> : <Fingerprint size={15} />}
          {inclusion ? `${inclusion.proof_count} included` : `${completedSteps} of 3`}
        </span>
      </header>

      {!supported ? (
        <ProofNotice title={dataMode === "mock" ? "Live run required" : "No eligible transaction"}>
          {dataMode === "mock"
            ? "Preview data cannot be promoted into cryptographic evidence. Create a real TonAPI-backed run."
            : "The run needs a live, network-scoped TonAPI transaction with a canonical hash and logical time."}
        </ProofNotice>
      ) : (
        <>
          <div className="gram-proof-selector">
            <label htmlFor={`gram-proof-transaction-${runId}`}>Transaction</label>
            <select
              id={`gram-proof-transaction-${runId}`}
              value={selected.transactionHash}
              disabled={busy}
              onChange={(event) => setSelectedHash(event.target.value)}
            >
              {eligible.map((row) => (
                <option value={row.transactionHash} key={row.transactionHash}>
                  {shortHash(row.transactionHash)} · LT {row.logicalTime}
                </option>
              ))}
            </select>
            <span>{selected.network}</span>
          </div>

          <ol className="gram-proof-steps">
            <ProofStep
              number="01"
              title="Capture trace"
              detail={capture ? `${capture.summary.transaction_count} transaction cells` : "Immutable provider graph"}
              complete={Boolean(capture)}
              active={!capture}
            />
            <ProofStep
              number="02"
              title="Verify BOC"
              detail={boc ? `${boc.summary.total_boc_bytes.toLocaleString()} bytes decoded` : "Local cell and hash checks"}
              complete={Boolean(boc)}
              active={Boolean(capture && !boc)}
            />
            <ProofStep
              number="03"
              title="Prove inclusion"
              detail={inclusion ? `${inclusion.proof_count} block proofs` : "Merkle path to shard blocks"}
              complete={Boolean(inclusion)}
              active={Boolean(boc && !inclusion)}
            />
          </ol>

          {state === "loading" && <ProofNotice title="Reading evidence" loading>Stored proof records are being revalidated.</ProofNotice>}
          {error && <ProofNotice title="Verification stopped" error>{error}</ProofNotice>}
          {state !== "loading" && !inclusion && (
            <div className="gram-proof-action-row">
              {!capture ? (
                <button className="button-primary" type="button" disabled={busy} onClick={() => void runStep("capture")}>
                  {workingStep === "capture" ? <SpinnerGap className="spin" /> : <ArrowRight />}
                  {workingStep === "capture" ? "Capturing…" : "Capture immutable trace"}
                </button>
              ) : !boc ? (
                <button className="button-primary" type="button" disabled={busy} onClick={() => void runStep("boc")}>
                  {workingStep === "boc" ? <SpinnerGap className="spin" /> : <ArrowRight />}
                  {workingStep === "boc" ? "Verifying…" : "Verify BOC locally"}
                </button>
              ) : (
                <button className="button-primary" type="button" disabled={busy} onClick={() => void runStep("inclusion")}>
                  {workingStep === "inclusion" ? <SpinnerGap className="spin" /> : <ArrowRight />}
                  {workingStep === "inclusion" ? "Proving…" : "Prove block inclusion"}
                </button>
              )}
              <p>Each completed step is persisted and can be audited again without repeating earlier work.</p>
            </div>
          )}

          {inclusion && primaryProof && (
            <div className="gram-proof-result">
              <div className="gram-proof-result-banner">
                <CheckCircle size={20} weight="fill" />
                <div>
                  <strong>Every captured transaction BOC is included in a block.</strong>
                  <span>{trustLevel === 0 ? "Checkpoint-anchored canonical chain verified at capture." : "Shard inclusion verified; a trust-level-0 checkpoint chain is not claimed."}</span>
                </div>
                <span>Trust {trustLevel}</span>
              </div>
              <dl className="gram-proof-facts">
                <div><dt>Proofs</dt><dd>{inclusion.proof_count}</dd></div>
                <div><dt>Shard block</dt><dd>#{primaryProof.block.seqno}</dd></div>
                <div><dt>Master anchor</dt><dd>#{primaryProof.masterchain_anchor.seqno}</dd></div>
                <div><dt>Evidence</dt><dd title={inclusion.catalog_digest_sha256}>{shortHash(inclusion.catalog_digest_sha256)}</dd></div>
              </dl>
            </div>
          )}
        </>
      )}
    </section>
  );

  function expectedAnchor(transaction: WalletTraceEligibleTransaction) {
    return {
      runId,
      transactionHash: transaction.transactionHash,
      logicalTime: transaction.logicalTime,
      accountCanonical: transaction.accountCanonical,
      network: transaction.network,
    };
  }
}

function ProofStep({ number, title, detail, complete, active }: { number: string; title: string; detail: string; complete: boolean; active: boolean }) {
  return (
    <li className={complete ? "is-complete" : active ? "is-active" : ""}>
      <span>{complete ? <Check size={14} weight="bold" /> : number}</span>
      <div><strong>{title}</strong><small>{detail}</small></div>
    </li>
  );
}

function ProofNotice({ title, children, error = false, loading = false }: { title: string; children: React.ReactNode; error?: boolean; loading?: boolean }) {
  return (
    <div className={error ? "gram-proof-notice is-error" : "gram-proof-notice"} role={error ? "alert" : "status"}>
      {loading ? <SpinnerGap className="spin" size={20} /> : error ? <WarningCircle size={20} weight="fill" /> : <Fingerprint size={20} />}
      <div><strong>{title}</strong><span>{children}</span></div>
    </div>
  );
}

function shortHash(value: string): string {
  return `${value.slice(0, 8)}…${value.slice(-8)}`;
}

function errorMessage(reason: unknown, fallback: string): string {
  return reason instanceof Error && reason.message ? reason.message : fallback;
}
