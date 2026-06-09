export interface PreviewFreshnessItem {
  label: string;
  requestedValue: string;
  currentValue: string;
}

interface PreviewFreshnessStripProps {
  isStale: boolean;
  requestedAt: string;
  message: string;
  items: PreviewFreshnessItem[];
}

export default function PreviewFreshnessStrip({
  isStale,
  requestedAt,
  message,
  items,
}: PreviewFreshnessStripProps) {
  return (
    <div
      className={
        isStale
          ? "preview-freshness preview-freshness-stale"
          : "preview-freshness preview-freshness-fresh"
      }
      role="status"
      aria-live="polite"
      aria-label={`${isStale ? "Stale result" : "Fresh result"}. ${message}`}
    >
      <div className="preview-freshness-head">
        <span className="preview-freshness-dot" aria-hidden="true" />
        <strong>{isStale ? "STALE RESULT" : "FRESH RESULT"}</strong>
        <span>Requested {requestedAt}</span>
      </div>
      <div className="preview-freshness-items">
        {items.map((item) => (
          <div className="preview-freshness-item" key={item.label}>
            <span>{item.label}</span>
            <strong>{item.requestedValue}</strong>
            {item.currentValue !== item.requestedValue && (
              <small>Current: {item.currentValue}</small>
            )}
          </div>
        ))}
      </div>
      <p>{message}</p>
    </div>
  );
}
