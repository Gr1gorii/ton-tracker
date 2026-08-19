import { parseRfc3339Instant } from "./rfc3339";
import { isCanonicalRawTonAddress } from "./tonAddress";
import {
  parseWalletCaseCoverage,
  type WalletCaseCoverage,
  type WalletCaseLimitation,
} from "./walletCase";
import {
  isWalletCaseActivityPublicId,
  isWalletCaseAssetPublicId,
  isWalletCaseSnapshotPublicId,
  type WalletCaseActivityKind,
  type WalletCaseActivitySnapshot,
} from "./walletCaseActivity";

export type WalletCaseFindingEvidenceLevel =
  | "fixture"
  | "normalized_provider_observation"
  | "locally_verified"
  | "chain_inclusion_proven";

export type WalletCaseFindingRule =
  | "activity_coverage_gaps_v1"
  | "activity_identity_conflicts_v1"
  | "failed_transaction_observations_v1"
  | "unavailable_asset_identity_v1"
  | "unavailable_counterparty_identity_v1"
  | "repeated_counterparty_observations_v1"
  | "recognized_protocol_observations_v1";

export interface WalletCaseFindingSupport {
  activity_public_id: string;
  kind: WalletCaseActivityKind;
  occurred_at: string | null;
  evidence_level: WalletCaseFindingEvidenceLevel;
}

export interface WalletCaseAssetFlow {
  asset_id: string;
  network: "ton-mainnet" | "ton-testnet";
  standard: "native" | "jetton";
  contract_address: string | null;
  symbol: string | null;
  inflow_amount: string | null;
  outflow_amount: string | null;
  inflow_observations: number;
  outflow_observations: number;
  unknown_direction_observations: number;
  amount_unavailable_observations: number;
  supporting_activity_ids: string[];
  support_truncated: boolean;
}

export interface WalletCaseCounterpartyFlow {
  canonical_address: string;
  incoming_observations: number;
  outgoing_observations: number;
  unknown_direction_observations: number;
  supporting_activity_ids: string[];
  support_truncated: boolean;
}

export interface WalletCaseProtocolFlow {
  protocol_id: string;
  family: string | null;
  version: string | null;
  label: string | null;
  swap_observations: number;
  supporting_activity_ids: string[];
  support_truncated: boolean;
}

export interface WalletCaseFinding {
  public_id: string;
  rule_id: WalletCaseFindingRule;
  category: "data_quality" | "transaction_outcome" | "flow_pattern";
  importance: "information" | "attention";
  title: string;
  explanation: string;
  affected_count: number;
  support_basis: "activity_rows" | "coverage_gaps" | "identity_conflicts";
  supporting_activities: WalletCaseFindingSupport[];
  support_truncated: boolean;
  evidence_level: WalletCaseFindingEvidenceLevel;
}

export interface WalletCaseFindings {
  contract_version: "wallet_case_findings_v1";
  public_id: string;
  content_hash_sha256: string;
  case_public_id: string;
  snapshot_public_id: string;
  subject: {
    network: "ton-mainnet" | "ton-testnet";
    data_environment: "demo" | "live";
    wallet_account_canonical: string;
  };
  snapshot: WalletCaseActivitySnapshot;
  activity_revision: {
    digest_sha256: string;
    aggregate: {
      total_items: number;
      transactions: number;
      transfers: number;
      swaps: number;
      failed_transactions: number;
      source_sync_count: number;
      suppressed_duplicate_observations: number;
      conflicted_identity_count: number;
    };
    observed_period: { start_at: string; end_at: string } | null;
  };
  evidence_revision: {
    digest_sha256: string;
    total_attempts: number;
    returned_revalidated: number;
    history_truncated: boolean;
  };
  flows: {
    identified_asset_count: number;
    returned_asset_count: number;
    assets_truncated: boolean;
    unavailable_asset_observations: number;
    identified_counterparty_count: number;
    returned_counterparty_count: number;
    counterparties_truncated: boolean;
    unavailable_counterparty_observations: number;
    recognized_protocol_count: number;
    returned_protocol_count: number;
    protocols_truncated: boolean;
    unrecognized_protocol_observations: number;
    asset_flows: WalletCaseAssetFlow[];
    counterparty_flows: WalletCaseCounterpartyFlow[];
    protocol_flows: WalletCaseProtocolFlow[];
  };
  findings: WalletCaseFinding[];
  gaps: Array<{
    code: string;
    surface: string | null;
    start_at: string | null;
    end_at: string | null;
    message: string;
  }>;
  limitations: WalletCaseLimitation[];
  truth_boundaries: {
    establishes_complete_wallet_history: false;
    establishes_ownership_or_control: false;
    establishes_illicit_or_safe_status: false;
    absence_of_findings_means_safe: false;
    cross_asset_amounts_are_comparable: false;
    includes_raw_provider_payloads: false;
  };
}

