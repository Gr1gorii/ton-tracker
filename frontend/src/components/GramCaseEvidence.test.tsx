// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { caseEvidenceSearch } from "../caseEvidenceQuery";
import { WalletCaseEvidenceApiError } from "../walletCaseEvidenceApi";
import { ACTIVITY_ID, activityDetailFixture } from "../test/walletCaseActivityFixtures";
import { CASE_ID, SYNC_ID, walletCaseFixture } from "../test/walletCaseFixtures";
import {
  evidenceCatalogFixture,
  liveEvidenceActivityDetailFixture,
  partialEvidenceVerificationFixture,
  queuedEvidenceVerificationFixture,
  runningEvidenceVerificationFixture,
  SECOND_VERIFICATION_ID,
  succeededEvidenceVerificationFixture,
  VERIFICATION_ID,
} from "../test/walletCaseEvidenceFixtures";

const evidenceApiMocks = vi.hoisted(() => ({
  getWalletCaseEvidence: vi.fn(),
  getWalletCaseEvidenceVerification: vi.fn(),
  createWalletCaseEvidenceVerification: vi.fn(),
  cancelWalletCaseEvidenceVerification: vi.fn(),
}));
const caseApiMocks = vi.hoisted(() => ({ getWalletCaseActivityDetail: vi.fn() }));

vi.mock("../walletCaseEvidenceApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../walletCaseEvidenceApi")>()),
  ...evidenceApiMocks,
}));
vi.mock("../walletCaseApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../walletCaseApi")>()),
  ...caseApiMocks,
}));

import GramCaseEvidence from "./GramCaseEvidence";

function selectedPath(verification: string | null = null): string {
  return `/cases/${CASE_ID}/evidence${caseEvidenceSearch({
    snapshot: SYNC_ID,
    activity: ACTIVITY_ID,
    verification,
  })}`;
}

function liveWalletCase() {
  return walletCaseFixture({ overrides: { data_environment: "live" } });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState({}, "", selectedPath());
  evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture());
  caseApiMocks.getWalletCaseActivityDetail.mockResolvedValue(liveEvidenceActivityDetailFixture());
  evidenceApiMocks.createWalletCaseEvidenceVerification.mockResolvedValue(queuedEvidenceVerificationFixture());
  evidenceApiMocks.getWalletCaseEvidenceVerification.mockResolvedValue(succeededEvidenceVerificationFixture());
});

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  document.documentElement.removeAttribute("data-theme");
});

