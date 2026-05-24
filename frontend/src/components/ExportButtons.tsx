import { exportUrl } from "../api";

interface Props {
  poolUrl: string;
  timeWindow: string;
}

export default function ExportButtons({ poolUrl, timeWindow }: Props) {
  const csv = exportUrl("csv", poolUrl, timeWindow);
  const json = exportUrl("json", poolUrl, timeWindow);

  return (
    <div className="export-buttons">
      <span className="muted small">Export (v0.1 placeholder):</span>
      <a className="btn btn-ghost" href={csv} target="_blank" rel="noreferrer">
        ⬇ CSV
      </a>
      <a className="btn btn-ghost" href={json} target="_blank" rel="noreferrer">
        ⬇ JSON
      </a>
    </div>
  );
}
