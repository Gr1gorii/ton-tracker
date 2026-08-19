// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CASE_ID, walletCaseFixture } from "../test/walletCaseFixtures";

const apiMocks = vi.hoisted(() => ({ getWalletCase: vi.fn() }));
vi.mock("../walletCaseApi", () => apiMocks);
vi.mock("./GramCaseSummary", () => ({ default: () => <div>Summary surface</div> }));
vi.mock("./GramCaseActivity", () => ({ default: () => <div>Activity surface</div> }));
vi.mock("./GramCaseFindings", () => ({ default: () => <div>Findings surface</div> }));
vi.mock("./GramCaseEvidence", () => ({ default: () => <div>Evidence surface</div> }));
vi.mock("./GramCaseReports", () => ({ default: () => <div>Reports surface</div> }));

import GramCaseWorkspace from "./GramCaseWorkspace";

beforeEach(() => {
  vi.clearAllMocks();
  apiMocks.getWalletCase.mockResolvedValue(walletCaseFixture());
});
afterEach(() => cleanup());

describe("GramCaseWorkspace", () => {
  it("offers real Summary, Activity, Findings, Evidence and Reports links with one current view and SPA plain-click navigation", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const { rerender } = render(<GramCaseWorkspace caseId={CASE_ID} view="summary" onNavigate={onNavigate} />);
    await screen.findByText("Summary surface");

    const summary = screen.getByRole("link", { name: /SummarySnapshot and coverage/ });
    const activity = screen.getByRole("link", { name: /ActivityFiltered snapshot rows/ });
    const findings = screen.getByRole("link", { name: /FindingsExplainable flows/ });
    const evidence = screen.getByRole("link", { name: /EvidenceTransaction verification/ });
    const reports = screen.getByRole("link", { name: /ReportsSaved revisions/ });
    expect(summary.getAttribute("href")).toBe(`/cases/${CASE_ID}/summary`);
    expect(activity.getAttribute("href")).toBe(`/cases/${CASE_ID}/activity`);
    expect(findings.getAttribute("href")).toBe(`/cases/${CASE_ID}/findings`);
    expect(evidence.getAttribute("href")).toBe(`/cases/${CASE_ID}/evidence`);
    expect(reports.getAttribute("href")).toBe(`/cases/${CASE_ID}/reports`);
    expect(summary.getAttribute("aria-current")).toBe("page");
    expect(activity.getAttribute("aria-current")).toBeNull();
    expect(findings.getAttribute("aria-current")).toBeNull();
    expect(evidence.getAttribute("aria-current")).toBeNull();
    expect(reports.getAttribute("aria-current")).toBeNull();
    await user.click(activity);
    expect(onNavigate).toHaveBeenCalledWith("activity");

    rerender(<GramCaseWorkspace caseId={CASE_ID} view="activity" onNavigate={onNavigate} />);
    await waitFor(() => expect(screen.getByText("Activity surface")).toBeTruthy());
    expect(activity.getAttribute("aria-current")).toBe("page");
    expect(apiMocks.getWalletCase).toHaveBeenCalledTimes(1);

    await user.click(findings);
    expect(onNavigate).toHaveBeenCalledWith("findings");

    rerender(<GramCaseWorkspace caseId={CASE_ID} view="findings" onNavigate={onNavigate} />);
    await waitFor(() => expect(screen.getByText("Findings surface")).toBeTruthy());
    expect(findings.getAttribute("aria-current")).toBe("page");

    await user.click(evidence);
    expect(onNavigate).toHaveBeenCalledWith("evidence");

    await user.click(reports);
    expect(onNavigate).toHaveBeenCalledWith("reports");

    rerender(<GramCaseWorkspace caseId={CASE_ID} view="reports" onNavigate={onNavigate} />);
    await waitFor(() => expect(screen.getByText("Reports surface")).toBeTruthy());
    expect(reports.getAttribute("aria-current")).toBe("page");
  });

  it("shows a retryable shell error and never mounts a case surface without a bound case", async () => {
    apiMocks.getWalletCase.mockRejectedValueOnce(new Error("Case scope rejected"));
    render(<GramCaseWorkspace caseId={CASE_ID} view="activity" onNavigate={vi.fn()} />);
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Case scope rejected");
    expect(screen.queryByText("Activity surface")).toBeNull();
  });
});
