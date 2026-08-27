// @vitest-environment jsdom

import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  useTonConnectUI: () => [{ setConnectRequestParameters: vi.fn() }],
  useTonWallet: () => null,
}));

import App from "./App";
import { API_BASE } from "./api";
import type { ProvidersStatus } from "./types";
import {
  activeSyncFixture,
  ALL_SURFACES,
  CASE_ID,
  emptyWalletCaseFixture,
  succeededSyncFixture,
  SYNC_ID,
  walletCaseFixture,
} from "./test/walletCaseFixtures";
import {
  ACTIVITY_ID,
  activityDetailFixture,
  activityResponseFixture,
} from "./test/walletCaseActivityFixtures";
import {
  evidenceCatalogFixture,
  liveEvidenceActivityDetailFixture,
  partialEvidenceVerificationFixture,
  VERIFICATION_ID,
} from "./test/walletCaseEvidenceFixtures";
import { walletCaseReportFixture } from "./test/walletCaseReportFixtures";
import {
  walletCaseReportRevisionCatalogFixture,
  walletCaseReportRevisionDetailFixture,
} from "./test/walletCaseReportRevisionFixtures";
import { walletCaseFindingsFixture } from "./test/walletCaseFindingsFixtures";

const WALLET = "EQC-demo-wallet";

function providersFixture(): ProvidersStatus {
  const configured = {
    configured: true,
    available: true,
    message: "Configured deterministic demo source; no live health claim.",
  };
  return {
    data_mode: "mock",
    data_environment: "demo",
    ton_network: "ton-mainnet",
    wallet_cases_available: true,
    geckoterminal: configured,
    ton_provider: configured,
    bitquery: configured,
    stonfi: configured,
    tonapi: configured,
    wallet_activity: configured,
  };
}

function jsonResponse(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function requestUrl(input: RequestInfo | URL): URL {
  if (input instanceof URL) return input;
  if (typeof input === "string") return new URL(input);
  return new URL(input.url);
}

function memoryStorage(): Storage {
  const values = new Map<string, string>();
  return {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, String(value)),
  };
}

beforeEach(() => {
  const storage = memoryStorage();
  Object.defineProperty(window, "localStorage", {
    configurable: true,
    value: storage,
  });
  vi.stubGlobal("localStorage", storage);
  window.history.replaceState({}, "", "/");
  vi.stubGlobal("scrollTo", vi.fn());
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: false,
      media: "",
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    }),
  );
});

afterEach(() => {
  cleanup();
  window.history.replaceState({}, "", "/");
  vi.unstubAllGlobals();
});

