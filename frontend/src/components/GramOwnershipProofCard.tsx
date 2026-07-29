import {
  CHAIN,
  useTonConnectUI,
  useTonWallet,
  type TonProofItemReply,
  type TonProofItemReplySuccess,
} from "@tonconnect/ui-react";
import {
  Check,
  CheckCircle,
  Fingerprint,
  LinkBreak,
  LockKey,
  SpinnerGap,
  WarningCircle,
  Wallet,
} from "@phosphor-icons/react";
import { useEffect, useRef, useState } from "react";

import {
  createWalletOwnershipChallenge,
  verifyWalletOwnershipChallenge,
} from "../api";
import type {
  WalletOwnershipChallengeResponse,
  WalletOwnershipNetwork,
  WalletOwnershipProofResponse,
} from "../types";

type OwnershipPhase =
  | "idle"
  | "preparing"
  | "awaiting_wallet"
  | "verifying"
  | "verified"
  | "error";

interface GramOwnershipProofCardProps {
  expectedWallet?: string | null;
  expectedNetwork?: "ton-mainnet" | "ton-testnet" | "ton-unknown";
}

function isProofSuccess(
  reply: TonProofItemReply | undefined,
): reply is TonProofItemReplySuccess {
  return Boolean(reply && "proof" in reply);
}

function networkFromChain(chain: string): WalletOwnershipNetwork | null {
  if (chain === CHAIN.MAINNET) return "ton-mainnet";
  if (chain === CHAIN.TESTNET) return "ton-testnet";
  return null;
}

function chainFromNetwork(network: WalletOwnershipNetwork): CHAIN {
  return network === "ton-mainnet" ? CHAIN.MAINNET : CHAIN.TESTNET;
}

function shortAddress(value?: string | null): string {
  if (!value) return "—";
  return value.length > 22
    ? `${value.slice(0, 11)}…${value.slice(-8)}`
    : value;
}

