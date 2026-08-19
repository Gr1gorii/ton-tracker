import { describe, expect, it } from "vitest";

import { parseWalletCaseFindingsResponse } from "./walletCaseFindings";
import {
  unsynchronizedWalletCaseFindingsFixture,
  walletCaseFindingsFixture,
} from "./test/walletCaseFindingsFixtures";

function payload(): any {
  return structuredClone(walletCaseFindingsFixture());
}

describe("Wallet Case Findings parser", () => {
  it("accepts the exact pinned Findings and Flows contract", () => {
    const parsed = parseWalletCaseFindingsResponse(payload());
    expect(parsed.findings?.flows.asset_flows[0].inflow_amount).toBe("12.5");
    expect(parsed.findings?.findings[0].evidence_level).toBe("normalized_provider_observation");
    expect(parsed.findings?.findings[0].supporting_activities[0].evidence_level).toBe("chain_inclusion_proven");
  });

  it("accepts the honest unsynchronized state", () => {
    expect(parseWalletCaseFindingsResponse(unsynchronizedWalletCaseFindingsFixture()).findings).toBeNull();
  });

  it("rejects raw or internal extras at every public boundary", () => {
    const top = payload();
    top.findings.run_id = 17;
    expect(() => parseWalletCaseFindingsResponse(top)).toThrow(/unexpected fields/);

    const nested = payload();
    nested.findings.findings[0].raw_json = { secret: true };
    expect(() => parseWalletCaseFindingsResponse(nested)).toThrow(/unexpected fields/);
  });

  it("rejects content-address, case and snapshot drift", () => {
    const hash = payload();
    hash.findings.content_hash_sha256 = "0".repeat(64);
    expect(() => parseWalletCaseFindingsResponse(hash)).toThrow(/content address/);

    const snapshot = payload();
    snapshot.findings.snapshot.public_id = "00000000-0000-4000-8000-000000000099";
    expect(() => parseWalletCaseFindingsResponse(snapshot)).toThrow(/snapshot/);
  });

  it("rejects flow identity, total and support contradictions", () => {
    const network = payload();
    network.findings.flows.asset_flows[0].network = "ton-testnet";
    expect(() => parseWalletCaseFindingsResponse(network)).toThrow(/changed network/);

    const total = payload();
    total.findings.flows.returned_asset_count = 0;
    expect(() => parseWalletCaseFindingsResponse(total)).toThrow(/totals/);

    const support = payload();
    support.findings.flows.protocol_flows[0].support_truncated = true;
    expect(() => parseWalletCaseFindingsResponse(support)).toThrow(/counts/);
  });

  it("rejects impossible Evidence promotion and demo/live mixing", () => {
    const derived = payload();
    derived.findings.findings[1].supporting_activities[0].evidence_level = "chain_inclusion_proven";
    derived.findings.findings[1].evidence_level = "chain_inclusion_proven";
    expect(() => parseWalletCaseFindingsResponse(derived)).toThrow(/overstates derived Activity evidence/);

    const demo = payload();
    demo.findings.subject.data_environment = "demo";
    demo.findings.snapshot.data_mode = "mock";
    expect(() => parseWalletCaseFindingsResponse(demo)).toThrow(/origin is inconsistent/);
  });

  it("rejects a finding whose published level exceeds its weakest support", () => {
    const mixed = payload();
    mixed.findings.findings[0].supporting_activities.push({
      activity_public_id: `act_${"9".repeat(64)}`,
      kind: "transfer",
      occurred_at: "2026-08-09T10:00:00Z",
      evidence_level: "normalized_provider_observation",
    });
    mixed.findings.findings[0].affected_count = 2;
    mixed.findings.findings[0].evidence_level = "chain_inclusion_proven";
    expect(() => parseWalletCaseFindingsResponse(mixed)).toThrow(/weakest support/);
  });

  it("rejects proof assurance on a provider-only failed outcome claim", () => {
    const overstated = payload();
    overstated.findings.findings[0].evidence_level = "chain_inclusion_proven";
    expect(() => parseWalletCaseFindingsResponse(overstated)).toThrow(/outcome assurance/);
  });

  it("accepts a live diagnostic finding whose support is a revision-level conflict", () => {
    const diagnostic = payload();
    diagnostic.findings.findings.push({
      public_id: `finding_${"3".repeat(64)}`,
      rule_id: "activity_identity_conflicts_v1",
      category: "data_quality",
      importance: "attention",
      title: "Conflicted Activity identities",
      explanation: "One identity group was omitted because its normalized observations disagreed.",
      affected_count: 1,
      support_basis: "identity_conflicts",
      supporting_activities: [],
      support_truncated: false,
      evidence_level: "normalized_provider_observation",
    });
    expect(parseWalletCaseFindingsResponse(diagnostic).findings?.findings).toHaveLength(3);
  });

  it("rejects truth claims and unsafe empty-response substitutions", () => {
    const truth = payload();
    truth.findings.truth_boundaries.absence_of_findings_means_safe = true;
    expect(() => parseWalletCaseFindingsResponse(truth)).toThrow(/absence boundary/);

    const empty: any = unsynchronizedWalletCaseFindingsFixture();
    empty.limitations = [];
    expect(() => parseWalletCaseFindingsResponse(empty)).toThrow(/not_synchronized/);
  });
});
