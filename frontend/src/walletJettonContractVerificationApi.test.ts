import { afterEach, describe, expect, it, vi } from "vitest";

import {
  API_BASE,
  getWalletJettonContractVerifications,
  verifyWalletJettonContractRelationship,
} from "./api";

const JETTON_WALLET = `0:${"2".repeat(64)}`;
const JETTON_MASTER = `0:${"3".repeat(64)}`;

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("jetton contract verification API", () => {
  it("reads immutable evidence with no-store and the supplied signal", async () => {
    const payload = { contract_version: "ton_jetton_contract_verification_v1" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      getWalletJettonContractVerifications(25, controller.signal),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/25/jetton-contract-verifications`,
      { cache: "no-store", signal: controller.signal },
    );
  });

  it("verifies only the exact selected wallet/master relation", async () => {
    const payload = { contract_version: "ton_jetton_contract_verification_v1" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const controller = new AbortController();

    await expect(
      verifyWalletJettonContractRelationship(
        25,
        JETTON_WALLET,
        JETTON_MASTER,
        controller.signal,
      ),
    ).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/wallets/ingest/25/jetton-contract-verifications`,
      {
        method: "POST",
        cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jetton_wallet_account_canonical: JETTON_WALLET,
          jetton_master_account_canonical: JETTON_MASTER,
        }),
        signal: controller.signal,
      },
    );
  });
});