export interface WalletCaseFindingsResponse {
  case_public_id: string;
  snapshot_public_id: string | null;
  findings: WalletCaseFindings | null;
  limitations: WalletCaseLimitation[];
}

const DIGEST = /^[0-9a-f]{64}$/;
const FINDINGS_ID = /^fset_[0-9a-f]{64}$/;
const FINDING_ID = /^finding_[0-9a-f]{64}$/;
const DECIMAL = /^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$/;
const NETWORKS = new Set(["ton-mainnet", "ton-testnet"] as const);
const ENVIRONMENTS = new Set(["demo", "live"] as const);
const KINDS = new Set(["transaction", "transfer", "swap"] as const);
const LEVELS = new Set<WalletCaseFindingEvidenceLevel>([
  "fixture",
  "normalized_provider_observation",
  "locally_verified",
  "chain_inclusion_proven",
]);
const LEVEL_SCORE: Record<WalletCaseFindingEvidenceLevel, number> = {
  fixture: 0,
  normalized_provider_observation: 1,
  locally_verified: 2,
  chain_inclusion_proven: 3,
};
const RULES = new Set<WalletCaseFindingRule>([
  "activity_coverage_gaps_v1",
  "activity_identity_conflicts_v1",
  "failed_transaction_observations_v1",
  "unavailable_asset_identity_v1",
  "unavailable_counterparty_identity_v1",
  "repeated_counterparty_observations_v1",
  "recognized_protocol_observations_v1",
]);
const CATEGORIES = new Set(["data_quality", "transaction_outcome", "flow_pattern"] as const);
const IMPORTANCE = new Set(["information", "attention"] as const);
const SUPPORT_BASIS = new Set(["activity_rows", "coverage_gaps", "identity_conflicts"] as const);

export function parseWalletCaseFindingsResponse(value: unknown): WalletCaseFindingsResponse {
  const response = exactRecord(value, ["case_public_id", "snapshot_public_id", "findings", "limitations"], "Wallet Case Findings response");
  const caseId = uuid(response.case_public_id, "Wallet Case Findings case ID");
  const snapshotId = response.snapshot_public_id === null
    ? null
    : uuid(response.snapshot_public_id, "Wallet Case Findings snapshot ID");
  const limitations = parseLimitations(response.limitations, "Wallet Case Findings response limitations");
  const findings = response.findings === null ? null : parseFindings(response.findings);
  if ((findings === null) !== (snapshotId === null)) fail("Wallet Case Findings availability is inconsistent");
  if (findings) {
    if (findings.case_public_id !== caseId || findings.snapshot_public_id !== snapshotId || limitations.length !== 0) {
      fail("Wallet Case Findings response scope is inconsistent");
    }
  } else if (limitations.length !== 1 || limitations[0].code !== "not_synchronized") {
    fail("Missing Wallet Case Findings requires not_synchronized");
  }
  return { case_public_id: caseId, snapshot_public_id: snapshotId, findings, limitations };
}

