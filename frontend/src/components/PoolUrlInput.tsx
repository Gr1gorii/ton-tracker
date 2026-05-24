interface Props {
  value: string;
  onChange: (value: string) => void;
  disabled?: boolean;
}

export default function PoolUrlInput({ value, onChange, disabled }: Props) {
  return (
    <div className="field">
      <label className="field-label" htmlFor="pool-url">
        GeckoTerminal TON pool URL
      </label>
      <input
        id="pool-url"
        className="text-input"
        type="text"
        placeholder="https://www.geckoterminal.com/ton/pools/<pool_address>"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
