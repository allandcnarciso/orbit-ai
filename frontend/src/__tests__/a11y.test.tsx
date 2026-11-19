import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import App from "../App";
import { installFetchMock } from "../test/mockApi";

function matchMedia(matches: boolean) {
  return (query: string): MediaQueryList =>
    ({
      matches,
      media: query,
      onchange: null,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

const CONVERSATION = {
  id: "c1",
  title: "Chat one",
  provider: null,
  model: null,
  status: "active",
  created_at: "2026-11-18T12:00:00Z",
  updated_at: "2026-11-18T12:00:00Z",
  last_message_at: null,
};

function baseRoutes() {
  return {
    "GET /api/v1/conversations": {
      body: { items: [CONVERSATION], total: 1, limit: 50, offset: 0 },
    },
    "GET /api/v1/conversations/c1/messages": {
      body: { items: [], has_more: false, next_before_sequence: null },
    },
    "GET /api/v1/models/default": { body: null },
  };
}

describe("accessibility", () => {
  it("exposes mobile menu state and closes with Escape, restoring focus", async () => {
    vi.stubGlobal("matchMedia", matchMedia(true));
    const user = userEvent.setup();
    window.history.pushState({}, "", "/chat");
    render(<App />);

    const toggle = screen.getByRole("button", {
      name: "Alternar barra lateral",
    });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveAttribute("aria-controls", "orbit-sidebar");

    const sidebar = document.getElementById("orbit-sidebar");
    expect(sidebar).not.toBeNull();
    expect(sidebar).toHaveAttribute("aria-hidden", "true");

    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(sidebar).not.toHaveAttribute("aria-hidden");
    expect(document.body.style.overflow).toBe("hidden");
    expect(sidebar?.contains(document.activeElement)).toBe(true);

    await user.keyboard("{Escape}");
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("keeps navigation links named when the sidebar is collapsed", async () => {
    window.history.pushState({}, "", "/chat");
    render(<App />);

    for (const name of ["Chat", "Modelos", "Providers", "Configurações"]) {
      expect(screen.getByRole("link", { name })).toHaveAttribute("href");
    }
  });

  it("limits the composer and exposes hint and counter to assistive tech", () => {
    window.history.pushState({}, "", "/chat");
    render(<App />);

    const composer = screen.getByLabelText("Escreva uma mensagem…");
    expect(composer).toHaveAttribute("maxLength", "32000");
    expect(composer).toHaveAttribute(
      "aria-describedby",
      "orbit-composer-hint orbit-composer-count",
    );

    fireEvent.change(composer, { target: { value: "a".repeat(25_600) } });
    const counter = document.getElementById("orbit-composer-count");
    expect(counter?.textContent).toContain("25600/32000");
    expect(counter).not.toHaveClass("visually-hidden");
  });

  it("provides a polite live region for generation announcements", () => {
    window.history.pushState({}, "", "/chat");
    render(<App />);

    const live = document.querySelector('[aria-live="polite"]');
    expect(live).not.toBeNull();
    expect(live).toHaveAttribute("role", "status");
  });

  it("focuses the composer after a failed generation", async () => {
    const user = userEvent.setup();
    installFetchMock({
      ...baseRoutes(),
      "POST /api/v1/conversations/c1/messages": {
        status: 502,
        body: {
          error: {
            code: "provider_unavailable",
            message: "upstream down",
          },
        },
      },
    });
    window.history.pushState({}, "", "/chat/c1");
    render(<App />);

    const composer = await screen.findByLabelText("Escreva uma mensagem…");
    await user.type(composer, "hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    await waitFor(() => expect(composer).toHaveFocus());
  });

  it("returns to the conversation list on mobile without auto-selecting again", async () => {
    vi.stubGlobal("matchMedia", matchMedia(true));
    installFetchMock(baseRoutes());
    const user = userEvent.setup();
    window.history.pushState({}, "", "/chat");
    render(<App />);

    const back = await screen.findByRole("button", {
      name: "Voltar para conversas",
    });
    await user.click(back);

    await waitFor(() => expect(window.location.pathname).toBe("/chat"));
    await new Promise((resolve) => window.setTimeout(resolve, 50));
    expect(window.location.pathname).toBe("/chat");
    expect(
      screen.getByPlaceholderText("Buscar conversas…"),
    ).toBeVisible();
  });
});
