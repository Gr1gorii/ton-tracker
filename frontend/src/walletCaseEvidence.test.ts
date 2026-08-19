import { describe, expect, it } from "vitest";

import {
  parseWalletCaseEvidenceCatalog,
  parseWalletCaseEvidenceVerification,
} from "./walletCaseEvidence";
import {
  BOC_DIGEST,
  evidenceCatalogFixture,
  inclusionProvenanceFixture,
  partialEvidenceVerificationFixture,
  queuedEvidenceVerificationFixture,
  retryWaitEvidenceVerificationFixture,
  runningEvidenceVerificationFixture,
  succeededEvidenceVerificationFixture,
} from "./test/walletCaseEvidenceFixtures";

describe("Wallet Case Evidence parser", () => {
  it("accepts nullable pending levels and a queued bounded retry_wait", () => {
    const queued = parseWalletCaseEvidenceVerification(queuedEvidenceVerificationFixture());
    expect(queued.steps.every((step) => step.evidence_level === null)).toBe(true);

    const retry = parseWalletCaseEvidenceVerification(retryWaitEvidenceVerificationFixture());
    expect(retry.state).toBe("queued");
    expect(retry.stage).toBe("retry_wait");
    expect(retry.retry).toMatchObject({ attempt: 1, max_attempts: 3 });
  });

  it("rejects a retry with no remaining bounded attempt", () => {
    const value = retryWaitEvidenceVerificationFixture();
    value.retry!.attempt = value.retry!.max_attempts;
    expect(() => parseWalletCaseEvidenceVerification(value)).toThrow(/budget is exhausted/);
  });

  it("accepts only active proof stages while a verification is running", () => {
    const running = queuedEvidenceVerificationFixture();
    running.state = "running";
    running.stage = "validating";
    running.started_at = running.created_at;
    expect(parseWalletCaseEvidenceVerification(structuredClone(running)).stage).toBe("validating");

    running.stage = "queued";
    expect(() => parseWalletCaseEvidenceVerification(running)).toThrow(/Running Evidence verification has an invalid stage/);
  });

  it("binds the cancellation flag to the durable lifecycle state", () => {
    const succeeded = succeededEvidenceVerificationFixture();
    succeeded.cancel_requested = true;
    expect(() => parseWalletCaseEvidenceVerification(succeeded)).toThrow(/cancellation flag is inconsistent/);

    const cancelled = queuedEvidenceVerificationFixture({
      state: "cancelled",
      stage: "terminal",
      cancel_requested: true,
      completed_at: "2026-08-10T12:00:01Z",
      updated_at: "2026-08-10T12:00:01Z",
      message: "Evidence verification was cancelled before execution.",
    });
    expect(parseWalletCaseEvidenceVerification(structuredClone(cancelled)).state).toBe("cancelled");
    cancelled.cancel_requested = false;
    expect(() => parseWalletCaseEvidenceVerification(cancelled)).toThrow(/cancellation flag is inconsistent/);
  });

  it("round-trips a partial usable result with error null and an explicit limitation", () => {
    const fixture = partialEvidenceVerificationFixture();
    const parsed = parseWalletCaseEvidenceVerification(structuredClone(fixture));

    expect(parsed.state).toBe("partial");
    expect(parsed.error).toBeNull();
    expect(parsed.result?.evidence_digests.boc_verification).toBe(BOC_DIGEST);
    expect(parsed.result?.evidence_digests.block_inclusion).toBeNull();
    expect(parsed.result?.inclusion_provenance).toBeNull();
    expect(parsed.limitations.map((item) => item.code)).toContain("verification_partial");
  });

  it("publishes exact pinned-checkpoint provenance after block inclusion", () => {
    const parsed = parseWalletCaseEvidenceVerification(
      structuredClone(succeededEvidenceVerificationFixture()),
    );
    expect(parsed.inclusion_provenance).toMatchObject({
      contract_version: "ton_transaction_inclusion_v2",
      network: "ton-mainnet",
      verifier_policy_id: "ton_liteserver_checkpoint_strict_2026_08_v2",
      trust_level: 0,
      canonical_block_chain_verified_at_capture: true,
      checkpoint_to_observed_head_transcript_persisted: false,
    });
    expect(parsed.result?.inclusion_provenance).toEqual(parsed.inclusion_provenance);
    expect(parsed.result?.inclusion_provenance?.trusted_checkpoint.seqno).toBe(46_894_135);
  });

  it("keeps pinned inclusion provenance outside terminal results for every progress-three state", () => {
    const running = runningEvidenceVerificationFixture(3);
    const retryWait = runningEvidenceVerificationFixture(3, {
      state: "queued",
      stage: "retry_wait",
      retry: {
        attempt: 2,
        max_attempts: 4,
        retry_at: "2026-08-10T12:01:30Z",
        reason_code: "provider_unavailable",
        message_safe: "Native ledger construction will retry.",
      },
      message: "Completed inclusion evidence is preserved while the ledger retries.",
    });
    const cancelled = runningEvidenceVerificationFixture(3, {
      state: "cancelled",
      stage: "terminal",
      cancel_requested: true,
      message: "Verification was cancelled after block inclusion.",
      updated_at: "2026-08-10T12:00:31Z",
      completed_at: "2026-08-10T12:00:31Z",
    });

    for (const value of [running, retryWait, cancelled]) {
      const parsed = parseWalletCaseEvidenceVerification(structuredClone(value));
      expect(parsed.result).toBeNull();
      expect(parsed.inclusion_provenance?.trusted_checkpoint.seqno).toBe(46_894_135);

      const missing = structuredClone(value);
      missing.inclusion_provenance = null;
      expect(() => parseWalletCaseEvidenceVerification(missing)).toThrow(
        /completed proof prefix/,
      );
    }
  });

  it.each([
    ["trust level", (value: any) => { value.result.inclusion_provenance.trust_level = 1; }],
    ["policy", (value: any) => { value.result.inclusion_provenance.verifier_policy_id = "legacy_unpinned_v1"; }],
    ["canonical flag", (value: any) => { value.result.inclusion_provenance.canonical_block_chain_verified_at_capture = false; }],
    ["transcript flag", (value: any) => { value.result.inclusion_provenance.checkpoint_to_observed_head_transcript_persisted = true; }],
    ["checkpoint", (value: any) => { value.result.inclusion_provenance.trusted_checkpoint.root_hash = "f".repeat(64); }],
    ["raw field", (value: any) => { value.result.inclusion_provenance.block_proof_boc_hex = "00"; }],
  ])("rejects incoherent inclusion provenance %s", (_label, mutate) => {
    const value = structuredClone(succeededEvidenceVerificationFixture());
    mutate(value);
    expect(() => parseWalletCaseEvidenceVerification(value)).toThrow();
  });

  it("binds inclusion provenance presence to the completed proof prefix and selected network", () => {
    const tooEarly = partialEvidenceVerificationFixture();
    tooEarly.result!.inclusion_provenance = inclusionProvenanceFixture();
    expect(() => parseWalletCaseEvidenceVerification(tooEarly)).toThrow(/inclusion/);

    const missing = succeededEvidenceVerificationFixture();
    missing.progress.current = 3;
    missing.steps[3] = {
      code: "native_ledger",
      state: "pending",
      evidence_level: null,
      evidence_digest_sha256: null,
      completed_at: null,
    };
    missing.state = "partial";
    missing.limitations = [{ code: "verification_partial", message: "Block inclusion completed; ledger construction stopped." }];
    missing.result!.evidence_digests.native_ledger = null;
    missing.result!.inclusion_provenance = null;
    missing.result!.native_ledger = null;
    expect(() => parseWalletCaseEvidenceVerification(missing)).toThrow(/inclusion/);

    const wrongNetwork = succeededEvidenceVerificationFixture();
    wrongNetwork.result!.inclusion_provenance = inclusionProvenanceFixture("ton-testnet");
    expect(() => parseWalletCaseEvidenceVerification(wrongNetwork)).toThrow(/inclusion/);
  });

  it.each([
    ["partial error", (value: any) => { value.error = { code: "unsafe", message_safe: "Not the partial contract.", retryable: false }; }],
    ["partial limitation", (value: any) => { value.limitations = []; }],
    ["out-of-order steps", (value: any) => {
      value.steps[0] = { code: "trace_capture", state: "pending", evidence_level: null, evidence_digest_sha256: null, completed_at: null };
      value.progress.current = 1;
      value.result.evidence_digests.trace_capture = null;
    }],
    ["result digest", (value: any) => { value.result.evidence_digests.boc_verification = "f".repeat(64); }],
  ])("fails closed for inconsistent %s", (_label, mutate) => {
    const value = structuredClone(partialEvidenceVerificationFixture());
    mutate(value);
    expect(() => parseWalletCaseEvidenceVerification(value)).toThrow();
  });

  it("requires exact response fields at every trust boundary", () => {
    const verification: any = structuredClone(queuedEvidenceVerificationFixture());
    verification.raw_boc = "not public";
    expect(() => parseWalletCaseEvidenceVerification(verification)).toThrow(/fields are invalid/);

    const step: any = structuredClone(queuedEvidenceVerificationFixture());
    step.steps[0].internal_id = 123;
    expect(() => parseWalletCaseEvidenceVerification(step)).toThrow(/fields are invalid/);

    const catalog: any = structuredClone(evidenceCatalogFixture());
    catalog.run_id = 99;
    expect(() => parseWalletCaseEvidenceCatalog(catalog)).toThrow(/fields are invalid/);
  });

  it("rejects an otherwise canonical Evidence wallet outside TON workchains 0 and -1", () => {
    const verification = queuedEvidenceVerificationFixture();
    verification.provenance.transaction.wallet_account_canonical = `1:${"a".repeat(64)}`;
    expect(() => parseWalletCaseEvidenceVerification(verification)).toThrow(
      /Evidence wallet account is invalid/,
    );
  });

  it("accepts true total counts beyond the 50-row catalog window", () => {
    const value = evidenceCatalogFixture({
      verifications: [succeededEvidenceVerificationFixture()],
      total: 51,
    });
    const parsed = parseWalletCaseEvidenceCatalog(value);
    expect(parsed.aggregate).toMatchObject({ total: 51, returned_count: 1, counts_scope: "returned_revalidated", succeeded: 1 });
    expect(parsed.truncated).toBe(true);
    expect(parsed.verifications).toHaveLength(1);
  });

  it("binds unavailable readiness to an explicit runner or runtime limitation", () => {
    const unavailable = evidenceCatalogFixture({
      transactionVerificationAvailable: false,
      limitations: [
        { code: "evidence_runner_unavailable", message: "The durable runner is unavailable." },
        { code: "report_not_built", message: "A Wallet Case report is not built yet." },
      ],
    });
    expect(parseWalletCaseEvidenceCatalog(unavailable).readiness.transaction_verification_available).toBe(false);

    const unexplained = evidenceCatalogFixture({ transactionVerificationAvailable: false });
    expect(() => parseWalletCaseEvidenceCatalog(unexplained)).toThrow(/availability is inconsistent/);
  });

  it("requires the explicit non-verifiable limitation for a mock snapshot", () => {
    const mock = evidenceCatalogFixture({
      transactionVerificationAvailable: false,
      limitations: [
        { code: "demo_evidence_not_verifiable", message: "Demo evidence cannot enter live verification." },
        { code: "report_not_built", message: "A Wallet Case report is not built yet." },
      ],
    });
    mock.snapshot!.data_mode = "mock";
    expect(parseWalletCaseEvidenceCatalog(structuredClone(mock)).readiness.transaction_verification_available).toBe(false);

    mock.limitations = mock.limitations.filter((item) => item.code !== "demo_evidence_not_verifiable");
    expect(() => parseWalletCaseEvidenceCatalog(mock)).toThrow(/availability is inconsistent/);
  });

  it.each([
    ["returned count", (value: any) => { value.aggregate.returned_count = 2; }],
    ["count scope", (value: any) => { value.aggregate.counts_scope = "all_history"; }],
    ["truncation", (value: any) => { value.truncated = false; }],
    ["state totals", (value: any) => { value.aggregate.queued += 1; }],
    ["highest level", (value: any) => { value.readiness.highest_evidence_level = "locally_verified"; }],
    ["report boundary", (value: any) => { value.limitations = value.limitations.filter((item: any) => item.code !== "report_not_built"); }],
  ])("rejects an inconsistent catalog %s", (_label, mutate) => {
    const value = structuredClone(evidenceCatalogFixture({
      verifications: [succeededEvidenceVerificationFixture()],
      total: 51,
    }));
    mutate(value);
    expect(() => parseWalletCaseEvidenceCatalog(value)).toThrow();
  });

  it("requires all native-ledger truth flags and a matching digest", () => {
    const missingFlag: any = structuredClone(succeededEvidenceVerificationFixture());
    delete missingFlag.result.native_ledger.used_by_pnl;
    expect(() => parseWalletCaseEvidenceVerification(missingFlag)).toThrow(/fields are invalid/);

    const mismatch = structuredClone(succeededEvidenceVerificationFixture());
    mismatch.result!.native_ledger!.evidence_digest_sha256 = "f".repeat(64);
    expect(() => parseWalletCaseEvidenceVerification(mismatch)).toThrow(/does not match/);
  });
});
