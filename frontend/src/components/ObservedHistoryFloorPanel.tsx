import {
  CheckCircle,
  ClockCounterClockwise,
  DownloadSimple,
  WarningCircle,
} from "@phosphor-icons/react";

import type { WalletCaseObservedHistoryFloorResponse } from "../walletCaseStreamCheckpoint";

function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export default function ObservedHistoryFloorPanel({
  floor,
  onExport,
}: {
  floor: WalletCaseObservedHistoryFloorResponse;
  onExport: () => void;
}) {
  const { summary } = floor.document;
  return (
    <section
      className="case-checkpoint-chain case-observed-history-floor"
      aria-label="Observed history floor"
    >
      <header>
        <span>
          <ClockCounterClockwise size={18} weight="fill" />
          <strong>Observed history floor</strong>
          <small className="case-observed-floor-state">
            {floor.document.state.replace(/_/g, " ")}
          </small>
        </span>
        <code>{floor.floor.public_id}</code>
      </header>
      <p className="case-observed-floor-verdict">
        {summary.earliest_observed_timestamp ? (
          <>
            Earliest timestamp currently observed across verified stream pages:
            {" "}<time dateTime={summary.earliest_observed_timestamp}>
              {formatTimestamp(summary.earliest_observed_timestamp)}
            </time>
          </>
        ) : (
          "No successful provider page timestamp is currently observed."
        )}
      </p>
      <dl>
        <div><dt>Streams</dt><dd>{summary.stream_count}</dd></div>
        <div><dt>Floors observed</dt><dd>{summary.observed_stream_count}/{summary.stream_count}</dd></div>
        <div><dt>Timestamped</dt><dd>{summary.timestamped_stream_count}/{summary.stream_count}</dd></div>
        <div><dt>Provider terminal</dt><dd>{summary.provider_terminal_stream_count}/{summary.stream_count}</dd></div>
      </dl>
      {floor.document.streams.length === 0 ? (
        <span>No verified provider stream checkpoint is available.</span>
      ) : (
        <ol className="case-observed-floor-streams">
          {floor.document.streams.map((stream) => (
            <li
              className={`is-${stream.floor_status}`}
              key={`${stream.provider}:${stream.stream_key}`}
            >
              {stream.floor_status === "observed"
                ? <CheckCircle size={17} weight="fill" />
                : <WarningCircle size={17} weight="fill" />}
              <span>
                <b>{stream.provider} / {stream.stream_key}</b>
                <small>
                  {stream.floor_page
                    ? `Oldest successful page ${stream.floor_page.page_index}`
                    : "No successful page is available"}
                  {stream.provider_terminal_observed
                    ? " · provider terminal observed"
                    : stream.requested_interval_complete
                      ? " · requested interval complete"
                      : " · acquisition can continue"}
                </small>
                {stream.floor_page?.min_timestamp && (
                  <small>
                    Page minimum timestamp: {formatTimestamp(stream.floor_page.min_timestamp)}
                  </small>
                )}
                {stream.floor_page?.min_logical_time && (
                  <small>Page minimum logical time: {stream.floor_page.min_logical_time}</small>
                )}
                <code>{stream.chain_public_id}</code>
              </span>
            </li>
          ))}
        </ol>
      )}
      <div className="case-complete-history-provenance">
        <span>Verified input progress</span>
        <code>{floor.floor.input_progress_public_id}</code>
        <small>
          Checkpoint cutoff: {floor.floor.checkpoint_cutoff_public_id ?? "no stream checkpoint"}
        </small>
      </div>
      <button
        className="button-secondary case-checkpoint-chain-export"
        type="button"
        onClick={onExport}
      >
        <DownloadSimple size={15} /> Export observed history floor JSON
      </button>
      <small className="case-observed-floor-boundary">
        This floor is provider page evidence, not proof of the wallet&apos;s first activity.
      </small>
    </section>
  );
}
