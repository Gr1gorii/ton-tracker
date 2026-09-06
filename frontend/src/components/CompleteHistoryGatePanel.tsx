import {
  CheckCircle,
  DownloadSimple,
  LockKey,
  WarningCircle,
} from "@phosphor-icons/react";

import type { WalletCaseCompleteHistoryGateResponse } from "../walletCaseStreamCheckpoint";

export default function CompleteHistoryGatePanel({
  gate,
  onExport,
}: {
  gate: WalletCaseCompleteHistoryGateResponse;
  onExport: () => void;
}) {
  const { summary } = gate.document;
  return (
    <section
      className="case-checkpoint-chain case-complete-history-gate"
      aria-label="Complete-history gate"
    >
      <header>
        <span>
          <LockKey size={18} weight="fill" />
          <strong>Complete-history gate</strong>
          <small className="case-complete-history-state">Locked</small>
        </span>
        <code>{gate.gate.public_id}</code>
      </header>
      <p className="case-complete-history-verdict">
        Complete wallet history is not established.
      </p>
      <dl>
        <div>
          <dt>Prerequisites</dt>
          <dd>{summary.satisfied_check_count}/{summary.check_count}</dd>
        </div>
        <div>
          <dt>Provider streams</dt>
          <dd>{summary.stream_count}</dd>
        </div>
        <div>
          <dt>Intervals complete</dt>
          <dd>{summary.requested_interval_complete_stream_count}/{summary.stream_count}</dd>
        </div>
        <div>
          <dt>Provider terminal</dt>
          <dd>{summary.provider_terminal_stream_count}/{summary.stream_count}</dd>
        </div>
      </dl>
      <ol className="case-complete-history-checks">
        {gate.document.checks.map((check) => (
          <li className={`is-${check.status}`} key={check.code}>
            {check.status === "satisfied"
              ? <CheckCircle size={17} weight="fill" />
              : <WarningCircle size={17} weight="fill" />}
            <span>
              <b>{check.code.replace(/_/g, " ")}</b>
              <small>{check.message}</small>
            </span>
          </li>
        ))}
      </ol>
      <div className="case-complete-history-provenance">
        <span>Verified input progress</span>
        <code>{gate.gate.input_progress_public_id}</code>
        <small>
          Checkpoint cutoff: {gate.gate.checkpoint_cutoff_public_id ?? "no stream checkpoint"}
        </small>
      </div>
      <button
        className="button-secondary case-checkpoint-chain-export"
        type="button"
        onClick={onExport}
      >
        <DownloadSimple size={15} /> Export complete-history gate JSON
      </button>
      <small className="case-checkpoint-history-boundary">
        {gate.document.limitations[gate.document.limitations.length - 1]?.message}
      </small>
    </section>
  );
}