function parseFindings(value: unknown): WalletCaseFindings {
  const item = exactRecord(value, [
    "contract_version", "public_id", "content_hash_sha256", "case_public_id", "snapshot_public_id",
    "subject", "snapshot", "activity_revision", "evidence_revision", "flows", "findings", "gaps",
    "limitations", "truth_boundaries",
  ], "Wallet Case Findings");
  literal(item.contract_version, "wallet_case_findings_v1", "Wallet Case Findings contract");
  const publicId = boundedText(item.public_id, "Wallet Case Findings ID", 69);
  const contentHash = digest(item.content_hash_sha256, "Wallet Case Findings content hash");
  if (!FINDINGS_ID.test(publicId) || publicId !== `fset_${contentHash}`) fail("Wallet Case Findings content address is invalid");
  const caseId = uuid(item.case_public_id, "Wallet Case Findings case ID");
  const snapshotId = uuid(item.snapshot_public_id, "Wallet Case Findings snapshot ID");

  const subjectValue = exactRecord(item.subject, ["network", "data_environment", "wallet_account_canonical"], "Wallet Case Findings subject");
  const network = enumValue(subjectValue.network, NETWORKS, "Wallet Case Findings network");
  const environment = enumValue(subjectValue.data_environment, ENVIRONMENTS, "Wallet Case Findings environment");
  const account = boundedText(subjectValue.wallet_account_canonical, "Wallet Case Findings account", 67);
  if (!isCanonicalRawTonAddress(account) || !/^(?:0|-1):/.test(account)) fail("Wallet Case Findings account is invalid");

  const snapshot = parseSnapshot(item.snapshot);
  if (snapshot.public_id !== snapshotId || (environment === "demo") !== (snapshot.data_mode === "mock")) {
    fail("Wallet Case Findings snapshot is inconsistent");
  }
  const activityRevision = parseActivityRevision(item.activity_revision);
  const evidenceRevision = parseEvidenceRevision(item.evidence_revision);
  const flows = parseFlows(item.flows, network);

  if (!Array.isArray(item.findings) || item.findings.length > 100) fail("Wallet Case Findings rules are invalid");
  const findings = item.findings.map((entry, index) => parseFinding(entry, index, environment));
  if (new Set(findings.map((entry) => entry.public_id)).size !== findings.length) fail("Wallet Case Finding IDs must be distinct");
  if (!Array.isArray(item.gaps)) fail("Wallet Case Findings gaps are invalid");
  const gaps = item.gaps.map((entry, index) => parseGap(entry, index));
  const limitations = parseLimitations(item.limitations, "Wallet Case Findings limitations");
  if (new Set(limitations.map((entry) => entry.code)).size !== limitations.length) fail("Wallet Case Findings limitations must be distinct");
  const truth = exactRecord(item.truth_boundaries, [
    "establishes_complete_wallet_history", "establishes_ownership_or_control",
    "establishes_illicit_or_safe_status", "absence_of_findings_means_safe",
    "cross_asset_amounts_are_comparable", "includes_raw_provider_payloads",
  ], "Wallet Case Findings truth boundaries");
  const truthBoundaries = {
    establishes_complete_wallet_history: literal(truth.establishes_complete_wallet_history, false, "complete history boundary"),
    establishes_ownership_or_control: literal(truth.establishes_ownership_or_control, false, "ownership boundary"),
    establishes_illicit_or_safe_status: literal(truth.establishes_illicit_or_safe_status, false, "classification boundary"),
    absence_of_findings_means_safe: literal(truth.absence_of_findings_means_safe, false, "absence boundary"),
    cross_asset_amounts_are_comparable: literal(truth.cross_asset_amounts_are_comparable, false, "cross-asset boundary"),
    includes_raw_provider_payloads: literal(truth.includes_raw_provider_payloads, false, "raw payload boundary"),
  };

  return {
    contract_version: "wallet_case_findings_v1",
    public_id: publicId,
    content_hash_sha256: contentHash,
    case_public_id: caseId,
    snapshot_public_id: snapshotId,
    subject: { network, data_environment: environment, wallet_account_canonical: account },
    snapshot,
    activity_revision: activityRevision,
    evidence_revision: evidenceRevision,
    flows,
    findings,
    gaps,
    limitations,
    truth_boundaries: truthBoundaries,
  };
}

