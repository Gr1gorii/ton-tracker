// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { WalletIngestionRunResponse, WalletRunSignalsResponse } from "../types";
import { WALLET_SIGNAL_CODES } from "../walletRunSignals";

const apiMocks = vi.hoisted(() => ({
  getWalletRunSignals: vi.fn(),
  walletRunSignalsCsvExportUrl: vi.fn((runId: number) => `/signals/${runId}.csv`),
  walletRunSignalsExportUrl: vi.fn((runId: number) => `/signals/${runId}.json`),
}));

vi.mock("../api", () => apiMocks);

import GramInsightsView from "./GramInsightsView";

const WALLET = "UQwallet-under-test";

function run(): WalletIngestionRunResponse {
  return {
    run_id: 25,
    wallet_address: WALLET,
    wallet_identity: {
      status: "unavailable",
      version: "unavailable",
      network: "ton-unknown",
      canonical_address: null,
      workchain_id: null,
      account_id_hex: null,
      submitted_format: "unrecognized",
      bounceable: null,
      testnet_only: null,
      is_account_existence_proof: false,
      is_ownership_proof: false,
    },
    time_window: "24h",
    custom_start: null,
    custom_end: null,
    created_at: "2026-07-29T12:00:00Z",
    status: "success",
    data_mode: "real",
    requested_surfaces: ["transactions"],
    provider_evidence: [],
    unavailable_surfaces: [],
    transfers: [],
    transactions: [],
    swaps: [],
    balances: [],
    warnings: [],
    message: "Run ready.",
  };
}

function signals(): WalletRunSignalsResponse {
  return {
    run_id: 25,
    wallet_address: WALLET,
    is_risk_score: false,
    evaluated: [...WALLET_SIGNAL_CODES],
    signals: [{
      code: "many_distinct_jettons",
      title: "Many distinct jettons held",
      confidence: "medium",
      observation: "The wallet holds 14 distinct non-TON jettons.",
      evidence: { distinct_jetton_count: 14 },
      note: "Often reflects airdrops or spam and is not by itself a risk indicator.",
    }],
    insufficient_evidence: [{
      code: "failed_transaction_ratio",
      reason: "Only 2 transactions were ingested.",
    }],
    note: "Heuristic evidence only; not a risk score.",
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getWalletRunSignals.mockResolvedValue(signals());
});

afterEach(cleanup);

describe("GramInsightsView", () => {
  it("shows matched evidence, confidence, gaps and exports without scoring the wallet", async () => {
    render(<GramInsightsView activeRun={run()} onOpenActivity={vi.fn()} />);

    await waitFor(() => expect(apiMocks.getWalletRunSignals).toHaveBeenCalledWith(25, expect.any(AbortSignal)));
    expect(await screen.findByText("1 heuristic pattern matched")).toBeTruthy();
    expect(screen.getByText("The wallet holds 14 distinct non-TON jettons.")).toBeTruthy();
    expect(screen.getByText("medium confidence")).toBeTruthy();
    expect(screen.getByText("Only 2 transactions were ingested.")).toBeTruthy();
    expect(screen.getByText("Risk score disabled")).toBeTruthy();
    expect((screen.getByRole("link", { name: "JSON" }) as HTMLAnchorElement).getAttribute("href")).toBe("/signals/25.json");
    expect((screen.getByRole("link", { name: "CSV" }) as HTMLAnchorElement).getAttribute("href")).toBe("/signals/25.csv");
  });

  it("fails closed when a response tries to introduce a risk score", async () => {
    const invalid = signals();
    invalid.is_risk_score = true;
    apiMocks.getWalletRunSignals.mockResolvedValue(invalid);
    render(<GramInsightsView activeRun={run()} onOpenActivity={vi.fn()} />);

    expect((await screen.findByRole("alert")).textContent).toContain("Wallet insight response is incoherent.");
    expect(screen.queryByText("1 heuristic pattern matched")).toBeNull();
  });

  it("guides the user to Activity without making a request when no run is selected", async () => {
    const onOpenActivity = vi.fn();
    const user = userEvent.setup();
    render(<GramInsightsView activeRun={null} onOpenActivity={onOpenActivity} />);
    expect(apiMocks.getWalletRunSignals).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Open activity" }));
    expect(onOpenActivity).toHaveBeenCalledOnce();
  });
});