describe("GramCaseEvidence", () => {
  it("fails an unknown, duplicated or padded Evidence query closed before fetching", async () => {
    const invalidPath = `/cases/${CASE_ID}/evidence?snapshot=${SYNC_ID}&snapshot=${SYNC_ID}`;
    window.history.replaceState({}, "", invalidPath);
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    expect((await screen.findByRole("alert")).textContent).toContain("more than one “snapshot” parameter");
    expect(evidenceApiMocks.getWalletCaseEvidence).not.toHaveBeenCalled();
    expect(caseApiMocks.getWalletCaseActivityDetail).not.toHaveBeenCalled();
    expect(`${window.location.pathname}${window.location.search}`).toBe(invalidPath);
  });

  it("blocks the Verify action when the durable runner is unavailable", async () => {
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({
      transactionVerificationAvailable: false,
      limitations: [
        { code: "evidence_runner_unavailable", message: "The local evidence runner is unavailable." },
        { code: "report_not_built", message: "A Wallet Case report is not built yet." },
      ],
    }));
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    expect(await screen.findByText("Unavailable")).toBeTruthy();
    expect(screen.getAllByText("The local evidence runner is unavailable.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Verify transaction evidence" })).toBeNull();
    expect(screen.getByRole("heading", { name: "Report not built yet" })).toBeTruthy();
    expect(evidenceApiMocks.createWalletCaseEvidenceVerification).not.toHaveBeenCalled();
  });

  it("starts an eligible live transaction only from Evidence and pins the durable UUID", async () => {
    const user = userEvent.setup();
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);
    const action = await screen.findByRole("button", { name: "Verify transaction evidence" });

    await user.click(action);

    await waitFor(() => expect(evidenceApiMocks.createWalletCaseEvidenceVerification).toHaveBeenCalledWith(
      CASE_ID,
      {
        snapshot_public_id: SYNC_ID,
        activity_public_id: ACTIVITY_ID,
        policy: "transaction_inclusion_v1",
      },
      expect.stringMatching(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/),
      expect.any(AbortSignal),
    ));
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("verification")).toBe(VERIFICATION_ID));
    await waitFor(() => expect(document.activeElement).toBe(document.getElementById("evidence-progress-title")));
    expect(screen.queryByText(/Run #/)).toBeNull();
    expect(screen.queryByText(/raw BOC/i)).toBeNull();
  });

  it("keeps and focuses the accepted heading while the newly pinned GET is deferred", async () => {
    const pinnedGet = deferred<ReturnType<typeof runningEvidenceVerificationFixture>>();
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockReturnValue(pinnedGet.promise);
    const user = userEvent.setup();
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Verify transaction evidence" }));

    await waitFor(() => expect(new URLSearchParams(window.location.search).get("verification")).toBe(VERIFICATION_ID));
    const heading = await screen.findByRole("heading", { name: "Queued safely" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(screen.queryByText("Loading durable verification…")).toBeNull();

    act(() => pinnedGet.resolve(runningEvidenceVerificationFixture(0)));
    expect(await screen.findByRole("heading", { name: "Capturing transaction trace" })).toBeTruthy();
  });

  it("keeps focus intent through a deferred GET when resuming an omitted active job", async () => {
    const unrelated = succeededEvidenceVerificationFixture({
      activity_public_id: `act_${"2".repeat(64)}`,
    });
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({
      verifications: [unrelated],
      total: 51,
    }));
    evidenceApiMocks.createWalletCaseEvidenceVerification.mockRejectedValue(
      new WalletCaseEvidenceApiError({
        message: "This selection already has active verification.",
        status: 409,
        code: "evidence_verification_already_active",
        retryable: false,
        retryAfterMs: null,
        activeVerificationPublicId: SECOND_VERIFICATION_ID,
      }),
    );
    const resumedGet = deferred<ReturnType<typeof queuedEvidenceVerificationFixture>>();
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockReturnValue(resumedGet.promise);
    const user = userEvent.setup();
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Verify transaction evidence" }));

    await waitFor(() => expect(new URLSearchParams(window.location.search).get("verification")).toBe(SECOND_VERIFICATION_ID));
    expect(await screen.findByText("Loading durable verification…")).toBeTruthy();
    act(() => resumedGet.resolve(queuedEvidenceVerificationFixture({ public_id: SECOND_VERIFICATION_ID })));
    const heading = await screen.findByRole("heading", { name: "Queued safely" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });

  it("labels the catalog peak as returned history rather than selected Activity assurance", async () => {
    const provenOtherActivity = succeededEvidenceVerificationFixture({
      activity_public_id: `act_${"2".repeat(64)}`,
    });
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({
      verifications: [provenOtherActivity],
    }));
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    expect(await screen.findByText("Returned snapshot-history peak")).toBeTruthy();
    expect(screen.getAllByText("Chain inclusion proven").length).toBeGreaterThan(0);
    expect(screen.queryByText("Highest level")).toBeNull();
    expect(screen.getByRole("heading", { name: /Transaction/ })).toBeTruthy();
    expect(screen.getByText("Provider observed")).toBeTruthy();
    expect(screen.getByText("network scoped")).toBeTruthy();
  });

  it("keeps demo transaction and derived transfer selections visibly ineligible", async () => {
    caseApiMocks.getWalletCaseActivityDetail.mockResolvedValue(activityDetailFixture());
    const first = render(<GramCaseEvidence walletCase={walletCaseFixture()} onOpenActivity={vi.fn()} />);

    expect(await screen.findByText("Ineligible")).toBeTruthy();
    expect(screen.getByText(/Demo fixtures cannot be promoted/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Verify transaction evidence/ })).toBeNull();
    first.unmount();

    const transfer = activityDetailFixture();
    transfer.item = {
      ...transfer.item,
      kind: "transfer",
      direction: "in",
      outcome: null,
      transaction: { linkage: "unknown", hash: null, event_id: null },
      details: { kind: "transfer", amount: "1" },
    };
    caseApiMocks.getWalletCaseActivityDetail.mockResolvedValue(transfer);
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    expect(await screen.findByText(/Transfers and swaps are provider-derived actions/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Verify transaction evidence/ })).toBeNull();
  });

  it("renders partial route data as usable artifacts with no fabricated terminal error", async () => {
    const partial = partialEvidenceVerificationFixture();
    window.history.replaceState({}, "", selectedPath(VERIFICATION_ID));
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({ verifications: [partial] }));
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockResolvedValue(partial);
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Partial evidence preserved", level: 2 })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Partial evidence preserved", level: 3 })).toBeTruthy();
    expect(screen.getByText(/Trace capture and local BOC verification succeeded/)).toBeTruthy();
    expect(screen.getAllByText("Locally verified").length).toBeGreaterThan(0);
    expect(screen.queryByText("Unsafe")).toBeNull();
    expect(screen.queryByText("Pinned checkpoint")).toBeNull();
    expect(screen.getByText(/does not create a canonical case report/)).toBeTruthy();
  });

  it("shows the pinned policy while disclosing the missing checkpoint transcript", async () => {
    const succeeded = succeededEvidenceVerificationFixture();
    window.history.replaceState({}, "", selectedPath(VERIFICATION_ID));
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({ verifications: [succeeded] }));
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockResolvedValue(succeeded);
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    expect(await screen.findByText("Pinned checkpoint")).toBeTruthy();
    expect(screen.getByText("ton-mainnet · #46894135")).toBeTruthy();
    expect(screen.getByText("Checkpoint root")).toBeTruthy();
    expect(screen.getByText("3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f")).toBeTruthy();
    expect(screen.getByText("Checkpoint file hash")).toBeTruthy();
    expect(screen.getByText("bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed")).toBeTruthy();
    expect(screen.getByText("ton_liteserver_checkpoint_strict_2026_08_v2")).toBeTruthy();
    expect(screen.getByText(/checkpoint-to-observed-head transcript was not persisted/i)).toBeTruthy();
  });

  it("keeps the pinned inclusion boundary visible after a progress-three cancellation", async () => {
    const cancelled = runningEvidenceVerificationFixture(3, {
      state: "cancelled",
      stage: "terminal",
      cancel_requested: true,
      message: "Verification was cancelled after block inclusion.",
      updated_at: "2026-08-10T12:00:31Z",
      completed_at: "2026-08-10T12:00:31Z",
    });
    window.history.replaceState({}, "", selectedPath(VERIFICATION_ID));
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(
      evidenceCatalogFixture({ verifications: [cancelled] }),
    );
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockResolvedValue(cancelled);
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    expect(await screen.findByRole("heading", { name: "Verification cancelled" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Pinned chain-verification boundary" })).toBeTruthy();
    expect(screen.getByText("ton-mainnet · #46894135")).toBeTruthy();
    expect(screen.queryByText("Verification digest")).toBeNull();
  });

  it("moves focus to the durable verification heading after confirmed cancellation", async () => {
    const queued = queuedEvidenceVerificationFixture();
    const cancelled = queuedEvidenceVerificationFixture({
      state: "cancelled",
      stage: "terminal",
      status_version: 2,
      cancel_requested: true,
      message: "Evidence verification was cancelled before execution.",
      updated_at: "2026-08-10T12:00:01Z",
      completed_at: "2026-08-10T12:00:01Z",
    });
    window.history.replaceState({}, "", selectedPath(VERIFICATION_ID));
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({ verifications: [queued] }));
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockResolvedValue(queued);
    evidenceApiMocks.cancelWalletCaseEvidenceVerification.mockResolvedValue(cancelled);
    const user = userEvent.setup();
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Cancel verification" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Keep verifying" })));
    await user.click(screen.getByRole("button", { name: "Confirm cancel" }));

    const heading = await screen.findByRole("heading", { name: "Verification cancelled" });
    await waitFor(() => expect(document.activeElement).toBe(heading));
    expect(screen.queryByRole("button", { name: "Confirm cancel" })).toBeNull();
  });

  it("restores cancel-trigger focus when queued polling advances to running", async () => {
    const queued = queuedEvidenceVerificationFixture();
    const running = runningEvidenceVerificationFixture(0);
    window.history.replaceState({}, "", selectedPath(VERIFICATION_ID));
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({ verifications: [queued] }));
    evidenceApiMocks.getWalletCaseEvidenceVerification
      .mockResolvedValueOnce(queued)
      .mockResolvedValue(running);
    const user = userEvent.setup();
    render(<GramCaseEvidence walletCase={liveWalletCase()} onOpenActivity={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "Cancel verification" }));
    await waitFor(() => expect(document.activeElement).toBe(screen.getByRole("button", { name: "Keep verifying" })));

    await screen.findByRole("heading", { name: "Capturing transaction trace" }, { timeout: 2_500 });
    const cancel = await screen.findByRole("button", { name: "Cancel verification" });
    await waitFor(() => expect(document.activeElement).toBe(cancel));
    expect(screen.queryByRole("button", { name: "Confirm cancel" })).toBeNull();
  });

  it("restores canonical URL state and route heading focus on browser history", async () => {
    const succeeded = succeededEvidenceVerificationFixture();
    const second = succeededEvidenceVerificationFixture({ public_id: SECOND_VERIFICATION_ID, status_version: 9 });
    window.history.replaceState({}, "", selectedPath(VERIFICATION_ID));
    evidenceApiMocks.getWalletCaseEvidence.mockResolvedValue(evidenceCatalogFixture({ verifications: [succeeded, second] }));
    evidenceApiMocks.getWalletCaseEvidenceVerification.mockImplementation(
      (_caseId: string, verificationId: string) => Promise.resolve(verificationId === SECOND_VERIFICATION_ID ? second : succeeded),
    );
    const user = userEvent.setup();
    render(<GramCaseEvidence walletCase={walletCaseFixture()} onOpenActivity={vi.fn()} />);
    await screen.findByRole("heading", { name: "Stored verification attempts" });

    await user.click(screen.getAllByRole("button", { name: /Verification complete/ })[1]);
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("verification")).toBe(SECOND_VERIFICATION_ID));
    window.history.back();

    const heading = screen.getByRole("heading", { name: "Verify one transaction without inflating trust" });
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("verification")).toBe(VERIFICATION_ID));
    await waitFor(() => expect(document.activeElement).toBe(heading));
    window.history.forward();
    await waitFor(() => expect(new URLSearchParams(window.location.search).get("verification")).toBe(SECOND_VERIFICATION_ID));
    await waitFor(() => expect(document.activeElement).toBe(heading));
  });
});