function parseSnapshot(value: unknown): WalletCaseActivitySnapshot {
  const item = exactRecord(value, ["public_id", "state", "completed_at", "data_mode", "provider", "requested_period", "coverage"], "Wallet Case Findings snapshot");
  const requestedPeriod = parsePeriod(item.requested_period, "Wallet Case Findings requested period");
  const coverage = parseWalletCaseCoverage(item.coverage);
  if (coverage.requested_start_at !== requestedPeriod.start_at || coverage.requested_end_at !== requestedPeriod.end_at) {
    fail("Wallet Case Findings snapshot coverage changed");
  }
  return {
    public_id: uuid(item.public_id, "Wallet Case Findings snapshot ID"),
    state: enumValue(item.state, new Set(["partial", "succeeded"] as const), "Wallet Case Findings snapshot state"),
    completed_at: timestamp(item.completed_at, "Wallet Case Findings snapshot completion"),
    data_mode: enumValue(item.data_mode, new Set(["mock", "real"] as const), "Wallet Case Findings snapshot mode"),
    provider: boundedText(item.provider, "Wallet Case Findings snapshot provider", 64),
    requested_period: requestedPeriod,
    coverage,
  };
}

function parseActivityRevision(value: unknown): WalletCaseFindings["activity_revision"] {
  const item = exactRecord(value, ["digest_sha256", "aggregate", "observed_period"], "Wallet Case Findings Activity revision");
  const aggregateValue = exactRecord(item.aggregate, [
    "total_items", "transactions", "transfers", "swaps", "failed_transactions", "source_sync_count",
    "suppressed_duplicate_observations", "conflicted_identity_count",
  ], "Wallet Case Findings Activity aggregate");
  const aggregate = {
    total_items: integer(aggregateValue.total_items, "Activity total"),
    transactions: integer(aggregateValue.transactions, "transaction total"),
    transfers: integer(aggregateValue.transfers, "transfer total"),
    swaps: integer(aggregateValue.swaps, "swap total"),
    failed_transactions: integer(aggregateValue.failed_transactions, "failed transaction total"),
    source_sync_count: integer(aggregateValue.source_sync_count, "source sync total"),
    suppressed_duplicate_observations: integer(aggregateValue.suppressed_duplicate_observations, "suppressed total"),
    conflicted_identity_count: integer(aggregateValue.conflicted_identity_count, "conflict total"),
  };
  if (aggregate.transactions + aggregate.transfers + aggregate.swaps !== aggregate.total_items || aggregate.failed_transactions > aggregate.transactions) {
    fail("Wallet Case Findings Activity aggregate is inconsistent");
  }
  return {
    digest_sha256: digest(item.digest_sha256, "Wallet Case Findings Activity digest"),
    aggregate,
    observed_period: item.observed_period === null ? null : parsePeriod(item.observed_period, "Wallet Case Findings observed period"),
  };
}

function parseEvidenceRevision(value: unknown): WalletCaseFindings["evidence_revision"] {
  const item = exactRecord(value, ["digest_sha256", "total_attempts", "returned_revalidated", "history_truncated"], "Wallet Case Findings Evidence revision");
  const total = integer(item.total_attempts, "Evidence attempt total");
  const returned = integer(item.returned_revalidated, "returned Evidence total", 50);
  const truncated = boolean(item.history_truncated, "Evidence truncation");
  if (returned > total || truncated !== (total > returned)) fail("Wallet Case Findings Evidence revision is inconsistent");
  return { digest_sha256: digest(item.digest_sha256, "Wallet Case Findings Evidence digest"), total_attempts: total, returned_revalidated: returned, history_truncated: truncated };
}