describe("Wallet Case application flow", () => {
  it("restores the Case library route and opens a selected Case", async () => {
    window.history.replaceState({}, "", "/cases");
    const walletCase = walletCaseFixture({ overrides: { label: "Treasury" } });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === "/api/v1/cases" && method === "GET") {
        expect(url.searchParams.getAll("limit")).toEqual(["12"]);
        return jsonResponse({
          cases: [walletCase], limit: 12, state: "active", query: null,
          network: null, data_environment: null, truncated: false, next_cursor: null,
        });
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}` && method === "GET") {
        return jsonResponse(walletCase);
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    const libraryMain = await screen.findByRole("main", { name: "Wallet Case library" });
    await waitFor(() => expect(document.title).toBe("Wallet Case Library · GRAM Scope"));
    await waitFor(() => expect(document.activeElement).toBe(libraryMain));
    await user.click(await screen.findByRole("button", { name: "Open Case Treasury" }));
    expect(await screen.findByRole("heading", { name: "Treasury" })).toBeTruthy();
    expect(window.location.pathname).toBe(`/cases/${CASE_ID}/summary`);
    expect(screen.getByRole("button", { name: "Open Case library" })).toBeTruthy();
  });

  it("navigates from the landing page to the local Case library", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === "/api/v1/cases" && method === "GET") {
        return jsonResponse({
          cases: [], limit: 12, state: "active", query: null,
          network: null, data_environment: null, truncated: false, next_cursor: null,
        });
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    await screen.findByText(/Demo runtime — cases use deterministic preview evidence/);
    await user.click(screen.getByRole("button", { name: "Open Case library" }));

    expect(await screen.findByRole("heading", { name: "No Wallet Cases yet" })).toBeTruthy();
    expect(window.location.pathname).toBe("/cases");
  });

  it("opens a deep-linked Case Reports catalog and restores an exact saved revision", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/reports?snapshot=${SYNC_ID}`);
    const reportCase = walletCaseFixture({
      latestAttempt: null,
      currentSnapshot: null,
      overrides: {
        data_environment: "live",
        canonical_wallet_key: `0:${"1".repeat(64)}`,
      },
    });
    const catalog = walletCaseReportRevisionCatalogFixture();
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}`) return jsonResponse(reportCase);
      if (url.pathname === `/api/v1/cases/${CASE_ID}/report`) return jsonResponse(walletCaseReportFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}/reports` && method === "GET") return jsonResponse(catalog);
      if (url.pathname === `/api/v1/cases/${CASE_ID}/reports/${catalog.items[0].public_id}`) return jsonResponse(walletCaseReportRevisionDetailFixture());
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);
    expect(await screen.findByRole("heading", { name: "Saved report revisions" })).toBeTruthy();
    expect(document.title).toBe("Wallet Case Reports · GRAM Scope");
    const saved = await screen.findByRole("link", { name: /Activity rows/ });
    await user.click(saved);
    expect(await screen.findByRole("heading", { name: "Exact stored public report" })).toBeTruthy();
    expect(window.location.search).toContain(`revision=${catalog.items[0].public_id}`);
    expect(fetchMock).toHaveBeenCalledWith(
      `${API_BASE}/api/v1/cases/${CASE_ID}/reports/${catalog.items[0].public_id}`,
      expect.objectContaining({ cache: "no-store" }),
    );
  });

  it("gives an initially deep-linked saved report revision focus precedence", async () => {
    const catalog = walletCaseReportRevisionCatalogFixture();
    window.history.replaceState(
      {},
      "",
      `/cases/${CASE_ID}/reports?snapshot=${SYNC_ID}&revision=${catalog.items[0].public_id}`,
    );
    const reportCase = walletCaseFixture({
      latestAttempt: null,
      currentSnapshot: null,
      overrides: {
        data_environment: "live",
        canonical_wallet_key: `0:${"1".repeat(64)}`,
      },
    });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}`) return jsonResponse(reportCase);
      if (url.pathname === `/api/v1/cases/${CASE_ID}/report`) return jsonResponse(walletCaseReportFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}/reports` && method === "GET") return jsonResponse(catalog);
      if (url.pathname === `/api/v1/cases/${CASE_ID}/reports/${catalog.items[0].public_id}`) {
        return jsonResponse(walletCaseReportRevisionDetailFixture());
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);
    const detailHeading = await screen.findByRole("heading", { name: "Exact stored public report" });
    await waitFor(() => expect(document.activeElement).toBe(detailHeading));
    expect(document.querySelector("[data-route-focus]")).not.toBe(document.activeElement);
  });

  it("creates or opens a canonical case URL, syncs a bounded interval, and restores it after remount", async () => {
    const emptyCase = emptyWalletCaseFixture();
    const syncedCase = walletCaseFixture();
    const queuedSync = activeSyncFixture("queued", { poll_after_ms: 500 });
    let caseReadCount = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status" && method === "GET") {
        return jsonResponse(providersFixture());
      }
      if (url.pathname === "/api/v1/cases" && method === "POST") {
        return jsonResponse({ created: true, case: emptyCase }, 201);
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}` && method === "GET") {
        caseReadCount += 1;
        return jsonResponse(caseReadCount === 1 ? emptyCase : syncedCase);
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/syncs` && method === "POST") {
        return jsonResponse(queuedSync, 202);
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/syncs/${SYNC_ID}` && method === "GET") {
        return jsonResponse(succeededSyncFixture());
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    const firstRender = render(<App />);
    expect(await screen.findByText(/Demo runtime — cases use deterministic preview evidence/)).toBeTruthy();
    await user.type(screen.getByLabelText("TON wallet address"), `  ${WALLET}  `);
    await user.click(screen.getByRole("button", { name: "Explore wallet" }));

    await waitFor(() => expect(window.location.pathname).toBe(
      `/cases/${CASE_ID}/summary`,
    ));
    const createCall = fetchMock.mock.calls.find(([input, init]) => {
      const url = requestUrl(input);
      return url.pathname === "/api/v1/cases" && (init?.method ?? "GET") === "POST";
    });
    expect(createCall).toBeTruthy();
    expect(JSON.parse(String(createCall?.[1]?.body))).toEqual({
      wallet_address: WALLET,
      network: "ton-mainnet",
      data_environment: "demo",
    });

    expect(await screen.findByRole("heading", { name: "Build the first usable snapshot" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Sync last 24 hours" }));

    await waitFor(() => {
      const syncCall = fetchMock.mock.calls.find(([input, init]) => {
        const url = requestUrl(input);
        return url.pathname === `/api/v1/cases/${CASE_ID}/syncs` && init?.method === "POST";
      });
      expect(syncCall).toBeTruthy();
      expect(JSON.parse(String(syncCall?.[1]?.body))).toEqual({
        mode: "bounded",
        time_window: "24h",
        surfaces: [...ALL_SURFACES],
      });
      expect(syncCall?.[1]?.headers).toMatchObject({
        "Idempotency-Key": expect.stringMatching(
          /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
        ),
      });
    });
    expect(await screen.findByRole("heading", { name: "Snapshot ready" })).toBeTruthy();
    expect(screen.getAllByText("Coverage not established").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Run #/)).toBeNull();

    firstRender.unmount();
    render(<App />);

    expect(await screen.findByRole("heading", { name: WALLET })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Snapshot ready" })).toBeTruthy();
    expect(window.location.pathname).toBe(`/cases/${CASE_ID}/summary`);
    expect(screen.queryByLabelText("TON wallet address")).toBeNull();
    expect(caseReadCount).toBe(3);
  });

  it("fails closed when a deep-linked live case contains demo sync evidence", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/summary`);
    const unsafeCase = walletCaseFixture({ overrides: { data_environment: "live" } });
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") {
        return jsonResponse(providersFixture());
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}` && method === "GET") {
        return jsonResponse(unsafeCase);
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain(
      "wallet case environment or identity does not match its sync evidence",
    );
    expect(screen.queryByText("Returned activity rows")).toBeNull();
    expect(screen.queryByRole("button", { name: "Sync last 24 hours" })).toBeNull();
    expect(window.location.pathname).toBe(`/cases/${CASE_ID}/summary`);
  });

  it("resumes a persisted active sync after refresh without creating another job", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/summary`);
    const queued = activeSyncFixture("queued", { poll_after_ms: 500 });
    const activeCase = walletCaseFixture({ latestAttempt: queued, currentSnapshot: null });
    const completedCase = walletCaseFixture();
    let caseReads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}` && method === "GET") {
        caseReads += 1;
        return jsonResponse(caseReads === 1 ? activeCase : completedCase);
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/syncs/${SYNC_ID}` && method === "GET") {
        return jsonResponse(succeededSyncFixture());
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Queued safely" })).toBeTruthy();
    expect(await screen.findByRole("heading", { name: "Snapshot ready" }, { timeout: 2_000 })).toBeTruthy();
    expect(caseReads).toBe(2);
    expect(fetchMock.mock.calls.some(([input, init]) =>
      requestUrl(input).pathname.endsWith("/syncs") && init?.method === "POST"
    )).toBe(false);
  });

  it("deep-links the modern case Activity route and never requests the legacy Activity facade", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/activity`);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}`) return jsonResponse(walletCaseFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}/activity` && (init?.method ?? "GET") === "GET") {
        return jsonResponse(activityResponseFixture());
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/activity/${ACTIVITY_ID}` && (init?.method ?? "GET") === "GET") {
        return jsonResponse(activityDetailFixture());
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "1 Activity rows" })).toBeTruthy();
    const activityMain = screen.getByRole("main", { name: "Wallet Case activity" });
    await waitFor(() => expect(document.activeElement).toBe(activityMain));
    expect(screen.getByRole("link", { name: /ActivityFiltered snapshot rows/ }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("link", { name: /SummarySnapshot and coverage/ }).getAttribute("href")).toBe(`/cases/${CASE_ID}/summary`);
    await waitFor(() => expect(document.title).toBe("Wallet Case Activity · GRAM Scope"));
    expect(screen.queryByText("Compatibility view")).toBeNull();
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input).pathname === "/api/wallets/ingest")).toBe(false);

    const activityRow = screen.getByRole("link", { name: "Open Transaction Activity detail" });
    await user.click(activityRow);
    expect(await screen.findByRole("dialog", { name: "Activity detail" })).toBeTruthy();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await waitFor(() => expect(document.activeElement).toBe(activityRow));

    await user.click(screen.getByRole("link", { name: /SummarySnapshot and coverage/ }));
    expect(await screen.findByRole("heading", { name: "Snapshot ready" })).toBeTruthy();
    expect(window.location.pathname).toBe(`/cases/${CASE_ID}/summary`);
  });

  it("deep-links pinned Findings and follows a supporting row back to Activity", async () => {
    const liveSync = succeededSyncFixture({ data_mode: "real", provider: "tonapi_wallet_activity_live" });
    const liveCase = walletCaseFixture({
      latestAttempt: liveSync,
      currentSnapshot: liveSync,
      overrides: { data_environment: "live" },
    });
    window.history.replaceState({}, "", `/cases/${CASE_ID}/findings?snapshot=${SYNC_ID}`);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}` && method === "GET") return jsonResponse(liveCase);
      if (url.pathname === `/api/v1/cases/${CASE_ID}/findings` && method === "GET") {
        expect(url.searchParams.getAll("snapshot")).toEqual([SYNC_ID]);
        return jsonResponse(walletCaseFindingsFixture());
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/activity` && method === "GET") {
        return jsonResponse(activityResponseFixture());
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/activity/${ACTIVITY_ID}` && method === "GET") {
        return jsonResponse(activityDetailFixture());
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Explainable findings with supporting rows" })).toBeTruthy();
    const findingsMain = screen.getByRole("main", { name: "Wallet Case findings" });
    await waitFor(() => expect(document.activeElement).toBe(findingsMain));
    expect(screen.getByRole("link", { name: /FindingsExplainable flows/ }).getAttribute("aria-current")).toBe("page");
    await waitFor(() => expect(document.title).toBe("Wallet Case Findings · GRAM Scope"));

    const support = screen.getAllByRole("link").find((link) => link.getAttribute("href")?.includes(ACTIVITY_ID));
    expect(support).toBeTruthy();
    await user.click(support!);
    await waitFor(() => expect(window.location.pathname).toBe(`/cases/${CASE_ID}/activity`));
    expect(new URLSearchParams(window.location.search).get("activity")).toBe(ACTIVITY_ID);
    expect(await screen.findByRole("dialog", { name: "Activity detail" })).toBeTruthy();
  });

  it("keeps initial deep-linked Activity detail focus inside the modal after route focus runs", async () => {
    window.history.replaceState(
      {},
      "",
      `/cases/${CASE_ID}/activity?snapshot=${SYNC_ID}&sort=newest&activity=${ACTIVITY_ID}`,
    );
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}`) return jsonResponse(walletCaseFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}/activity` && (init?.method ?? "GET") === "GET") {
        return jsonResponse(activityResponseFixture());
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/activity/${ACTIVITY_ID}` && (init?.method ?? "GET") === "GET") {
        return jsonResponse(activityDetailFixture());
      }
      throw new Error(`Unexpected request: ${init?.method ?? "GET"} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    let routeFocusCallback: (() => void) | null = null;
    const nativeSetTimeout = window.setTimeout.bind(window);
    const timerSpy = vi.spyOn(window, "setTimeout").mockImplementation((handler, timeout, ...args) => {
      if (timeout === 0 && routeFocusCallback === null && typeof handler === "function") {
        routeFocusCallback = () => handler(...args);
        return 987_654_321;
      }
      return nativeSetTimeout(handler, timeout, ...args);
    });

    try {
      render(<App />);

      const dialog = await screen.findByRole("dialog", { name: "Activity detail" });
      const close = screen.getByRole("button", { name: "Close Activity detail" });
      await waitFor(() => expect(document.activeElement).toBe(close));
      const callback = routeFocusCallback;
      expect(callback).not.toBeNull();
      act(() => (callback as unknown as () => void)());
      expect(dialog.contains(document.activeElement)).toBe(true);
      expect(document.activeElement).toBe(close);
    } finally {
      timerSpy.mockRestore();
    }
  });

  it("deep-links strict Evidence state, resumes its durable partial result, and keeps route focus", async () => {
    const liveSync = succeededSyncFixture({
      data_mode: "real",
      provider: "tonapi_wallet_activity_live",
    });
    const liveCase = walletCaseFixture({
      latestAttempt: liveSync,
      currentSnapshot: liveSync,
      overrides: { data_environment: "live" },
    });
    const partial = partialEvidenceVerificationFixture();
    const search = new URLSearchParams({
      snapshot: SYNC_ID,
      activity: ACTIVITY_ID,
      verification: VERIFICATION_ID,
    });
    window.history.replaceState({}, "", `/cases/${CASE_ID}/evidence?${search}`);
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = requestUrl(input);
      const method = init?.method ?? "GET";
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      if (url.pathname === `/api/v1/cases/${CASE_ID}` && method === "GET") return jsonResponse(liveCase);
      if (url.pathname === `/api/v1/cases/${CASE_ID}/evidence` && method === "GET") {
        expect(url.searchParams.getAll("snapshot")).toEqual([SYNC_ID]);
        return jsonResponse(evidenceCatalogFixture({ verifications: [partial] }));
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/activity/${ACTIVITY_ID}` && method === "GET") {
        return jsonResponse(liveEvidenceActivityDetailFixture());
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/evidence/verifications/${VERIFICATION_ID}` && method === "GET") {
        return jsonResponse(partial);
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}/report` && method === "GET") {
        expect(url.searchParams.getAll("snapshot")).toEqual([SYNC_ID]);
        return jsonResponse(walletCaseReportFixture());
      }
      throw new Error(`Unexpected request: ${method} ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Partial evidence preserved", level: 2 })).toBeTruthy();
    const evidenceMain = screen.getByRole("main", { name: "Wallet Case evidence" });
    await waitFor(() => expect(document.activeElement).toBe(evidenceMain));
    expect(screen.getByRole("link", { name: /EvidenceTransaction verification/ }).getAttribute("aria-current")).toBe("page");
    expect(screen.getByRole("heading", { name: "Normalized report" })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Export JSON" })).toBeTruthy();
    expect(screen.queryByText(/canonical case ledger/i)).toBeNull();
    await waitFor(() => expect(document.title).toBe("Wallet Case Evidence · GRAM Scope"));
    expect(fetchMock.mock.calls.some(([input]) => requestUrl(input).pathname.includes("/runs/"))).toBe(false);
  });

  it("keeps the pre-authentication case facade disabled on hosted access", async () => {
    const hostedStatus = {
      ...providersFixture(),
      wallet_cases_available: false,
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") {
        return jsonResponse(hostedStatus);
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByText(/Wallet Cases are disabled on hosted access/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Explore wallet" }) as HTMLButtonElement).disabled).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("retries a transient runtime-status failure without requiring a page reload", async () => {
    let statusReads = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, _init?: RequestInit) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") {
        statusReads += 1;
        return statusReads === 1
          ? jsonResponse({ detail: "Backend is still starting." }, 503)
          : jsonResponse(providersFixture());
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    expect(await screen.findByText(/Runtime configuration unavailable/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Explore wallet" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("button", { name: "Retry runtime check" }));

    expect(await screen.findByText(/Demo runtime — cases use deterministic preview evidence/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Explore wallet" }) as HTMLButtonElement).disabled).toBe(false);
    expect(statusReads).toBe(2);
    expect(fetchMock.mock.calls.every(([, init]) => init?.cache === "no-store")).toBe(true);
  });

  it("announces landing validation errors and marks the wallet input invalid", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") {
        return jsonResponse(providersFixture());
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    await screen.findByText(/Demo runtime — cases use deterministic preview evidence/);
    const input = screen.getByLabelText("TON wallet address");
    expect(input.getAttribute("aria-invalid")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Explore wallet" }));

    expect((await screen.findByRole("alert")).textContent).toContain(
      "Enter a TON wallet address to start.",
    );
    expect(input.getAttribute("aria-invalid")).toBe("true");

    await user.type(input, WALLET);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(input.getAttribute("aria-invalid")).toBeNull();
  });

  it("labels unfinished reports and exports as legacy run-scoped diagnostics", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    await screen.findByText(/Demo runtime — cases use deterministic preview evidence/);
    expect(screen.getByText("Explicit trust levels")).toBeTruthy();
    expect(document.body.textContent).not.toContain("One canonical ledger");
    expect(document.body.textContent).not.toContain("Reports, clustering and exports share");

    await user.click(screen.getByRole("button", { name: "Open advanced diagnostics without an address" }));
    const reports = screen.getAllByRole("button", { name: /ReportsLegacy run exports/ });
    await user.click(reports[0]);

    expect(await screen.findByRole("heading", { name: "Legacy run-scoped exports" })).toBeTruthy();
    expect(screen.getByText(/not the Wallet Case report/)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Run-scoped ledger export" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Legacy report export" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("One ledger, every downstream answer");
    expect(document.body.textContent).not.toContain("Reports and exports use the canonical ledger");
  });

  it("announces SPA route changes with a title, focus target, and named mobile Home control", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/summary`);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") {
        return jsonResponse(providersFixture());
      }
      if (url.pathname === `/api/v1/cases/${CASE_ID}`) {
        return jsonResponse(walletCaseFixture());
      }
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(<App />);

    const caseMain = await screen.findByRole("main", { name: "Wallet Case summary" });
    await waitFor(() => expect(document.title).toBe("Wallet Case Summary · GRAM Scope"));
    await waitFor(() => expect(document.activeElement).toBe(caseMain));
    const home = screen.getByRole("button", { name: "Return to home" });
    await user.click(home);

    const landingMain = await screen.findByRole("main", {
      name: /clearer evidence trail/i,
    });
    await waitFor(() => expect(window.location.pathname).toBe("/"));
    await waitFor(() => expect(document.title).toBe("GRAM Scope · TON Wallet Evidence"));
    await waitFor(() => expect(document.activeElement).toBe(landingMain));
  });
});
