import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import App from "../App";

function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

describe("app shell", () => {
  it("renders navigation and the chat empty state in pt-BR", async () => {
    renderAt("/chat");

    const nav = screen.getByRole("navigation", {
      name: "Navegação principal",
    });
    expect(within(nav).getByRole("link", { name: "Chat" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(nav).getByRole("link", { name: "Modelos" })).toBeVisible();
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Como posso ajudar?",
      }),
    ).toBeVisible();
    expect(screen.getByLabelText("Escreva uma mensagem…")).toBeEnabled();
    expect(document.documentElement.lang).toBe("pt-BR");
  });

  it("navigates between pages and marks the active item", async () => {
    const user = userEvent.setup();
    renderAt("/chat");

    await user.click(screen.getByRole("link", { name: "Modelos" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Modelos" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Modelos" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("switches the interface language and persists it", async () => {
    const user = userEvent.setup();
    renderAt("/settings");

    const languageSelectors = screen.getAllByLabelText("Idioma");
    await user.selectOptions(languageSelectors[0]!, "en-US");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Settings" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Models" })).toBeVisible();
    expect(document.documentElement.lang).toBe("en-US");
    expect(window.localStorage.getItem("orbit.locale")).toBe("en-US");
  });

  it("toggles the theme and persists the preference", async () => {
    const user = userEvent.setup();
    renderAt("/settings");

    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Tema" }));

    expect(document.documentElement.dataset.theme).toBe("light");
    expect(window.localStorage.getItem("orbit.theme")).toBe("light");
  });

  it("exposes settings information without inventing backend state", async () => {
    renderAt("/settings");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Configurações" }),
    ).toBeVisible();
    expect(screen.getByText("/api/v1")).toBeVisible();
    expect(
      screen.getByText(/nunca são armazenados no navegador/i),
    ).toBeVisible();
  });
});