function parseFlows(value: unknown, network: "ton-mainnet" | "ton-testnet"): WalletCaseFindings["flows"] {
  const item = exactRecord(value, [
    "identified_asset_count", "returned_asset_count", "assets_truncated", "unavailable_asset_observations",
    "identified_counterparty_count", "returned_counterparty_count", "counterparties_truncated", "unavailable_counterparty_observations",
    "recognized_protocol_count", "returned_protocol_count", "protocols_truncated", "unrecognized_protocol_observations",
    "asset_flows", "counterparty_flows", "protocol_flows",
  ], "Wallet Case flow summary");
  if (!Array.isArray(item.asset_flows) || !Array.isArray(item.counterparty_flows) || !Array.isArray(item.protocol_flows)) fail("Wallet Case flow groups are invalid");
  if (item.asset_flows.length > 50 || item.counterparty_flows.length > 50 || item.protocol_flows.length > 50) fail("Wallet Case flow groups exceed their public bound");
  const assetFlows = item.asset_flows.map((entry, index) => parseAssetFlow(entry, index, network));
  const counterpartyFlows = item.counterparty_flows.map(parseCounterpartyFlow);
  const protocolFlows = item.protocol_flows.map(parseProtocolFlow);
  const result = {
    identified_asset_count: integer(item.identified_asset_count, "identified asset total"),
    returned_asset_count: integer(item.returned_asset_count, "returned asset total", 50),
    assets_truncated: boolean(item.assets_truncated, "asset truncation"),
    unavailable_asset_observations: integer(item.unavailable_asset_observations, "unavailable asset total"),
    identified_counterparty_count: integer(item.identified_counterparty_count, "identified counterparty total"),
    returned_counterparty_count: integer(item.returned_counterparty_count, "returned counterparty total", 50),
    counterparties_truncated: boolean(item.counterparties_truncated, "counterparty truncation"),
    unavailable_counterparty_observations: integer(item.unavailable_counterparty_observations, "unavailable counterparty total"),
    recognized_protocol_count: integer(item.recognized_protocol_count, "recognized protocol total"),
    returned_protocol_count: integer(item.returned_protocol_count, "returned protocol total", 50),
    protocols_truncated: boolean(item.protocols_truncated, "protocol truncation"),
    unrecognized_protocol_observations: integer(item.unrecognized_protocol_observations, "unrecognized protocol total"),
    asset_flows: assetFlows,
    counterparty_flows: counterpartyFlows,
    protocol_flows: protocolFlows,
  };
  const dimensions: Array<[number, number, boolean, number]> = [
    [result.identified_asset_count, result.returned_asset_count, result.assets_truncated, assetFlows.length],
    [result.identified_counterparty_count, result.returned_counterparty_count, result.counterparties_truncated, counterpartyFlows.length],
    [result.recognized_protocol_count, result.returned_protocol_count, result.protocols_truncated, protocolFlows.length],
  ];
  if (dimensions.some(([total, returned, truncated, length]) => returned !== length || returned > total || truncated !== (total > returned))) fail("Wallet Case flow totals are inconsistent");
  if (new Set(assetFlows.map((entry) => entry.asset_id)).size !== assetFlows.length || new Set(counterpartyFlows.map((entry) => entry.canonical_address)).size !== counterpartyFlows.length || new Set(protocolFlows.map((entry) => entry.protocol_id)).size !== protocolFlows.length) fail("Wallet Case flow identities must be distinct");
  return result;
}

function parseAssetFlow(value: unknown, index: number, network: "ton-mainnet" | "ton-testnet"): WalletCaseAssetFlow {
  const item = exactRecord(value, [
    "asset_id", "network", "standard", "contract_address", "symbol", "inflow_amount", "outflow_amount",
    "inflow_observations", "outflow_observations", "unknown_direction_observations", "amount_unavailable_observations",
    "supporting_activity_ids", "support_truncated",
  ], `asset flow ${index}`);
  const standard = enumValue(item.standard, new Set(["native", "jetton"] as const), `asset flow ${index} standard`);
  const contract = item.contract_address === null ? null : rawAddress(item.contract_address, `asset flow ${index} contract`);
  if ((standard === "native") !== (contract === null)) fail(`asset flow ${index} identity is inconsistent`);
  const inflow = decimalOrNull(item.inflow_amount, `asset flow ${index} inflow`);
  const outflow = decimalOrNull(item.outflow_amount, `asset flow ${index} outflow`);
  const inflowCount = integer(item.inflow_observations, `asset flow ${index} inflow count`);
  const outflowCount = integer(item.outflow_observations, `asset flow ${index} outflow count`);
  const unknownCount = integer(item.unknown_direction_observations, `asset flow ${index} unknown count`);
  const unavailable = integer(item.amount_unavailable_observations, `asset flow ${index} unavailable amount count`);
  const support = activityIds(item.supporting_activity_ids, `asset flow ${index} support`);
  const truncated = boolean(item.support_truncated, `asset flow ${index} support truncation`);
  const observations = inflowCount + outflowCount + unknownCount;
  if (observations === 0 || unavailable > observations || support.length > observations || (truncated && support.length !== 50)) fail(`asset flow ${index} counts are inconsistent`);
  const flowNetwork = enumValue(item.network, NETWORKS, `asset flow ${index} network`);
  if (flowNetwork !== network) fail(`asset flow ${index} changed network`);
  return {
    asset_id: assetId(item.asset_id, `asset flow ${index} asset ID`), network: flowNetwork, standard,
    contract_address: contract, symbol: nullableText(item.symbol, `asset flow ${index} symbol`, 128),
    inflow_amount: inflow, outflow_amount: outflow, inflow_observations: inflowCount,
    outflow_observations: outflowCount, unknown_direction_observations: unknownCount,
    amount_unavailable_observations: unavailable, supporting_activity_ids: support, support_truncated: truncated,
  };
}

