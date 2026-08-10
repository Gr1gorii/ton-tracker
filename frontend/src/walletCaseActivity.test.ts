import { describe, expect, it } from "vitest";

import {
  parseWalletCaseActivityDetailResponse,
  parseWalletCaseActivityResponse,
} from "./walletCaseActivity";
import {
  activityDetailFixture,
  activityResponseFixture,
  unsynchronizedActivityResponseFixture,
} from "./test/walletCaseActivityFixtures";

describe("Wallet Case Activity parser", () => {
  it("accepts a snapshot-bound page and honest unsynchronized empty state", () => {
    const parsed = parseWalletCaseActivityResponse(activityResponseFixture());
    expect(parsed.snapshot?.data_mode).toBe("mock");
    expect(Date.parse(parsed.observed_period!.start_at)).toBeLessThanOrEqual(Date.parse(parsed.observed_period!.end_at));
    expect(parseWalletCaseActivityResponse(unsynchronizedActivityResponseFixture()).snapshot).toBeNull();
  });

  it("requires a strict half-open observed period, including for one row", () => {
    const value = activityResponseFixture();
    value.observed_period = { start_at: value.items[0].occurred_at!, end_at: value.items[0].occurred_at! };
    expect(() => parseWalletCaseActivityResponse(value)).toThrow(/observed period/);
  });

  it("accepts the uint64 logical-time ceiling and rejects overflow", () => {
    const maximum = activityResponseFixture();
    maximum.items[0].logical_time = "18446744073709551615";
    expect(parseWalletCaseActivityResponse(maximum).items[0].logical_time).toBe("18446744073709551615");

    const overflow = activityResponseFixture();
    overflow.items[0].logical_time = "18446744073709551616";
    expect(() => parseWalletCaseActivityResponse(overflow)).toThrow(/logical time/);
  });

  it.each([
    `-0:${"a".repeat(64)}`,
    `2147483648:${"a".repeat(64)}`,
    `-2147483649:${"a".repeat(64)}`,
  ])("rejects noncanonical or out-of-int32 response workchain %s", (counterparty) => {
    const value = activityResponseFixture();
    value.filters.counterparty = counterparty;
    expect(() => parseWalletCaseActivityResponse(value)).toThrow(/counterparty filter/);
  });

  it.each([
    "2026-02-30T00:00:00Z",
    "2026-08-01T24:00:00Z",
    "0000-01-01T00:00:00Z",
    "2026-08-01T00:00:00.0000001Z",
  ])("rejects impossible response timestamp %s", (occurredAt) => {
    const value = activityResponseFixture();
    value.items[0].occurred_at = occurredAt;
    expect(() => parseWalletCaseActivityResponse(value)).toThrow(/occurrence time/);
  });

  it.each([
    ["aggregate totals", (value: any) => { value.aggregate.swaps = 1; }],
    ["page cursor", (value: any) => { value.page.has_more = true; }],
    ["snapshot coverage", (value: any) => { value.snapshot.requested_period.end_at = "2026-08-09T11:00:00Z"; }],
    ["demo origin", (value: any) => { value.items[0].provenance.data_origin = "provider_observed"; value.items[0].provenance.evidence_level = "normalized_provider_observation"; }],
    ["details kind", (value: any) => { value.items[0].details = { kind: "transfer", amount: "1" }; }],
    ["dedup counts", (value: any) => { value.items[0].provenance.observation_count = 2; }],
    ["unavailable identity dedup", (value: any) => { value.items[0].provenance.observation_count = 2; value.items[0].provenance.suppressed_count = 1; }],
    ["transaction reference", (value: any) => { value.items[0].transaction = { linkage: "self", hash: null, event_id: null }; }],
    ["duplicate item", (value: any) => { value.items.push(value.items[0]); value.aggregate.total_items = 2; value.aggregate.transactions = 2; }],
  ])("fails closed for inconsistent %s", (_label, mutate) => {
    const value = structuredClone(activityResponseFixture());
    mutate(value);
    expect(() => parseWalletCaseActivityResponse(value)).toThrow();
  });

  it("does not accept evidence in an unsynchronized response", () => {
    const value = unsynchronizedActivityResponseFixture();
    value.aggregate.source_sync_count = 1;
    expect(() => parseWalletCaseActivityResponse(value)).toThrow(/published evidence/);
  });

  it.each([
    ["kind", (value: any) => { value.filters.kinds = ["swap"]; }],
    ["direction", (value: any) => { value.filters.directions = ["in"]; }],
    ["outcome", (value: any) => { value.filters.outcomes = ["failed"]; }],
    ["period", (value: any) => { value.filters.from_at = "2026-08-09T11:00:01Z"; value.filters.to_at = "2026-08-09T11:01:00Z"; }],
    ["asset", (value: any) => { value.filters.asset_id = `asset_${"f".repeat(64)}`; }],
    ["protocol", (value: any) => { value.filters.protocol_id = "stonfi_v2"; }],
    ["counterparty", (value: any) => { value.filters.counterparty = `0:${"f".repeat(64)}`; }],
    ["origin", (value: any) => { value.filters.data_origins = ["provider_observed"]; }],
  ])("rejects a page item outside its echoed %s filter", (_label, mutate) => {
    const value = structuredClone(activityResponseFixture());
    mutate(value);
    expect(() => parseWalletCaseActivityResponse(value)).toThrow(/does not match echoed filters/);
  });

  it("parses sanitized detail with nullable observation times", () => {
    const value = activityDetailFixture();
    value.source_observations[0].observed_at = null;
    expect(parseWalletCaseActivityDetailResponse(value).source_observations[0].observed_at).toBeNull();
  });

  it.each([
    ["origin", (value: any) => { value.source_observations[0].data_origin = "provider_observed"; }],
    ["provider", (value: any) => { value.source_observations[0].provider = "different-provider"; }],
    ["status", (value: any) => { value.source_observations[0].source_status = "different"; }],
    ["first sync", (value: any) => { value.source_observations[0].sync_public_id = "550e8400-e29b-41d4-a716-446655440099"; }],
  ])("rejects detail with incoherent source %s", (_label, mutate) => {
    const value = structuredClone(activityDetailFixture());
    mutate(value);
    expect(() => parseWalletCaseActivityDetailResponse(value)).toThrow(/detail provenance/);
  });

  it("rejects an internal-looking or malformed Activity id", () => {
    const value = activityDetailFixture() as any;
    value.item.public_id = "1";
    expect(() => parseWalletCaseActivityDetailResponse(value)).toThrow(/item id/);
  });
});
