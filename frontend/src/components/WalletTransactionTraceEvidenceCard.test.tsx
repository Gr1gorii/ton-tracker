// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  WalletTransactionRecord,
  WalletTransactionTraceEvidenceResponse,
} from "../types";

const apiMocks = vi.hoisted(() => ({
  getWalletTransactionTraceEvidence: vi.fn(),
}));

vi.mock("../api", () => apiMocks);

import WalletTransactionTraceEvidenceCard from "./WalletTransactionTraceEvidenceCard";

const ACCOUNT = `0:${"c".repeat(64)}`;

function transaction(
  marker = "a",
  logicalTime = "46000000000001",
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
      account_canonical: ACCOUNT,
      logical_time_canonical: logicalTime,
      hash_canonical: hash,
      key: `ton_account_tx_v1|ton-mainnet|${ACCOUNT}|${logicalTime}|${hash}`,
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
    message: `Sanitized trace for ${identity.hash_canonical}`,
    ...overrides,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

describe("WalletTransactionTraceEvidenceCard", () => {
  afterEach(cleanup);

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("stays network-silent and permanently exposes false invariants for mock runs", () => {
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="mock"
        transactions={[transaction()]}
      />,
    );

    expect(
      screen.getByRole("region", { name: "Transaction trace evidence" }),
    ).toBeTruthy();
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(
      (screen.getByLabelText("Stored transaction anchor") as HTMLSelectElement)
        .disabled,
    ).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Inspect trace evidence" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("NON-AUTHORITATIVE")).toBeTruthy();
    expect(screen.getByText("NOT PNL")).toBeTruthy();
    expect(screen.getByText("NO OWNERSHIP PROOF")).toBeTruthy();
    expect(screen.getAllByText("FALSE")).toHaveLength(8);
    expect(screen.getByText("is_authoritative_activity_identity")).toBeTruthy();
    expect(screen.getByText("used_by_pnl")).toBeTruthy();
  });

  it("keeps a real empty run explicit and disabled", () => {
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="real"
        transactions={[]}
      />,
    );

    expect(screen.getByText("NO ELIGIBLE TRACE ANCHOR")).toBeTruthy();
    expect(screen.getByText(/no stored low-level transaction rows/i)).toBeTruthy();
    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(
      (screen.getByRole("button", { name: "Inspect trace evidence" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it("fetches only after explicit inspection and renders sanitized evidence", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    apiMocks.getWalletTransactionTraceEvidence.mockResolvedValueOnce(
      traceResponse(25, stored),
    );
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="real"
        transactions={[stored]}
      />,
    );

    expect(apiMocks.getWalletTransactionTraceEvidence).not.toHaveBeenCalled();
    expect(screen.getByText("EXPLICIT REQUEST REQUIRED")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Inspect trace evidence" }));

    expect(await screen.findByText("FINALIZED PROVIDER TRACE")).toBeTruthy();
    expect(apiMocks.getWalletTransactionTraceEvidence).toHaveBeenCalledWith(
      25,
      "a".repeat(64),
      expect.any(AbortSignal),
    );
    expect(screen.getByText("tonapi_transaction_trace_preview_v1")).toBeTruthy();
    expect(screen.getByText("Transactions")).toBeTruthy();
    expect(screen.getByText("Unique accounts")).toBeTruthy();
    expect(screen.getByText(`Sanitized trace for ${"a".repeat(64)}`)).toBeTruthy();

    const disclosure = screen.getByText("Exact stored anchor and provider trace root");
    await user.click(disclosure);
    expect(screen.getByText("Matches stored transaction")).toBeTruthy();
    expect(screen.getByText("TRUE")).toBeTruthy();
  });

  it("preserves the last success when an explicit retry fails", async () => {
    const user = userEvent.setup();
    const stored = transaction();
    apiMocks.getWalletTransactionTraceEvidence
      .mockResolvedValueOnce(traceResponse(25, stored))
      .mockRejectedValueOnce(new Error("Provider trace temporarily unavailable"));
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="real"
        transactions={[stored]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Inspect trace evidence" }));
    expect(await screen.findByText("FINALIZED PROVIDER TRACE")).toBeTruthy();
    const priorMessage = `Sanitized trace for ${"a".repeat(64)}`;
    expect(screen.getByText(priorMessage)).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Inspect again" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Provider trace temporarily unavailable",
    );
    expect(screen.getByText("LAST TRACE RESULT PRESERVED")).toBeTruthy();
    expect(screen.getByText(priorMessage)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Retry trace evidence" })).toBeTruthy();
  });

  it("aborts a superseded anchor request and ignores its late response", async () => {
    const user = userEvent.setup();
    const first = transaction("a", "46000000000001");
    const second = transaction("b", "46000000000002");
    const pendingFirst = deferred<WalletTransactionTraceEvidenceResponse>();
    apiMocks.getWalletTransactionTraceEvidence
      .mockReturnValueOnce(pendingFirst.promise)
      .mockResolvedValueOnce(traceResponse(25, second));
    render(
      <WalletTransactionTraceEvidenceCard
        runId={25}
        dataMode="real"
        transactions={[first, second]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Inspect trace evidence" }));
    const firstSignal = apiMocks.getWalletTransactionTraceEvidence.mock.calls[0][2];
    await user.selectOptions(
      screen.getByLabelText("Stored transaction anchor"),
      "b".repeat(64),
    );
    expect(firstSignal.aborted).toBe(true);
    await user.click(screen.getByRole("button", { name: "Inspect trace evidence" }));

    expect(
      await screen.findByText(`Sanitized trace for ${"b".repeat(64)}`),
    ).toBeTruthy();
    pendingFirst.resolve(traceResponse(25, first));
    await act(async () => Promise.resolve());
    expect(screen.queryByText(`Sanitized trace for ${"a".repeat(64)}`)).toBeNull();
    expect(screen.getByText(`Sanitized trace for ${"b".repeat(64)}`)).toBeTruthy();
  });

  it("remounts cleanly for another run and aborts pending run-scoped state", async () => {
    const user = userEvent.setup();
    const first = transaction("a", "46000000000001");
    const second = transaction("b", "46000000000002");
    const pending = deferred<WalletTransactionTraceEvidenceResponse>();
    apiMocks.getWalletTransactionTraceEvidence.mockReturnValueOnce(pending.promise);
    const rendered = render(
      <WalletTransactionTraceEvidenceCard
        key="run-25"
        runId={25}
        dataMode="real"
        transactions={[first]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Inspect trace evidence" }));
    const signal = apiMocks.getWalletTransactionTraceEvidence.mock.calls[0][2];
    rendered.rerender(
      <WalletTransactionTraceEvidenceCard
        key="run-26"
        runId={26}
        dataMode="real"
        transactions={[second]}
      />,
    );

    expect(signal.aborted).toBe(true);
    expect(screen.getByText("EXPLICIT REQUEST REQUIRED")).toBeTruthy();
    expect(screen.getByText("#26")).toBeTruthy();
    expect(apiMocks.getWalletTransactionTraceEvidence).toHaveBeenCalledTimes(1);

    pending.resolve(traceResponse(25, first));
    await act(async () => Promise.resolve());
    await waitFor(() => {
      expect(screen.queryByText(`Sanitized trace for ${"a".repeat(64)}`)).toBeNull();
    });
  });
});