function parseCounterpartyFlow(value: unknown, index: number): WalletCaseCounterpartyFlow {
  const item = exactRecord(value, ["canonical_address", "incoming_observations", "outgoing_observations", "unknown_direction_observations", "supporting_activity_ids", "support_truncated"], `counterparty flow ${index}`);
  const incoming = integer(item.incoming_observations, `counterparty flow ${index} incoming`);
  const outgoing = integer(item.outgoing_observations, `counterparty flow ${index} outgoing`);
  const unknown = integer(item.unknown_direction_observations, `counterparty flow ${index} unknown`);
  const support = activityIds(item.supporting_activity_ids, `counterparty flow ${index} support`);
  const truncated = boolean(item.support_truncated, `counterparty flow ${index} truncation`);
  const observations = incoming + outgoing + unknown;
  if (observations === 0 || support.length > observations || truncated !== (observations > support.length)) fail(`counterparty flow ${index} counts are inconsistent`);
  return { canonical_address: rawAddress(item.canonical_address, `counterparty flow ${index} address`), incoming_observations: incoming, outgoing_observations: outgoing, unknown_direction_observations: unknown, supporting_activity_ids: support, support_truncated: truncated };
}

function parseProtocolFlow(value: unknown, index: number): WalletCaseProtocolFlow {
  const item = exactRecord(value, ["protocol_id", "family", "version", "label", "swap_observations", "supporting_activity_ids", "support_truncated"], `protocol flow ${index}`);
  const count = integer(item.swap_observations, `protocol flow ${index} count`);
  if (count < 1) fail(`protocol flow ${index} requires an observation`);
  const support = activityIds(item.supporting_activity_ids, `protocol flow ${index} support`);
  const truncated = boolean(item.support_truncated, `protocol flow ${index} truncation`);
  if (support.length > count || truncated !== (count > support.length)) fail(`protocol flow ${index} counts are inconsistent`);
  return { protocol_id: boundedText(item.protocol_id, `protocol flow ${index} ID`, 32), family: nullableText(item.family, `protocol flow ${index} family`, 32), version: nullableText(item.version, `protocol flow ${index} version`, 32), label: nullableText(item.label, `protocol flow ${index} label`, 128), swap_observations: count, supporting_activity_ids: support, support_truncated: truncated };
}

