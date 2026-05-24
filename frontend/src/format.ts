// Display formatting helpers.

export function shortAddress(addr: string): string {
  if (addr.length <= 14) return addr;
  return `${addr.slice(0, 8)}…${addr.slice(-4)}`;
}

export function formatUsd(value: number, maxFrac = 2): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: maxFrac,
  }).format(value);
}

export function formatNum(value: number, maxFrac = 0): string {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: maxFrac,
  }).format(value);
}

export function formatPct(value: number): string {
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toFixed(2)}%`;
}

export function formatSignedUsd(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "-" : "";
  return `${sign}${formatUsd(Math.abs(value))}`;
}

export function formatPrice(value: number): string {
  if (value === 0) return "$0";
  if (value < 0.01) {
    // Trim trailing zeros at 6 significant digits for tiny prices.
    return `$${parseFloat(value.toPrecision(6)).toString()}`;
  }
  return formatUsd(value, 4);
}

// pnl sign class for green/red coloring
export function pnlClass(value: number): string {
  if (value > 0) return "pnl-pos";
  if (value < 0) return "pnl-neg";
  return "pnl-zero";
}

export const STATUS_LABELS: Record<string, string> = {
  holder: "Holder",
  partial_seller: "Partial seller",
  full_exit: "Full exit",
  unknown: "Unknown",
};
