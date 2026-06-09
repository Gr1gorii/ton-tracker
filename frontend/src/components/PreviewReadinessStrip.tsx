export type PreviewReadinessTone =
  | "ready"
  | "running"
  | "fresh"
  | "stale"
  | "warning"
  | "error";

export interface PreviewReadinessItem {
  label: string;
  value: string;
}

interface PreviewReadinessStripProps {
  tone: PreviewReadinessTone;
  label: string;
  message: string;
  items: PreviewReadinessItem[];
}

export default function PreviewReadinessStrip({
  tone,
  label,
  message,
  items,
}: PreviewReadinessStripProps) {
  return (
    <div
      className={`preview-readiness preview-readiness-${tone}`}
      role={tone === "error" ? "alert" : "status"}
      aria-live={tone === "error" ? "assertive" : "polite"}
      aria-label={`${label}. ${message}`}
    >
      <div className="preview-readiness-main">
        <span className="preview-readiness-dot" aria-hidden="true" />
        <strong>{label}</strong>
        <p>{message}</p>
      </div>
      <div className="preview-readiness-items">
        {items.map((item) => (
          <div className="preview-readiness-item" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.value}</strong>
          </div>
        ))}
      </div>
    </div>
  );
}