function parseFinding(value: unknown, index: number, environment: "demo" | "live"): WalletCaseFinding {
  const item = exactRecord(value, ["public_id", "rule_id", "category", "importance", "title", "explanation", "affected_count", "support_basis", "supporting_activities", "support_truncated", "evidence_level"], `finding ${index}`);
  const publicId = boundedText(item.public_id, `finding ${index} ID`, 72);
  if (!FINDING_ID.test(publicId)) fail(`finding ${index} ID is invalid`);
  const affected = integer(item.affected_count, `finding ${index} affected count`);
  if (affected < 1) fail(`finding ${index} requires an affected row`);
  const basis = enumValue(item.support_basis, SUPPORT_BASIS, `finding ${index} support basis`);
  if (!Array.isArray(item.supporting_activities) || item.supporting_activities.length > 50) fail(`finding ${index} support is invalid`);
  const supports = item.supporting_activities.map((entry, supportIndex) => parseSupport(entry, index, supportIndex, environment));
  if (new Set(supports.map((entry) => entry.activity_public_id)).size !== supports.length) fail(`finding ${index} support must be distinct`);
  const truncated = boolean(item.support_truncated, `finding ${index} support truncation`);
  const evidenceLevel = enumValue(item.evidence_level, LEVELS, `finding ${index} evidence level`);
  if (basis === "activity_rows") {
    if (supports.length === 0 || supports.length > affected || truncated !== (affected > supports.length)) fail(`finding ${index} Activity support is inconsistent`);
    const weakest = supports.reduce((current, support) => LEVEL_SCORE[support.evidence_level] < LEVEL_SCORE[current] ? support.evidence_level : current, supports[0].evidence_level);
    if (weakest !== evidenceLevel) fail(`finding ${index} evidence level exceeds its weakest support`);
  } else if (supports.length !== 0 || truncated) fail(`finding ${index} diagnostic support is inconsistent`);
  if (
    (environment === "demo") !== (evidenceLevel === "fixture")
    || supports.some((support) => (environment === "demo") !== (support.evidence_level === "fixture"))
  ) fail(`finding ${index} evidence origin is inconsistent`);
  return {
    public_id: publicId,
    rule_id: enumValue(item.rule_id, RULES, `finding ${index} rule`),
    category: enumValue(item.category, CATEGORIES, `finding ${index} category`),
    importance: enumValue(item.importance, IMPORTANCE, `finding ${index} importance`),
    title: boundedText(item.title, `finding ${index} title`, 120),
    explanation: boundedText(item.explanation, `finding ${index} explanation`, 500),
    affected_count: affected,
    support_basis: basis,
    supporting_activities: supports,
    support_truncated: truncated,
    evidence_level: evidenceLevel,
  };
}

function parseSupport(value: unknown, findingIndex: number, index: number, environment: "demo" | "live"): WalletCaseFindingSupport {
  const item = exactRecord(value, ["activity_public_id", "kind", "occurred_at", "evidence_level"], `finding ${findingIndex} support ${index}`);
  const level = enumValue(item.evidence_level, LEVELS, `finding ${findingIndex} support ${index} evidence`);
  const kind = enumValue(item.kind, KINDS, `finding ${findingIndex} support ${index} kind`);
  if ((environment === "demo") !== (level === "fixture")) fail(`finding ${findingIndex} support ${index} origin is inconsistent`);
  if ((level === "locally_verified" || level === "chain_inclusion_proven") && kind !== "transaction") fail(`finding ${findingIndex} support ${index} overstates derived Activity evidence`);
  return { activity_public_id: activityId(item.activity_public_id, `finding ${findingIndex} support ${index} ID`), kind, occurred_at: item.occurred_at === null ? null : timestamp(item.occurred_at, `finding ${findingIndex} support ${index} time`), evidence_level: level };
}

function parseGap(value: unknown, index: number): WalletCaseFindings["gaps"][number] {
  const item = exactRecord(value, ["code", "surface", "start_at", "end_at", "message"], `finding gap ${index}`);
  const start = item.start_at === null ? null : timestamp(item.start_at, `finding gap ${index} start`);
  const end = item.end_at === null ? null : timestamp(item.end_at, `finding gap ${index} end`);
  const startInstant = start === null ? null : parseRfc3339Instant(start);
  const endInstant = end === null ? null : parseRfc3339Instant(end);
  if ((start === null) !== (end === null) || (startInstant !== null && endInstant !== null && startInstant >= endInstant)) fail(`finding gap ${index} period is invalid`);
  return { code: boundedText(item.code, `finding gap ${index} code`, 64), surface: nullableText(item.surface, `finding gap ${index} surface`, 32), start_at: start, end_at: end, message: boundedText(item.message, `finding gap ${index} message`, 500) };
}

