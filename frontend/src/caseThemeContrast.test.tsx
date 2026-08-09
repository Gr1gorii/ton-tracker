// @ts-expect-error -- Vitest runs this regression in Node; the browser bundle intentionally omits Node ambient types.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const designCss = readFileSync("src/gram-design.css", "utf8");

interface Rgb {
  red: number;
  green: number;
  blue: number;
}

function themeBlock(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escaped}\\s*\\{([\\s\\S]*?)\\n\\}`).exec(designCss);
  if (!match) throw new Error(`Theme block ${selector} is missing`);
  return match[1];
}

function token(block: string, name: string): string {
  const match = new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`).exec(block);
  if (!match) throw new Error(`Theme token ${name} is missing`);
  return match[1];
}

function hex(value: string): Rgb {
  const match = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(value);
  if (!match) throw new Error(`Expected a six-digit color token, received ${value}`);
  return {
    red: Number.parseInt(match[1], 16),
    green: Number.parseInt(match[2], 16),
    blue: Number.parseInt(match[3], 16),
  };
}

function mix(foreground: Rgb, background: Rgb, weight: number): Rgb {
  return {
    red: foreground.red * weight + background.red * (1 - weight),
    green: foreground.green * weight + background.green * (1 - weight),
    blue: foreground.blue * weight + background.blue * (1 - weight),
  };
}

function luminance(color: Rgb): number {
  const channels = [color.red, color.green, color.blue].map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(first: Rgb, second: Rgb): number {
  const lighter = Math.max(luminance(first), luminance(second));
  const darker = Math.min(luminance(first), luminance(second));
  return (lighter + 0.05) / (darker + 0.05);
}

function expectCaseDangerContrast(block: string): void {
  const danger = hex(token(block, "--danger"));
  const surface = hex(token(block, "--surface-solid"));
  const errorBackground = mix(danger, surface, 0.07);
  expect(contrast(hex(token(block, "--case-danger-text")), errorBackground)).toBeGreaterThanOrEqual(4.5);
  expect(contrast(
    hex(token(block, "--case-danger-button-text")),
    hex(token(block, "--case-danger-button-bg")),
  )).toBeGreaterThanOrEqual(4.5);
}

describe("Wallet Case danger contrast", () => {
  it("meets WCAG AA for small error and destructive text in both themes", () => {
    expectCaseDangerContrast(themeBlock(":root"));
    expectCaseDangerContrast(themeBlock(':root[data-theme="dark"]'));
  });
});
