import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

function luminance(hex: string): number {
  const value = hex.replace("#", "");
  const channels = [0, 2, 4].map((index) =>
    Number.parseInt(value.slice(index, index + 2), 16) / 255,
  );
  const linear = channels.map((channel) =>
    channel <= 0.03928
      ? channel / 12.92
      : ((channel + 0.055) / 1.055) ** 2.4,
  );
  const [r, g, b] = linear as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(foreground: string, background: string): number {
  const a = luminance(foreground);
  const b = luminance(background);
  const lighter = Math.max(a, b);
  const darker = Math.min(a, b);
  return (lighter + 0.05) / (darker + 0.05);
}

function token(css: string, name: string, theme: "dark" | "light"): string {
  const section =
    theme === "dark"
      ? css.slice(css.indexOf(":root,\n:root[data-theme=\"dark\"]"), css.indexOf(":root[data-theme=\"light\"]"))
      : css.slice(css.indexOf(":root[data-theme=\"light\"]"));
  const match = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(section);
  if (match?.[1] === undefined) {
    throw new Error(`missing token ${name} in ${theme}`);
  }
  return match[1];
}

describe("WCAG contrast", () => {
  const css = readFileSync("src/styles/tokens.css", "utf8");

  it("keeps body, muted and faint text at AA for both themes", () => {
    for (const theme of ["dark", "light"] as const) {
      const backgrounds =
        theme === "dark" ? ["surface", "bg"] : ["surface", "bg", "bg-subtle"];
      for (const background of backgrounds) {
        for (const text of ["text", "text-muted", "text-faint"]) {
          expect(
            contrast(token(css, text, theme), token(css, background, theme)),
          ).toBeGreaterThanOrEqual(4.5);
        }
      }
    }
  });
});