function parsePeriod(value: unknown, label: string): { start_at: string; end_at: string } {
  const item = exactRecord(value, ["start_at", "end_at"], label);
  const start = timestamp(item.start_at, `${label} start`);
  const end = timestamp(item.end_at, `${label} end`);
  const startInstant = parseRfc3339Instant(start);
  const endInstant = parseRfc3339Instant(end);
  if (startInstant === null || endInstant === null || startInstant >= endInstant) fail(`${label} must be half-open`);
  return { start_at: start, end_at: end };
}

function parseLimitations(value: unknown, label: string): WalletCaseLimitation[] {
  if (!Array.isArray(value)) fail(`${label} must be a list`);
  return value.map((entry, index) => {
    const item = exactRecord(entry, ["code", "message"], `${label} ${index}`);
    return { code: boundedText(item.code, `${label} ${index} code`, 64), message: boundedText(item.message, `${label} ${index} message`, 500) };
  });
}

function activityIds(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.length > 50) fail(`${label} is invalid`);
  const ids = value.map((entry, index) => activityId(entry, `${label} ${index}`));
  if (new Set(ids).size !== ids.length) fail(`${label} must be distinct`);
  return ids;
}

function activityId(value: unknown, label: string): string {
  const result = boundedText(value, label, 68);
  if (!isWalletCaseActivityPublicId(result)) fail(`${label} is invalid`);
  return result;
}

function assetId(value: unknown, label: string): string {
  const result = boundedText(value, label, 70);
  if (!isWalletCaseAssetPublicId(result)) fail(`${label} is invalid`);
  return result;
}

function rawAddress(value: unknown, label: string): string {
  const result = boundedText(value, label, 67);
  if (!isCanonicalRawTonAddress(result) || !/^(?:0|-1):/.test(result)) fail(`${label} is invalid`);
  return result;
}

function uuid(value: unknown, label: string): string {
  const result = boundedText(value, label, 36);
  if (!isWalletCaseSnapshotPublicId(result)) fail(`${label} is invalid`);
  return result;
}

function digest(value: unknown, label: string): string {
  const result = boundedText(value, label, 64);
  if (!DIGEST.test(result)) fail(`${label} is invalid`);
  return result;
}

function decimalOrNull(value: unknown, label: string): string | null {
  if (value === null) return null;
  const result = boundedText(value, label, 80);
  if (!DECIMAL.test(result)) fail(`${label} is invalid`);
  return result;
}

function timestamp(value: unknown, label: string): string {
  const result = boundedText(value, label, 40);
  if (parseRfc3339Instant(result) === null) fail(`${label} is invalid`);
  return result;
}

function boundedText(value: unknown, label: string, maximum: number): string {
  if (typeof value !== "string" || value.length === 0 || value.length > maximum || value !== value.trim()) fail(`${label} is invalid`);
  return value;
}

function nullableText(value: unknown, label: string, maximum: number): string | null {
  return value === null ? null : boundedText(value, label, maximum);
}

function integer(value: unknown, label: string, maximum = Number.MAX_SAFE_INTEGER): number {
  if (!Number.isSafeInteger(value) || (value as number) < 0 || (value as number) > maximum) fail(`${label} is invalid`);
  return value as number;
}

function boolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") fail(`${label} is invalid`);
  return value;
}

function enumValue<T extends string>(value: unknown, allowed: ReadonlySet<T>, label: string): T {
  if (typeof value !== "string" || !allowed.has(value as T)) fail(`${label} is invalid`);
  return value as T;
}

function literal<T extends string | boolean>(value: unknown, expected: T, label: string): T {
  if (value !== expected) fail(`${label} is invalid`);
  return expected;
}

function exactRecord(value: unknown, keys: readonly string[], label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) fail(`${label} must be an object`);
  const result = value as Record<string, unknown>;
  const actual = Object.keys(result).sort();
  const expected = [...keys].sort();
  if (actual.length !== expected.length || actual.some((key, index) => key !== expected[index])) fail(`${label} contains unexpected fields`);
  return result;
}

function fail(message: string): never {
  throw new Error(message);
}
