import { describe, expect, it } from "vitest";

import { manifestResponseFixture } from "./test/walletCaseSyncManifestFixtures";
import {
  parseWalletCaseSyncManifestDescriptor,
  parseWalletCaseSyncManifestResponse,
} from "./walletCaseSyncManifest";

describe("Wallet Case acquisition manifest contracts", () => {
  it("accepts a content-addressed, scope-bound manifest", () => {
    const fixture = manifestResponseFixture();

    expect(parseWalletCaseSyncManifestResponse(fixture)).toEqual(fixture);
    expect(parseWalletCaseSyncManifestDescriptor(fixture.manifest).public_id).toBe(
      fixture.manifest.public_id,
    );
  });

  it("rejects identity, count, lineage, and shape contradictions", () => {
    const fixture = manifestResponseFixture();
    expect(() => parseWalletCaseSyncManifestResponse({
      ...fixture,
      manifest: { ...fixture.manifest, public_id: `smf_${"0".repeat(64)}` },
    })).toThrow(/identity/);
    expect(() => parseWalletCaseSyncManifestResponse({
      ...fixture,
      manifest: { ...fixture.manifest, page_count: 1 },
    })).toThrow(/does not match/);
    expect(() => parseWalletCaseSyncManifestResponse({
      ...fixture,
      document: { ...fixture.document, overlap_seconds: 900 },
    })).toThrow(/lineage/);
    expect(() => parseWalletCaseSyncManifestResponse({
      ...fixture,
      document: { ...fixture.document, raw_provider_payload: {} },
    })).toThrow(/shape/);
  });

  it("requires canonical surface order and matching requested bounds", () => {
    const fixture = manifestResponseFixture();
    expect(() => parseWalletCaseSyncManifestResponse({
      ...fixture,
      document: {
        ...fixture.document,
        requested_surfaces: [...fixture.document.requested_surfaces].reverse(),
      },
    })).toThrow(/surfaces/);
    expect(() => parseWalletCaseSyncManifestResponse({
      ...fixture,
      document: {
        ...fixture.document,
        acquisition_period: {
          start_at: "2026-08-08T12:00:01Z",
          end_at: "2026-08-09T12:00:00Z",
        },
      },
    })).toThrow(/lineage/);
  });
});
