// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { WalletIngestionRunCatalogItem } from "../types";
import WalletRunCatalog from "./WalletRunCatalog";

function run(runId: string): WalletIngestionRunCatalogItem {
  return {
    run_id: runId,
    wallet_hint: "EQwall…llet",
    time_window: "24h",
    created_at: "2026-07-10T00:00:00Z",
    status: "success",
    data_mode: "real",
  };
}

function renderCatalog(
  overrides: Partial<Parameters<typeof WalletRunCatalog>[0]> = {},
) {
  const onOpen = vi.fn();
  const onRefresh = vi.fn();
  render(
    <WalletRunCatalog
      runs={[run("25"), run("24"), run("23"), run("22"), run("21")]}
      truncated
      loading={false}
      error={null}
      activeRunId={25}
      openingRunId={null}
      workspaceBusy={false}
      onRefresh={onRefresh}
      onOpen={onOpen}
      {...overrides}
    />,
  );
  return { onOpen, onRefresh };
}

describe("WalletRunCatalog", () => {
  afterEach(cleanup);

  it("starts compact, expands locally, and marks only the opened run current", async () => {
    const user = userEvent.setup();
    const { onOpen } = renderCatalog();

    expect(screen.getByText("RUN #25")).toBeTruthy();
    expect(screen.getByText("RUN #23")).toBeTruthy();
    expect(screen.queryByText("RUN #22")).toBeNull();
    expect(screen.getByText("CURRENT")).toBeTruthy();
    expect(
      screen.getByRole("button", {
        name: "Open stored run #25, wallet EQwall…llet",
      }).getAttribute("aria-current"),
    ).toBe("true");

    const disclosure = screen.getByRole("button", { name: "Show all 5" });
    expect(disclosure.getAttribute("aria-expanded")).toBe("false");
    expect(disclosure.getAttribute("aria-controls")).toBe(
      "wallet-run-catalog-list",
    );
    await user.click(disclosure);
    expect(screen.getByText("RUN #21")).toBeTruthy();
    expect(disclosure.getAttribute("aria-expanded")).toBe("true");

    await user.click(
      screen.getByRole("button", {
        name: "Open stored run #24, wallet EQwall…llet",
      }),
    );
    expect(onOpen).toHaveBeenCalledWith(24);
  });

  it("keeps an unsafe canonical ID exact and never opens it", async () => {
    const user = userEvent.setup();
    const { onOpen } = renderCatalog({
      runs: [run("9223372036854775807")],
      truncated: false,
      activeRunId: null,
    });

    expect(screen.getByText("RUN #9223372036854775807")).toBeTruthy();
    const button = screen.getByRole("button", {
      name: "Open stored run #9223372036854775807, wallet EQwall…llet",
    });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    await user.click(button);
    expect(onOpen).not.toHaveBeenCalled();
    expect(screen.getByText(/cannot safely open it/i)).toBeTruthy();
  });

  it("preserves stale rows and offers retry after a refresh error", async () => {
    const user = userEvent.setup();
    const { onRefresh } = renderCatalog({ error: "Catalog offline" });

    expect(screen.getByText("RUN #25")).toBeTruthy();
    expect(screen.getByText(/last successful list remains visible/i)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });
});
