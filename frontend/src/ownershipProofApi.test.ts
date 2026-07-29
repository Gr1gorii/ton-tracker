import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE,
  createWalletOwnershipChallenge,
  verifyWalletOwnershipChallenge,
} from "./api";
import type { WalletOwnershipProofRequest } from "./types";

const CHALLENGE_ID = "2063e557-b4fc-478f-b861-18fb82754f2b";
const EXPECTED_WALLET = `0:${"4".repeat(64)}`;

describe("wallet ownership API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("creates a no-store challenge bound to the selected wallet", async () => {
    const payload = {
      challenge_id: CHALLENGE_ID,
      payload: "challenge-payload-that-is-long-enough-for-the-contract",
      expected_domain: "tracker.example",
      expected_network: "ton-mainnet",
      expected_wallet_account_canonical: EXPECTED_WALLET,
      issued_at: "2026-07-29T10:00:00Z",
      expires_at: "2026-07-29T10:15:00Z",
      single_use: true,
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      createWalletOwnershipChallenge(EXPECTED_WALLET, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ownership/challenges`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify({ expected_wallet: EXPECTED_WALLET }),
        signal: controller.signal,
      },
    );
  });

  it("submits the wallet proof to the exact single-use challenge", async () => {
    const request: WalletOwnershipProofRequest = {
      address: EXPECTED_WALLET,
      network: "ton-mainnet",
      wallet_state_init: "base64-state-init",
      proof: {
        timestamp: 1785320000,
        domain: { lengthBytes: 15, value: "tracker.example" },
        payload: "challenge-payload-that-is-long-enough-for-the-contract",
        signature: "c2lnbmF0dXJl",
      },
    };
    const payload = {
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
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      verifyWalletOwnershipChallenge(CHALLENGE_ID, request),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ownership/challenges/${CHALLENGE_ID}/verify`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        cache: "no-store",
        body: JSON.stringify(request),
        signal: undefined,
      },
    );
  });

  it("surfaces a replay-safe backend conflict without hiding its reason", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ detail: "Ownership challenge is absent or consumed." }),
          { status: 409, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(
      createWalletOwnershipChallenge(EXPECTED_WALLET),
    ).rejects.toThrow("Ownership challenge is absent or consumed.");
  });
});
