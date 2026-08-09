// @vitest-environment jsdom

import { cleanup, render, screen, waitFor } from "@testing-library/react";
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

  it("keeps the unsupported case Activity URL fail-closed without legacy requests", async () => {
    window.history.replaceState({}, "", `/cases/${CASE_ID}/activity`);
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = requestUrl(input);
      if (url.pathname === "/api/providers/status") return jsonResponse(providersFixture());
      throw new Error(`Unexpected request: ${url.pathname}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<App />);

    expect(await screen.findByRole("heading", { name: "Page not found" })).toBeTruthy();
    expect(screen.queryByText("Compatibility view")).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
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
