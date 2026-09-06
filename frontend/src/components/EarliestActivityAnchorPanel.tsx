import {
  CheckCircle,
  DownloadSimple,
  LinkSimple,
  WarningCircle,
} from "@phosphor-icons/react";

import type {
  WalletCaseEarliestActivityAnchorResponse,
  WalletCaseEarliestActivityAnchorState,
} from "../walletCaseStreamCheckpoint";

const STATE_LABELS: Record<WalletCaseEarliestActivityAnchorState, string> = {
  empty: "No candidate",
  ineligible: "Ineligible",
  verification_required: "Proof required",
  predecessor_present: "Earlier transaction found",
  verified: "Verified",
};

const STATE_VERDICTS: Record<WalletCaseEarliestActivityAnchorState, string> = {
  empty: "No canonical provider-observed transaction is available to anchor.",
  ineligible: "Earliest activity cannot be established outside a live data environment.",
  verification_required: "Verify the candidate transaction in Evidence to inspect its predecessor.",
  predecessor_present: "The candidate has an earlier predecessor, so it is not the wallet's first activity.",
  verified: "Earliest wallet activity is anchored to canonical chain evidence.",
};

function formatTimestamp(value: string | null): string {
  if (!value) return "Not timestamped";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

function yesNo(value: boolean | null, yes: string, no: string): string {
  return value === null ? "Unknown" : value ? yes : no;
}

export default function EarliestActivityAnchorPanel({
  anchor,
  onExport,
}: {
  anchor: WalletCaseEarliestActivityAnchorResponse;
  onExport: () => void;
}) {
  const { candidate, proof, summary } = anchor.document;
  return (
    <section
      className={`case-checkpoint-chain case-earliest-activity-anchor is-${summary.state}`}
      aria-label="Earliest activity anchor"
    >
      <header>
        <span>
          <LinkSimple size={18} weight="bold" />
          <strong>Earliest activity anchor</strong>
          <small className="case-earliest-anchor-state">
            {STATE_LABELS[summary.state]}
          </small>
        </span>
        <code>{anchor.anchor.public_id}</code>
      </header>
      <p className="case-earliest-anchor-verdict">
        {STATE_VERDICTS[summary.state]}
      </p>
      <dl>
        <div>
          <dt>Candidate</dt>
          <dd>{summary.candidate_available ? "Selected" : "Unavailable"}</dd>
        </div>
        <div>
          <dt>Chain inclusion</dt>
          <dd>{summary.canonical_inclusion_proven ? "Proven" : "Not proven"}</dd>
        </div>
        <div>
          <dt>Predecessor</dt>
          <dd>{yesNo(summary.predecessor_absent, "Absent", "Present")}</dd>
        </div>
        <div>
          <dt>First activity</dt>
          <dd>{summary.earliest_wallet_activity_established ? "Established" : "Not established"}</dd>
        </div>
      </dl>
      {candidate && (
        <div className="case-earliest-anchor-candidate">
          <span>Selected canonical Activity</span>
          <b>{formatTimestamp(candidate.occurred_at)}</b>
          <small>{candidate.provider} · logical time {candidate.logical_time}</small>
          <code>{candidate.activity_public_id}</code>
          <code>{candidate.transaction_hash}</code>
        </div>
      )}
      {proof && (
        <div className="case-earliest-anchor-proof">
          {proof.predecessor.absent
            ? <CheckCircle size={18} weight="fill" />
            : <WarningCircle size={18} weight="fill" />}
          <span>
            <b>
              {proof.predecessor.absent
                ? "Canonical inclusion and zero predecessor verified"
                : "Canonical inclusion verified; predecessor is present"}
            </b>
            <small>
              Block {proof.block.workchain}:{proof.block.shard}:{proof.block.seqno}
              {" · "}trust level {proof.trust_level}
            </small>
            <small>Previous logical time: {proof.predecessor.logical_time}</small>
            <code>{proof.predecessor.transaction_hash}</code>
            <code>{proof.evidence_public_id}</code>
          </span>
        </div>
      )}
      <div className="case-complete-history-provenance">
        <span>Verified input observed floor</span>
        <code>{anchor.anchor.input_floor_public_id}</code>
        <small>
          Checkpoint cutoff: {anchor.anchor.checkpoint_cutoff_public_id ?? "no stream checkpoint"}
        </small>
      </div>
      <button
        className="button-secondary case-checkpoint-chain-export"
        type="button"
        onClick={onExport}
      >
        <DownloadSimple size={15} /> Export earliest activity anchor JSON
      </button>
      <small className="case-earliest-anchor-boundary">
        A verified zero predecessor establishes the chain origin for this account, but complete-history
        status also requires acquisition coverage and reorg invalidation.
      </small>
    </section>
  );
}
