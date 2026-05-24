import type { TimeWindow } from "../types";

interface Props {
  value: TimeWindow;
  onChange: (value: TimeWindow) => void;
  customStart: string;
  customEnd: string;
  onCustomStartChange: (value: string) => void;
  onCustomEndChange: (value: string) => void;
  disabled?: boolean;
}

const OPTIONS: { value: TimeWindow; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "3d", label: "3d" },
  { value: "7d", label: "7d" },
  { value: "custom", label: "Custom" },
];

export default function TimeWindowPicker({
  value,
  onChange,
  customStart,
  customEnd,
  onCustomStartChange,
  onCustomEndChange,
  disabled,
}: Props) {
  return (
    <div className="field">
      <label className="field-label">Time window</label>
      <div className="segmented">
        {OPTIONS.map((opt) => (
          <button
            key={opt.value}
            type="button"
            className={`segment ${value === opt.value ? "segment-active" : ""}`}
            onClick={() => onChange(opt.value)}
            disabled={disabled}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {value === "custom" && (
        <div className="custom-range">
          <div className="custom-range-field">
            <label className="field-sublabel" htmlFor="custom-start">
              Start
            </label>
            <input
              id="custom-start"
              className="text-input"
              type="datetime-local"
              value={customStart}
              disabled={disabled}
              onChange={(e) => onCustomStartChange(e.target.value)}
            />
          </div>
          <div className="custom-range-field">
            <label className="field-sublabel" htmlFor="custom-end">
              End
            </label>
            <input
              id="custom-end"
              className="text-input"
              type="datetime-local"
              value={customEnd}
              disabled={disabled}
              onChange={(e) => onCustomEndChange(e.target.value)}
            />
          </div>
        </div>
      )}
    </div>
  );
}
