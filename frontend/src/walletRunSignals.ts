import type {
  WalletEvidenceInsufficientRecord,
  WalletEvidenceSignalRecord,
  WalletRunSignalsResponse,
} from "./types";

export const WALLET_SIGNAL_CODES = [
  "single_counterparty_dominance",
  "high_outflow_concentration",
  "failed_transaction_ratio",
  "many_distinct_jettons",
  "repeated_identical_transfer_amounts",
  "burst_transaction_activity",
] as const;

const SIGNAL_KEYS = ["code", "confidence", "evidence", "note", "observation", "title"];
const INSUFFICIENT_KEYS = ["code", "reason"];
const RESPONSE_KEYS = [
  "evaluated",
  "insufficient_evidence",
  "is_risk_score",
  "note",
  "run_id",
  "signals",
  "wallet_address",
];
const CODES = new Set<string>(WALLET_SIGNAL_CODES);

export function validateWalletRunSignalsResponse(
  value: unknown,
  expectedRunId: number,
  expectedWalletAddress: string,
): WalletRunSignalsResponse {
  if (!isRecord(value) || !hasExactKeys(value, RESPONSE_KEYS)) fail();
  if (
    value.run_id !== expectedRunId ||
    value.wallet_address !== expectedWalletAddress ||
    value.is_risk_score !== false ||
    !Array.isArray(value.evaluated) ||
    value.evaluated.length !== WALLET_SIGNAL_CODES.length ||
    value.evaluated.some((code, index) => code !== WALLET_SIGNAL_CODES[index]) ||
    !Array.isArray(value.signals) ||
    !Array.isArray(value.insufficient_evidence) ||
    value.signals.length > WALLET_SIGNAL_CODES.length ||
    value.insufficient_evidence.length > WALLET_SIGNAL_CODES.length ||
    !validText(value.note, 2_500)
  ) {
    fail();
  }

  const signals = value.signals.map(validateSignal);
  const insufficientEvidence = value.insufficient_evidence.map(validateInsufficient);
  const representedCodes = [
    ...signals.map((row) => row.code),
    ...insufficientEvidence.map((row) => row.code),
  ];
  if (new Set(representedCodes).size !== representedCodes.length) fail();

  return {
    run_id: expectedRunId,
    wallet_address: expectedWalletAddress,
    is_risk_score: false,
    evaluated: [...WALLET_SIGNAL_CODES],
    signals,
    insufficient_evidence: insufficientEvidence,
    note: value.note,
  };
}

function validateSignal(value: unknown): WalletEvidenceSignalRecord {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, SIGNAL_KEYS) ||
    !validCode(value.code) ||
    (value.confidence !== "low" && value.confidence !== "medium" && value.confidence !== "high") ||
    !validText(value.title, 160) ||
    !validText(value.observation, 1_000) ||
    !validText(value.note, 1_500) ||
    !isRecord(value.evidence) ||
    Object.keys(value.evidence).length > 20 ||
    !isBoundedJson(value.evidence)
  ) {
    fail();
  }
  return value as unknown as WalletEvidenceSignalRecord;
}

function validateInsufficient(value: unknown): WalletEvidenceInsufficientRecord {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, INSUFFICIENT_KEYS) ||
    !validCode(value.code) ||
    !validText(value.reason, 1_000)
  ) {
    fail();
  }
  return value as unknown as WalletEvidenceInsufficientRecord;
}

function validCode(value: unknown): value is string {
  return typeof value === "string" && CODES.has(value);
}

function validText(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maxLength;
}

function isBoundedJson(value: Record<string, unknown>): boolean {
  try {
    const encoded = JSON.stringify(value);
    return typeof encoded === "string" && encoded.length <= 8_000;
  } catch {
    return false;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: string[]): boolean {
  const actual = Object.keys(value).sort();
  const expected = [...keys].sort();
  return actual.length === expected.length && actual.every((key, index) => key === expected[index]);
}

function fail(): never {
  throw new Error("Wallet insight response is incoherent.");
}
