// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import GramOwnershipProofCard from "./GramOwnershipProofCard";

const EXPECTED_WALLET = `0:${"4".repeat(64)}`;
const CHALLENGE_ID = "2063e557-b4fc-478f-b861-18fb82754f2b";

const mocks = vi.hoisted(() => ({
  wallet: null as null | {
    account: { address: string; chain: string; walletStateInit: string };
    connectItems: {
      tonProof: {
        name: "ton_proof";
        proof: {
          timestamp: number;
          domain: { lengthBytes: number; value: string };
          payload: string;
          signature: string;
        };
      };
    };
  },
  ui: {
    connected: false,
    disconnect: vi.fn(),
    setConnectionNetwork: vi.fn(),
    setConnectRequestParameters: vi.fn(),
    openModal: vi.fn(),
  },
  createChallenge: vi.fn(),
  verifyChallenge: vi.fn(),
}));

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  useTonConnectUI: () => [mocks.ui],
  useTonWallet: () => mocks.wallet,
}));

vi.mock("../api", () => ({
  createWalletOwnershipChallenge: mocks.createChallenge,
  verifyWalletOwnershipChallenge: mocks.verifyChallenge,
}));

describe("GramOwnershipProofCard", () => {
  afterEach(cleanup);

  beforeEach(() => {
    mocks.wallet = null;
    mocks.ui.connected = false;
    mocks.ui.disconnect.mockReset().mockResolvedValue(undefined);
    mocks.ui.setConnectionNetwork.mockReset();
    mocks.ui.setConnectRequestParameters.mockReset();
    mocks.ui.openModal.mockReset().mockResolvedValue(undefined);
    mocks.createChallenge.mockReset().mockResolvedValue({
      challenge_id: CHALLENGE_ID,
      payload: "challenge-payload-that-is-long-enough-for-the-contract",
      expected_domain: "tracker.example",
      expected_network: "ton-mainnet",
      expected_wallet_account_canonical: EXPECTED_WALLET,
      issued_at: "2026-07-29T10:00:00Z",
      expires_at: "2026-07-29T10:15:00Z",
      single_use: true,
    });
    mocks.verifyChallenge.mockReset().mockResolvedValue({
      challenge_id: CHALLENGE_ID,
      wallet_account_canonical: EXPECTED_WALLET,
      network: "ton-mainnet",
      domain: "tracker.example",
      verified_at: "2026-07-29T10:01:00Z",
      signature_verified: true,
      state_init_address_binding_verified: true,
      public_key_resolved_from_proof_checked_account: true,
      challenge_consumed: true,
      is_ownership_proof: true,
    });
  });

  it("stays fail-closed until a network-scoped run is selected", () => {
    render(<GramOwnershipProofCard />);

    expect(
      (screen.getByRole("button", {
        name: "Connect and verify",
      }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText("Not verified")).toBeTruthy();
  });

  it("requests a scoped ton_proof and verifies the wallet response", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <GramOwnershipProofCard
        expectedWallet={EXPECTED_WALLET}
        expectedNetwork="ton-mainnet"
      />,
    );

    await user.click(screen.getByRole("button", { name: "Connect and verify" }));

    await waitFor(() => {
      expect(mocks.createChallenge).toHaveBeenCalledWith(
        EXPECTED_WALLET,
        expect.any(AbortSignal),
      );
    });
    expect(mocks.ui.setConnectionNetwork).toHaveBeenCalledWith("-239");
    expect(mocks.ui.setConnectRequestParameters).toHaveBeenCalledWith({
      state: "ready",
      value: {
        tonProof: "challenge-payload-that-is-long-enough-for-the-contract",
      },
    });
    expect(mocks.ui.openModal).toHaveBeenCalledOnce();

    mocks.wallet = {
      account: {
        address: EXPECTED_WALLET,
        chain: "-239",
        walletStateInit: "base64-state-init",
      },
      connectItems: {
        tonProof: {
          name: "ton_proof",
          proof: {
            timestamp: 1785320000,
            domain: { lengthBytes: 15, value: "tracker.example" },
            payload: "challenge-payload-that-is-long-enough-for-the-contract",
            signature: "base64-signature",
          },
        },
      },
    };
    rerender(
      <GramOwnershipProofCard
        expectedWallet={EXPECTED_WALLET}
        expectedNetwork="ton-mainnet"
      />,
    );

    await waitFor(() => {
      expect(mocks.verifyChallenge).toHaveBeenCalledWith(
        CHALLENGE_ID,
        {
          address: EXPECTED_WALLET,
          network: "ton-mainnet",
          wallet_state_init: "base64-state-init",
          proof: mocks.wallet?.connectItems.tonProof.proof,
        },
        expect.any(AbortSignal),
      );
    });
    expect(
      await screen.findByText(
        "Ownership verified. The single-use challenge was consumed and cannot be replayed.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Signature verified")).toBeTruthy();
    expect(screen.getByText("StateInit bound")).toBeTruthy();
    expect(screen.getByText("Public key checked")).toBeTruthy();
    expect(screen.getByText("Challenge consumed")).toBeTruthy();
  });
});