function readableError(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function GramOwnershipProofCard({
  expectedWallet,
  expectedNetwork,
}: GramOwnershipProofCardProps) {
  const [tonConnectUI] = useTonConnectUI();
  const wallet = useTonWallet();
  const [phase, setPhase] = useState<OwnershipPhase>("idle");
  const [challenge, setChallenge] =
    useState<WalletOwnershipChallengeResponse | null>(null);
  const [verification, setVerification] =
    useState<WalletOwnershipProofResponse | null>(null);
  const [message, setMessage] = useState(
    "Create a single-use challenge, connect the matching wallet and approve the signature request.",
  );
  const requestController = useRef<AbortController | null>(null);
  const verificationKey = useRef("");

  const canVerify = Boolean(
    expectedWallet &&
      (expectedNetwork === "ton-mainnet" || expectedNetwork === "ton-testnet"),
  );

  useEffect(() => {
    requestController.current?.abort();
    requestController.current = null;
    verificationKey.current = "";
    setChallenge(null);
    setVerification(null);
    setPhase("idle");
    setMessage(
      "Create a single-use challenge, connect the matching wallet and approve the signature request.",
    );
  }, [expectedWallet, expectedNetwork]);

  useEffect(
    () => () => {
      requestController.current?.abort();
    },
    [],
  );

  useEffect(() => {
    if (!wallet || !challenge || phase !== "awaiting_wallet") return;

    const proofReply = wallet.connectItems?.tonProof;
    if (!isProofSuccess(proofReply)) {
      setPhase("error");
      setMessage(
        "The connected wallet did not return ton_proof. Try another compatible wallet or reconnect.",
      );
      return;
    }
    if (proofReply.proof.payload !== challenge.payload) {
      setPhase("error");
      setMessage(
        "The wallet returned a proof for a different challenge. Restart verification to obtain a fresh nonce.",
      );
      return;
    }

    const network = networkFromChain(wallet.account.chain);
    if (!network || network !== challenge.expected_network) {
      setPhase("error");
      setMessage("The connected wallet is on a different TON network.");
      return;
    }

    const key = `${challenge.challenge_id}:${wallet.account.address}:${proofReply.proof.signature}`;
    if (verificationKey.current === key) return;
    verificationKey.current = key;
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    setPhase("verifying");
    setMessage(
      "The signature is being checked against the challenge, wallet StateInit and proof-scoped public key.",
    );

    void verifyWalletOwnershipChallenge(
      challenge.challenge_id,
      {
        address: wallet.account.address,
        network,
        wallet_state_init: wallet.account.walletStateInit,
        proof: proofReply.proof,
      },
      controller.signal,
    )
      .then((result) => {
        if (controller.signal.aborted) return;
        setVerification(result);
        setPhase("verified");
        setMessage(
          "Ownership verified. The single-use challenge was consumed and cannot be replayed.",
        );
        tonConnectUI.setConnectRequestParameters(null);
      })
      .catch((error) => {
        if (controller.signal.aborted) return;
        setPhase("error");
        setMessage(readableError(error, "Ownership verification failed."));
      });
  }, [challenge, phase, tonConnectUI, wallet]);

  async function startVerification() {
    if (
      !expectedWallet ||
      (expectedNetwork !== "ton-mainnet" && expectedNetwork !== "ton-testnet")
    ) {
      setPhase("error");
      setMessage("Load a network-scoped wallet run before requesting ownership proof.");
      return;
    }

    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    verificationKey.current = "";
    setVerification(null);
    setChallenge(null);
    setPhase("preparing");
    setMessage("Creating a short-lived, single-use ownership challenge…");
    tonConnectUI.setConnectRequestParameters({ state: "loading" });

    try {
      const nextChallenge = await createWalletOwnershipChallenge(
        expectedWallet,
        controller.signal,
      );
      if (controller.signal.aborted) return;

      if (tonConnectUI.connected) {
        await tonConnectUI.disconnect();
      }
      tonConnectUI.setConnectionNetwork(
        chainFromNetwork(nextChallenge.expected_network),
      );
      tonConnectUI.setConnectRequestParameters({
        state: "ready",
        value: { tonProof: nextChallenge.payload },
      });
      setChallenge(nextChallenge);
      setPhase("awaiting_wallet");
      setMessage(
        "Choose the expected wallet and approve the proof request. No transaction or asset transfer is requested.",
      );
      await tonConnectUI.openModal();
    } catch (error) {
      if (controller.signal.aborted) return;
      tonConnectUI.setConnectRequestParameters(null);
      setPhase("error");
      setMessage(readableError(error, "Could not start wallet verification."));
    }
  }

  async function disconnectWallet() {
    try {
      await tonConnectUI.disconnect();
    } catch (error) {
      setPhase("error");
      setMessage(readableError(error, "Could not disconnect the wallet."));
    }
  }

  const busy = phase === "preparing" || phase === "verifying";
  const verified = phase === "verified" && verification !== null;
  const walletProof = wallet?.connectItems?.tonProof;
  const signatureReturned = Boolean(
    challenge &&
      isProofSuccess(walletProof) &&
      walletProof.proof.payload === challenge.payload,
  );

  return (
    <article className={`ownership-proof-card phase-${phase}`}>
      <header className="ownership-proof-header">
        <span className="ownership-proof-icon"><Fingerprint size={27} /></span>
        <div>
          <small>TON Connect · cryptographic ownership</small>
          <h2>Prove control of this wallet</h2>
          <p>
            The proof binds one wallet address, this app domain, the selected
            TON network and a server-issued nonce.
          </p>
        </div>
        <span className={verified ? "ownership-badge is-verified" : "ownership-badge"}>
          {busy ? <SpinnerGap className="spin" size={16} /> : verified ? <CheckCircle size={16} weight="fill" /> : phase === "error" ? <WarningCircle size={16} weight="fill" /> : <LockKey size={16} />}
          {verified ? "Verified" : phase === "error" ? "Needs attention" : busy ? "Checking" : "Not verified"}
        </span>
      </header>

      <div className="ownership-steps" aria-label="Ownership verification steps">
        <OwnershipStep label="Scoped challenge" complete={Boolean(challenge)} active={phase === "preparing"} />
        <OwnershipStep label="Wallet signature" complete={signatureReturned} active={phase === "awaiting_wallet"} />
        <OwnershipStep label="Backend verification" complete={verified} active={phase === "verifying"} />
      </div>

      <div className={phase === "error" ? "ownership-message is-error" : verified ? "ownership-message is-success" : "ownership-message"} role="status">
        {phase === "error" ? <WarningCircle size={19} weight="fill" /> : verified ? <CheckCircle size={19} weight="fill" /> : busy ? <SpinnerGap className="spin" size={19} /> : <LockKey size={19} />}
        <span>{message}</span>
      </div>

      <dl className="ownership-facts">
        <div><dt>Expected wallet</dt><dd title={expectedWallet ?? undefined}>{shortAddress(expectedWallet)}</dd></div>
        <div><dt>Network</dt><dd>{expectedNetwork ?? "—"}</dd></div>
        <div><dt>Connected wallet</dt><dd title={wallet?.account.address}>{shortAddress(wallet?.account.address)}</dd></div>
        <div><dt>Proof domain</dt><dd>{verification?.domain ?? challenge?.expected_domain ?? "—"}</dd></div>
      </dl>

      {challenge && !verified && (
        <div className="ownership-challenge-meta">
          <span>Single-use challenge</span>
          <strong>{challenge.challenge_id}</strong>
          <small>Expires {new Date(challenge.expires_at).toLocaleString()}</small>
        </div>
      )}

      {verification && (
        <div className="ownership-verification-grid">
          <span><Check size={15} weight="bold" />Signature verified</span>
          <span><Check size={15} weight="bold" />StateInit bound</span>
          <span><Check size={15} weight="bold" />Public key checked</span>
          <span><Check size={15} weight="bold" />Challenge consumed</span>
        </div>
      )}

      <footer className="ownership-actions">
        <button
          className="button-primary"
          type="button"
          onClick={startVerification}
          disabled={!canVerify || busy || verified}
        >
          {busy ? <SpinnerGap className="spin" size={18} /> : <Wallet size={18} />}
          {verified ? "Ownership verified" : phase === "awaiting_wallet" ? "Restart verification" : "Connect and verify"}
        </button>
        {wallet && (
          <button className="button-secondary" type="button" onClick={disconnectWallet} disabled={busy}>
            <LinkBreak size={17} />Disconnect
          </button>
        )}
        <p>No seed phrase, private key, transaction or transfer is requested.</p>
      </footer>
    </article>
  );
}

function OwnershipStep({
  label,
  complete,
  active,
}: {
  label: string;
  complete: boolean;
  active: boolean;
}) {
  return (
    <span className={complete ? "is-complete" : active ? "is-active" : ""}>
      <i>{complete ? <Check size={13} weight="bold" /> : active ? <SpinnerGap className="spin" size={13} /> : null}</i>
      {label}
    </span>
  );
}
