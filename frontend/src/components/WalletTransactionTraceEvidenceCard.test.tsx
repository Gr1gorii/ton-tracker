// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletPersistedTransactionTraceEvidenceResponse,
  WalletTraceBocVerificationResponse,
  WalletTransactionRecord,
  WalletTransactionTraceEvidenceResponse,
} from "../types";

const apiMocks = vi.hoisted(() => ({
  getPersistedWalletTransactionTraceEvidence: vi.fn(),
  getWalletTransactionTraceBocVerification: vi.fn(),
  getWalletTransactionJettonPayloadObservations: vi.fn(),
  getWalletTransactionTraceEvidence: vi.fn(),
  persistWalletTransactionTraceEvidence: vi.fn(),
  verifyWalletTransactionTraceBocs: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import WalletTransactionTraceEvidenceCard from "./WalletTransactionTraceEvidenceCard";

const ACCOUNT = `0:${"c".repeat(64)}`;

function transaction(
  marker = "a",
  logicalTime = "46000000000001",
  account = ACCOUNT,
): WalletTransactionRecord {
  const hash = marker.repeat(64);
  return {
    tx_hash: hash.toUpperCase(),
    logical_time: logicalTime,
    timestamp: "2026-07-10T01:00:00Z",
    fee_ton: "0.01",
    success: "success",
    provider: "tonapi",
    source_status: "live",
    transaction_identity: {
      status: "network_scoped",
      version: "ton_account_tx_v1",
      network: "ton-mainnet",
      account_canonical: account,
      logical_time_canonical: logicalTime,
      hash_canonical: hash,
      key: `ton_account_tx_v1|ton-mainnet|${account}|${logicalTime}|${hash}`,
      is_deduplication_identity: true,
      is_blockchain_proof_verified: false,
      is_ownership_proof: false,
      deduplication_applied: false,
      used_by_pnl: false,
    },
    raw: null,
  };
}

function traceResponse(
  runId: number,
  selected: WalletTransactionRecord,
  overrides: Partial<WalletTransactionTraceEvidenceResponse> = {},
): WalletTransactionTraceEvidenceResponse {
  const identity = selected.transaction_identity;
  return {
    contract_version: "tonapi_transaction_trace_preview_v1",
    run_id: String(runId),
    provider: "tonapi",
    source_status: "live",
    trace_state: "finalized",
    anchor: {
      transaction_hash: identity.hash_canonical!,
      logical_time: identity.logical_time_canonical!,
      account_canonical: identity.account_canonical!,
      matches_stored_transaction: true,
    },
    summary: {
      root_transaction_hash: "f".repeat(64),
      transaction_count: 3,
      max_depth: 2,
      out_message_count: 4,
      pending_internal_message_count: 0,
      successful_transaction_count: 2,
      failed_transaction_count: 1,
      aborted_transaction_count: 1,
      unique_account_count: 2,
    },
    is_provider_indexed_low_level_trace: true,
    is_blockchain_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: `Live preview for ${identity.hash_canonical}`,
    ...overrides,
  };
}

function persistedResponse(
  runId: number,
  selected: WalletTransactionRecord,
  captureId = "9",
): WalletPersistedTransactionTraceEvidenceResponse {
  const identity = selected.transaction_identity;
  return {
    contract_version: "tonapi_low_level_trace_evidence_v1",
    capture_id: captureId,
    run_id: String(runId),
    provider: "tonapi",
    source_status: "live",
    network: "ton-mainnet",
    trace_state: "finalized",
    captured_at: "2026-07-10T12:34:56.123456Z",
    anchor: {
      transaction_hash: identity.hash_canonical!,
      logical_time: identity.logical_time_canonical!,
      account_canonical: identity.account_canonical!,
      matches_stored_transaction: true,
    },
    summary: {
      root_transaction_hash: "e".repeat(64),
      transaction_count: 3,
      max_depth: 2,
      message_count: 5,
      root_inbound_message_count: 1,
      child_internal_message_count: 2,
      remaining_out_message_count: 2,
      internal_message_count: 2,
      external_in_message_count: 1,
      external_out_message_count: 2,
      successful_transaction_count: 2,
      failed_transaction_count: 1,
      aborted_transaction_count: 1,
      unique_account_count: 2,
    },
    evidence_digest_sha256: "d".repeat(64),
    is_provider_indexed_low_level_trace: true,
    provider_structure_validated: true,
    persisted_graph_revalidated: true,
    is_immutable_record: true,
    raw_boc_persisted: false,
    message_body_persisted: false,
    is_blockchain_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: `Saved evidence for ${identity.hash_canonical}`,
  };
}

function bocResponse(
  runId: number,
  selected: WalletTransactionRecord,
): WalletTraceBocVerificationResponse {
  const persisted = persistedResponse(runId, selected);
  const hashes = [
    persisted.summary.root_transaction_hash,
    selected.transaction_identity.hash_canonical!,
    "f".repeat(64),
  ];
  return {
    contract_version: "ton_boc_trace_verification_v1",
    verification_id: "4",
    capture_id: persisted.capture_id,
    run_id: String(runId),
    provider: "tonapi",
    source_status: "live",
    network: "ton-mainnet",
    verified_at: "2026-07-10T13:00:00.123456Z",
    verifier: { name: "pytoniq-core", version: "0.1.46" },
    anchor: persisted.anchor,
    capture_evidence_digest_sha256: persisted.evidence_digest_sha256,
    evidence_digest_sha256: "9".repeat(64),
    summary: {
      transaction_count: 3,
      message_count: 5,
      total_boc_bytes: 1200,
      normalized_external_in_hash_count: 1,
      direct_cell_hash_message_count: 4,
      body_hash_count: 5,
      opcode_count: 2,
    },
    transactions: hashes.map((hash, index) => ({
      preorder_index: index,
      transaction_hash: hash,
      transaction_boc_bytes: 400,
      transaction_cell_hash: hash,
      raw_out_message_count: index === 0 ? 2 : 0,
      message_count: index < 2 ? 2 : 1,
      body_hash_count: index < 2 ? 2 : 1,
      opcode_count: index < 2 ? 1 : 0,
      message_evidence_digest_sha256: String(index + 1).repeat(64),
    })),
    transaction_bocs_deserialized_locally: true,
    transaction_cell_hashes_verified: true,
    transaction_headers_verified: true,
    message_hashes_verified: true,
    message_headers_verified: true,
    message_body_hashes_derived: true,
    raw_boc_persisted: true,
    raw_boc_returned: false,
    message_bodies_returned: false,
    is_blockchain_inclusion_proof_verified: false,
    is_authoritative_activity_identity: false,
    semantic_reconstruction_applied: false,
    activity_merge_applied: false,
    deduplication_applied: false,
    eligible_for_cost_basis: false,
    used_by_pnl: false,
    is_ownership_proof: false,
    message: "Locally reparsed transaction BOC evidence.",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

describe("WalletTransactionTraceEvidenceCard", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockReset().mockResolvedValue(null);
    apiMocks.getWalletTransactionTraceBocVerification.mockReset().mockResolvedValue(null);
    apiMocks.getWalletTransactionTraceEvidence.mockReset();
    apiMocks.persistWalletTransactionTraceEvidence.mockReset();
    apiMocks.verifyWalletTransactionTraceBocs.mockReset();
  });

  it("reads local BOC state automatically and verifies only on explicit click", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    const persisted = persistedResponse(25, stored);
    const verified = bocResponse(25, stored);
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValue(
      persisted,
    );
    apiMocks.getWalletTransactionTraceBocVerification.mockResolvedValue(null);
    apiMocks.verifyWalletTransactionTraceBocs.mockResolvedValue(verified);

    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="real"
        transactions={[stored]}
      />,
    );

    const verifyButton = await screen.findByRole("button", {
      name: "Verify transaction BOCs",
    });
    expect(apiMocks.getWalletTransactionTraceBocVerification).toHaveBeenCalledWith(
      25,
      "a".repeat(64),
      expect.any(AbortSignal),
    );
    expect(apiMocks.verifyWalletTransactionTraceBocs).not.toHaveBeenCalled();

    await user.click(verifyButton);
    expect(apiMocks.verifyWalletTransactionTraceBocs).toHaveBeenCalledWith(
      25,
      "a".repeat(64),
      expect.any(AbortSignal),
    );
    expect(await screen.findByText("Transaction cells and messages matched")).toBeTruthy();
    expect(screen.getByText("RAW BOC HIDDEN")).toBeTruthy();
    expect(screen.queryByText(/transaction_boc_hex/i)).toBeNull();
  });

  it("stays network-silent and exposes permanent limits for mock runs", () => {
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="mock"
        transactions={[transaction()]}
      />,
    );

    expect(screen.getByRole("region", { name: "Transaction trace evidence" })).toBeTruthy();
    expect(apiMocks.getPersistedWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(apiMocks.persistWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Stored transaction anchor") as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Preview live trace" }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("STORED ≠ VERIFIED")).toBeTruthy();
    expect(screen.getByText("NON-AUTHORITATIVE")).toBeTruthy();
    expect(screen.getAllByText("FALSE")).toHaveLength(10);
  });

  it("keeps a real empty run explicit without any read or capture", () => {
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[]} />,
    );

    expect(screen.getByText("NO ELIGIBLE TRACE ANCHOR")).toBeTruthy();
    expect(screen.getByText(/no stored low-level transaction rows/i)).toBeTruthy();
    expect(apiMocks.getPersistedWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
  });

  it("automatically performs a database-only readback and never previews or captures", async () => {
    const stored = transaction();
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[stored]} />,
    );

    expect(await screen.findByText("NO SAVED TRACE EVIDENCE")).toBeTruthy();
    expect(apiMocks.getPersistedWalletTransactionTraceEvidence).toHaveBeenCalledWith(
      25,
      "a".repeat(64),
      expect.any(AbortSignal),
    );
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(apiMocks.persistWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Preview live trace" })).toBeTruthy();
    expect((screen.getByRole("button", { name: "Preview finalized trace to save" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("renders an immutable saved readback without contacting the provider", async () => {
    const stored = transaction();
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValueOnce(
      persistedResponse(25, stored),
    );
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[stored]} />,
    );

    expect(await screen.findByText("SAVED IMMUTABLE TRACE EVIDENCE")).toBeTruthy();
    expect(screen.getByText("tonapi_low_level_trace_evidence_v1")).toBeTruthy();
    expect(screen.getByText("FINALIZED AT CAPTURE")).toBeTruthy();
    expect(screen.getByText("LOCAL GRAPH REVALIDATED")).toBeTruthy();
    expect(screen.getByText(`Saved evidence for ${"a".repeat(64)}`)).toBeTruthy();
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(apiMocks.persistWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Immutable evidence saved" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("previews explicitly, then captures and renders a validated immutable record", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    apiMocks.getWalletTransactionTraceEvidence.mockResolvedValueOnce(traceResponse(25, stored));
    apiMocks.persistWalletTransactionTraceEvidence.mockResolvedValueOnce(
      persistedResponse(25, stored),
    );
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[stored]} />,
    );

    await screen.findByText("NO SAVED TRACE EVIDENCE");
    await user.click(screen.getByRole("button", { name: "Preview live trace" }));

    expect(await screen.findByText("Finalized preview")).toBeTruthy();
    expect(apiMocks.getWalletTransactionTraceEvidence).toHaveBeenCalledWith(
      25,
      "a".repeat(64),
      expect.any(AbortSignal),
    );
    await user.click(screen.getByRole("button", { name: "Capture and store evidence" }));

    expect(await screen.findByText("SAVED IMMUTABLE TRACE EVIDENCE")).toBeTruthy();
    expect(apiMocks.persistWalletTransactionTraceEvidence).toHaveBeenCalledWith(
      25,
      "a".repeat(64),
      expect.any(AbortSignal),
    );
    expect(screen.getByText(`Live preview for ${"a".repeat(64)}`)).toBeTruthy();
    expect(screen.getByText(`Saved evidence for ${"a".repeat(64)}`)).toBeTruthy();
  });

  it("keeps a pending live preview visible but never enables persistence", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    apiMocks.getWalletTransactionTraceEvidence.mockResolvedValueOnce(
      traceResponse(25, stored, {
        trace_state: "pending",
        summary: {
          ...traceResponse(25, stored).summary,
          pending_internal_message_count: 1,
        },
      }),
    );
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[stored]} />,
    );

    await screen.findByText("NO SAVED TRACE EVIDENCE");
    await user.click(screen.getByRole("button", { name: "Preview live trace" }));

    expect(await screen.findByText("Pending preview")).toBeTruthy();
    expect((screen.getByRole("button", { name: "Finalized trace required to save" }) as HTMLButtonElement).disabled).toBe(true);
    expect(apiMocks.persistWalletTransactionTraceEvidence).not.toHaveBeenCalled();
  });

  it("preserves a saved record when a later explicit live preview fails", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    apiMocks.getPersistedWalletTransactionTraceEvidence.mockResolvedValueOnce(
      persistedResponse(25, stored),
    );
    apiMocks.getWalletTransactionTraceEvidence.mockRejectedValueOnce(
      new Error("Provider trace temporarily unavailable"),
    );
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[stored]} />,
    );

    await screen.findByText("SAVED IMMUTABLE TRACE EVIDENCE");
    await user.click(screen.getByRole("button", { name: "Preview live trace" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Provider trace temporarily unavailable",
    );
    expect(screen.getByText(`Saved evidence for ${"a".repeat(64)}`)).toBeTruthy();
    expect(screen.getByText("SAVED IMMUTABLE TRACE EVIDENCE")).toBeTruthy();
  });

  it("keeps the finalized preview when capture fails and allows retry", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    apiMocks.getWalletTransactionTraceEvidence.mockResolvedValueOnce(traceResponse(25, stored));
    apiMocks.persistWalletTransactionTraceEvidence.mockRejectedValueOnce(
      new Error("Trace became pending before persistence"),
    );
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[stored]} />,
    );

    await screen.findByText("NO SAVED TRACE EVIDENCE");
    await user.click(screen.getByRole("button", { name: "Preview live trace" }));
    await screen.findByText("Finalized preview");
    await user.click(screen.getByRole("button", { name: "Capture and store evidence" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Trace became pending before persistence",
    );
    expect(screen.getByText("EVIDENCE NOT SAVED")).toBeTruthy();
    expect(screen.getByText(`Live preview for ${"a".repeat(64)}`)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Capture and store evidence" })).toBeTruthy();
  });

  it("keeps saved read failure distinct and retries only the database read", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    apiMocks.getPersistedWalletTransactionTraceEvidence
      .mockRejectedValueOnce(new Error("Saved evidence database unavailable"))
      .mockResolvedValueOnce(null);
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="real"
        transactions={[stored]}
      />,
    );

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Saved evidence database unavailable",
    );
    expect(screen.getByText("SAVED EVIDENCE READ FAILED")).toBeTruthy();
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    await user.click(
      screen.getByRole("button", { name: "Retry saved evidence read" }),
    );

    expect(await screen.findByText("NO SAVED TRACE EVIDENCE")).toBeTruthy();
    expect(apiMocks.getPersistedWalletTransactionTraceEvidence).toHaveBeenCalledTimes(2);
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(apiMocks.persistWalletTransactionTraceEvidence).not.toHaveBeenCalled();
  });

  it("aborts a superseded saved read and ignores its late response", async () => {
    const user = userEvent.setup();
    const first = transaction("a", "46000000000001");
    const second = transaction("b", "46000000000002");
    const firstRead = deferred<WalletPersistedTransactionTraceEvidenceResponse | null>();
    apiMocks.getPersistedWalletTransactionTraceEvidence
      .mockReturnValueOnce(firstRead.promise)
      .mockResolvedValueOnce(persistedResponse(25, second, "10"));
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[first, second]} />,
    );

    await waitFor(() => expect(apiMocks.getPersistedWalletTransactionTraceEvidence).toHaveBeenCalledTimes(1));
    const firstSignal = apiMocks.getPersistedWalletTransactionTraceEvidence.mock.calls[0][2];
    await user.selectOptions(screen.getByLabelText("Stored transaction anchor"), "b".repeat(64));

    expect(firstSignal.aborted).toBe(true);
    expect(await screen.findByText(`Saved evidence for ${"b".repeat(64)}`)).toBeTruthy();
    firstRead.resolve(persistedResponse(25, first));
    await act(async () => Promise.resolve());
    expect(screen.queryByText(`Saved evidence for ${"a".repeat(64)}`)).toBeNull();
  });

  it("aborts a superseded live preview and ignores its late response", async () => {
    const user = userEvent.setup();
    const first = transaction("a", "46000000000001");
    const second = transaction("b", "46000000000002");
    const firstPreview = deferred<WalletTransactionTraceEvidenceResponse>();
    apiMocks.getWalletTransactionTraceEvidence.mockReturnValueOnce(
      firstPreview.promise,
    );
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="real"
        transactions={[first, second]}
      />,
    );

    await screen.findByText("NO SAVED TRACE EVIDENCE");
    await user.click(screen.getByRole("button", { name: "Preview live trace" }));
    const previewSignal = apiMocks.getWalletTransactionTraceEvidence.mock.calls[0][2];
    await user.selectOptions(
      screen.getByLabelText("Stored transaction anchor"),
      "b".repeat(64),
    );

    expect(previewSignal.aborted).toBe(true);
    await screen.findByText("NO SAVED TRACE EVIDENCE");
    firstPreview.resolve(traceResponse(25, first));
    await act(async () => Promise.resolve());
    expect(screen.queryByText(`Live preview for ${"a".repeat(64)}`)).toBeNull();
  });

  it("aborts capture on anchor change and ignores a late saved response", async () => {
    const user = userEvent.setup();
    const first = transaction("a", "46000000000001");
    const second = transaction("b", "46000000000002");
    const capture = deferred<WalletPersistedTransactionTraceEvidenceResponse>();
    apiMocks.getWalletTransactionTraceEvidence.mockResolvedValueOnce(traceResponse(25, first));
    apiMocks.persistWalletTransactionTraceEvidence.mockReturnValueOnce(capture.promise);
    render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[first, second]} />,
    );

    await screen.findByText("NO SAVED TRACE EVIDENCE");
    await user.click(screen.getByRole("button", { name: "Preview live trace" }));
    await screen.findByText("Finalized preview");
    await user.click(screen.getByRole("button", { name: "Capture and store evidence" }));
    const captureSignal = apiMocks.persistWalletTransactionTraceEvidence.mock.calls[0][2];
    await user.selectOptions(screen.getByLabelText("Stored transaction anchor"), "b".repeat(64));

    expect(captureSignal.aborted).toBe(true);
    await screen.findByText("NO SAVED TRACE EVIDENCE");
    capture.resolve(persistedResponse(25, first));
    await act(async () => Promise.resolve());
    expect(screen.queryByText(`Saved evidence for ${"a".repeat(64)}`)).toBeNull();
  });

  it("re-reads when LT and account change even if the selected hash is unchanged", async () => {
    const first = transaction("a", "46000000000001", ACCOUNT);
    const nextAccount = `0:${"d".repeat(64)}`;
    const second = transaction("a", "46000000000002", nextAccount);
    apiMocks.getPersistedWalletTransactionTraceEvidence
      .mockResolvedValueOnce(persistedResponse(25, first))
      .mockResolvedValueOnce(persistedResponse(25, second, "11"));
    const rendered = render(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[first]} />,
    );

    expect(await screen.findByText(`Saved evidence for ${"a".repeat(64)}`)).toBeTruthy();
    rendered.rerender(
      <WalletTransactionTraceEvidenceCard runId={25} dataMode="real" transactions={[second]} />,
    );

    await waitFor(() => expect(apiMocks.getPersistedWalletTransactionTraceEvidence).toHaveBeenCalledTimes(2));
    expect((await screen.findAllByText("#11")).length).toBeGreaterThanOrEqual(1);
    const disclosure = screen.getByText("Stored anchor, message graph, and evidence digest");
    await userEvent.setup().click(disclosure);
    expect(screen.getByText(nextAccount)).toBeTruthy();
    expect(screen.getByText("46000000000002")).toBeTruthy();
  });
});
