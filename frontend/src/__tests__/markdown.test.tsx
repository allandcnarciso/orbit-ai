import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SafeMarkdown } from "../components/SafeMarkdown";
import { I18nProvider } from "../i18n";

const DANGEROUS = [
  '<script>alert("xss")</script>',
  "",
  "**bold text**",
  "",
  "[bad](javascript:alert(1)) [good](https://example.com)",
  "",
  "```js",
  "const x = 1;",
  "```",
].join("\n");

describe("SafeMarkdown", () => {
  it("renders markdown but never raw HTML or unsafe URLs", () => {
    const { container } = render(
      <I18nProvider initialLocale="pt-BR">
        <SafeMarkdown content={DANGEROUS} />
      </I18nProvider>,
    );

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("strong")?.textContent).toBe("bold text");
    expect(screen.queryByRole("link", { name: "bad" })).not.toBeInTheDocument();
    expect(screen.getByText("bad")).toBeVisible();

    const good = screen.getByRole("link", { name: "good" });
    expect(good).toHaveAttribute("href", "https://example.com");
    expect(good).toHaveAttribute("target", "_blank");
    expect(good).toHaveAttribute("rel", "noopener noreferrer nofollow");

    const code = container.querySelector("pre code");
    expect(code).not.toBeNull();
    expect(code?.textContent).toContain("const x = 1;");
  });

  it("drops data URLs and keeps safe links", () => {
    render(
      <I18nProvider initialLocale="pt-BR">
        <SafeMarkdown content="[data](data:text/html;base64,PHNjcmlwdD4=) [ok](https://example.com)" />
      </I18nProvider>,
    );

    expect(screen.queryByRole("link", { name: "data" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "ok" })).toHaveAttribute(
      "href",
      "https://example.com",
    );
  });

  it("blocks remote images and keeps their alt text accessible", () => {
    const { container } = render(
      <I18nProvider initialLocale="pt-BR">
        <SafeMarkdown content="![pixel](https://tracker.example/x.png)\n\n![local](http://example.com/y.png)" />
      </I18nProvider>,
    );

    expect(container.querySelector("img")).toBeNull();
    expect(screen.getAllByText(/Imagem externa bloqueada/)).toHaveLength(2);
    expect(screen.getByRole("img", { name: /pixel/ })).toBeVisible();
  });
});
