import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelWalletCaseEvidenceVerification,
  createWalletCaseEvidenceVerification,
  getWalletCaseEvidence,
  getWalletCaseEvidenceVerification,
  WalletCaseEvidenceApiError,
} from "./walletCaseEvidenceApi";
import { ACTIVITY_ID } from "./test/walletCaseActivityFixtures";
import { CASE_ID, IDEMPOTENCY_KEY, SYNC_ID } from "./test/walletCaseFixtures";
import {
  evidenceCatalogFixture,
  partialEvidenceVerificationFixture,
  queuedEvidenceVerificationFixture,
  VERIFICATION_ID,
} from "./test/walletCaseEvidenceFixtures";

function jsonResponse(payload: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (input instanceof URL) return input;
  if (typeof input === "string") return new URL(input, "http://localhost");
  return new URL(input.url);
}

afterEach(() => vi.unstubAllGlobals());

describe("Wallet Case Evidence API", () => {
  it("reads the strict snapshot catalog with no-store and the supplied AbortSignal", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(evidenceCatalogFixture()));
    vi.stubGlobal("fetch", fetchMock);

    const result = await getWalletCaseEvidence(CASE_ID, SYNC_ID, controller.signal);

    expect(result.snapshot?.public_id).toBe(SYNC_ID);
    const [input, init] = fetchMock.mock.calls[0];
    expect(requestUrl(input).pathname).toBe(`/api/v1/cases/${CASE_ID}/evidence`);
    expect(requestUrl(input).searchParams.getAll("snapshot")).toEqual([SYNC_ID]);
    expect(init).toMatchObject({ cache: "no-store", signal: controller.signal });
  });

  it("enqueues only the locked policy with a UUIDv4 idempotency key", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(queuedEvidenceVerificationFixture(), 202, {
      Location: `/api/v1/cases/${CASE_ID}/evidence/verifications/${VERIFICATION_ID}`,
      "Retry-After": "1",
    }));
    vi.stubGlobal("fetch", fetchMock);

    await createWalletCaseEvidenceVerification(CASE_ID, {
      snapshot_public_id: SYNC_ID,
      activity_public_id: ACTIVITY_ID,
      policy: "transaction_inclusion_v1",
    }, IDEMPOTENCY_KEY, controller.signal);

    const [input, init] = fetchMock.mock.calls[0];
    expect(requestUrl(input).pathname).toBe(`/api/v1/cases/${CASE_ID}/evidence/verifications`);
    expect(init).toMatchObject({
      method: "POST",
      cache: "no-store",
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": IDEMPOTENCY_KEY,
      },
    });
    expect(JSON.parse(String(init.body))).toEqual({
      snapshot_public_id: SYNC_ID,
      activity_public_id: ACTIVITY_ID,
      policy: "transaction_inclusion_v1",
    });
  });

  it("parses a route-shaped partial response without inventing an error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(partialEvidenceVerificationFixture())));

    const parsed = await getWalletCaseEvidenceVerification(CASE_ID, VERIFICATION_ID);

    expect(parsed.state).toBe("partial");
    expect(parsed.error).toBeNull();
    expect(parsed.result).not.toBeNull();
    expect(parsed.limitations.some((entry) => entry.code === "verification_partial")).toBe(true);
  });

  it("posts cancellation to the durable verification resource with no-store", async () => {
    const cancelled = queuedEvidenceVerificationFixture({
      state: "cancelled",
      stage: "terminal",
      status_version: 2,
      cancel_requested: true,
      message: "Evidence verification was cancelled before execution.",
      updated_at: "2026-08-10T12:00:01Z",
      completed_at: "2026-08-10T12:00:01Z",
    });
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(cancelled));
    vi.stubGlobal("fetch", fetchMock);

    await cancelWalletCaseEvidenceVerification(CASE_ID, VERIFICATION_ID);

    const [input, init] = fetchMock.mock.calls[0];
    expect(requestUrl(input).pathname).toBe(`/api/v1/cases/${CASE_ID}/evidence/verifications/${VERIFICATION_ID}/cancel`);
    expect(init).toMatchObject({ method: "POST", cache: "no-store" });
  });

  it("fails closed when a response crosses case, snapshot, Activity or verification scope", async () => {
    const wrongCase = queuedEvidenceVerificationFixture({ case_public_id: "550e8400-e29b-41d4-a716-446655440099" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(wrongCase, 202)));
    await expect(createWalletCaseEvidenceVerification(CASE_ID, {
      snapshot_public_id: SYNC_ID,
      activity_public_id: ACTIVITY_ID,
      policy: "transaction_inclusion_v1",
    }, IDEMPOTENCY_KEY)).rejects.toThrow(/does not match/);

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(queuedEvidenceVerificationFixture({ public_id: "550e8400-e29b-41d4-a716-446655440099" }))));
    await expect(getWalletCaseEvidenceVerification(CASE_ID, VERIFICATION_ID)).rejects.toThrow(/does not match/);
  });

  it("preserves the safe error code, retryability and Retry-After", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: {
        code: "evidence_runner_unavailable",
        message_safe: "Transaction evidence verification is temporarily unavailable.",
        retryable: true,
      },
    }, 503, { "Retry-After": "5" })));

    const error = await getWalletCaseEvidenceVerification(CASE_ID, VERIFICATION_ID).catch((caught) => caught);

    expect(error).toBeInstanceOf(WalletCaseEvidenceApiError);
    expect(error).toMatchObject({
      status: 503,
      code: "evidence_runner_unavailable",
      retryable: true,
      retryAfterMs: 5_000,
      message: "Transaction evidence verification is temporarily unavailable.",
    });
  });

  it("parses only a canonical active verification UUID from a conflict", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: {
        code: "evidence_verification_already_active",
        message_safe: "This selection already has active verification.",
        retryable: false,
        active_verification_public_id: VERIFICATION_ID,
      },
    }, 409)));

    const error = await createWalletCaseEvidenceVerification(CASE_ID, {
      snapshot_public_id: SYNC_ID,
      activity_public_id: ACTIVITY_ID,
      policy: "transaction_inclusion_v1",
    }, IDEMPOTENCY_KEY).catch((caught) => caught);
    expect(error).toMatchObject({
      code: "evidence_verification_already_active",
      activeVerificationPublicId: VERIFICATION_ID,
    });

    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: {
        code: "evidence_verification_already_active",
        message_safe: "This selection already has active verification.",
        retryable: false,
        active_verification_public_id: "1",
      },
    }, 409)));
    const malformed = await createWalletCaseEvidenceVerification(CASE_ID, {
      snapshot_public_id: SYNC_ID,
      activity_public_id: ACTIVITY_ID,
      policy: "transaction_inclusion_v1",
    }, IDEMPOTENCY_KEY).catch((caught) => caught);
    expect(malformed.activeVerificationPublicId).toBeNull();
  });

  it("rejects noncanonical identifiers before issuing a request", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(getWalletCaseEvidence("1", null)).rejects.toThrow(/canonical UUIDv4/);
    await expect(createWalletCaseEvidenceVerification(CASE_ID, {
      snapshot_public_id: SYNC_ID,
      activity_public_id: "act_1",
      policy: "transaction_inclusion_v1",
    }, IDEMPOTENCY_KEY)).rejects.toThrow(/Activity ID/);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
