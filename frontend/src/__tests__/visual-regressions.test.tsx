import { readFileSync } from "node:fs";

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Logo } from "../components/Logo";
import { renderAt } from "../test/mockApi";

const tokensCss = readFileSync("src/styles/tokens.css", "utf8");
const globalCss = readFileSync("src/styles/global.css", "utf8");
const TAGLINE = "One Harness. Any Model. Infinite Possibilities.";

function blockAfter(css: string, marker: string): string {
  const markerIndex = css.indexOf(marker);
  if (markerIndex === -1) {
    throw new Error(`missing marker: ${marker}`);
  }
  const open = css.indexOf("{", markerIndex);
  let depth = 0;
  for (let index = open; index < css.length; index += 1) {
    if (css[index] === "{") {
      depth += 1;
    } else if (css[index] === "}") {
      depth -= 1;
      if (depth === 0) {
        return css.slice(open + 1, index);
      }
    }
  }
  throw new Error(`unterminated block: ${marker}`);
}

function cssRule(css: string, selector: string): string {
  return blockAfter(css, `${selector} {`);
}

function mediaBlock(css: string, width: number): string {
  return blockAfter(css, `@media (max-width: ${width}px) {`);
}

function token(theme: "dark" | "light", name: string): string {
  const marker = `:root[data-theme="${theme}"]`;
  const block = blockAfter(tokensCss, marker);
  const match = block.match(new RegExp(`${name}:\\s*([^;]+);`));
  if (!match?.[1]) {
    throw new Error(`missing token ${name} for ${theme}`);
  }
  return match[1].trim();
}

function luminance(hex: string): number {
  const value = hex.replace("#", "");
  const channels = [0, 2, 4].map((offset) => Number.parseInt(value.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) =>
    channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4,
  );
  return 0.2126 * linear[0]! + 0.7152 * linear[1]! + 0.0722 * linear[2]!;
}

function contrast(foreground: string, background: string): number {
  const first = luminance(foreground);
  const second = luminance(background);
  const lighter = Math.max(first, second);
  const darker = Math.min(first, second);
  return (lighter + 0.05) / (darker + 0.05);
}

describe("logo and tagline regressions", () => {
  it("renders the complete tagline with the brand icon", () => {
    const { container } = render(<Logo withText tagline={TAGLINE} />);

    expect(screen.getByText("ORBIT AI")).toBeVisible();
    expect(screen.getByText(TAGLINE)).toBeVisible();
    expect(screen.getByText(TAGLINE)).toHaveClass("sidebar__brand-tagline");
    expect(screen.getByText(TAGLINE).getAttribute("style")).toBeNull();
    expect(screen.getByText("ORBIT AI").getAttribute("style")).toBeNull();
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("keeps the expanded tagline wrappable instead of truncating it", () => {
    const taglineRule = cssRule(globalCss, ".sidebar__brand-tagline");

    expect(taglineRule).toMatch(/white-space:\s*normal/);
    expect(taglineRule).toMatch(/overflow-wrap:\s*anywhere/);
    expect(taglineRule).not.toMatch(/text-overflow:\s*ellipsis/);
    expect(taglineRule).not.toMatch(/white-space:\s*nowrap/);
  });

  it("hides the brand text when the sidebar is collapsed", () => {
    const collapsedRule = globalCss.match(
      /\.app-shell\[data-collapsed="true"\] \.sidebar__brand-text[\s\S]*?\{([\s\S]*?)\}/,
    )?.[1];

    expect(collapsedRule).toBeDefined();
    expect(collapsedRule).toContain("display: none");
  });

  it("stacks and wraps the brand text in the mobile drawer", () => {
    const mobileRule = globalCss.match(
      /\.app-shell\[data-mobile-open="true"\] \.sidebar__brand-text\s*\{([\s\S]*?)\}/,
    )?.[1];

    expect(mobileRule).toBeDefined();
    expect(mobileRule).toContain("display: flex");
    expect(globalCss).toMatch(/\.sidebar__brand-tagline[\s\S]*?white-space:\s*normal/);
  });
});

describe("unavailable capability badge contrast", () => {
  it("uses the effective badge colors with at least 4.5:1 contrast", () => {
    const offRule = cssRule(globalCss, ".badge--off");

    expect(offRule).toMatch(/opacity:\s*1/);
    expect(offRule).toMatch(/color:\s*var\(--text-muted\)/);
    expect(offRule).toMatch(/background:\s*transparent/);
    expect(offRule).toMatch(/border-style:\s*dashed/);

    for (const theme of ["dark", "light"] as const) {
      const foreground = token(theme, "--text-muted");
      const background = token(theme, "--surface");
      expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5);
    }
  });
});

describe("settings description width", () => {
  it("limits descriptive lines and stacks rows on narrow screens", () => {
    expect(cssRule(globalCss, ".settings-grid .settings-row__description")).toMatch(
      /max-width:\s*58ch/,
    );
    expect(cssRule(globalCss, ".card--muted .settings-row__description")).toMatch(
      /max-width:\s*62ch/,
    );

    const narrow = mediaBlock(globalCss, 560);
    expect(narrow).toContain(".settings-row");
    expect(narrow).toContain("flex-direction: column");
  });
});

describe("mobile topbar", () => {
  it.each([360, 390])("keeps the Chat title and locale label at %ipx", (width) => {
    const mobile = mediaBlock(globalCss, 390);

    expect(width).toBeLessThanOrEqual(390);
    expect(mobile).toContain("#orbit-locale");
    expect(mobile).toContain("max-width: 118px");
    expect(mobile).toContain(".topbar__title");
    expect(mobile).toContain("text-overflow: clip");

    renderAt("/chat");
    expect(document.querySelector(".topbar__title")?.textContent).toBe("Chat");
    expect(screen.getByLabelText("Idioma")).toBeInTheDocument();
  });
});
