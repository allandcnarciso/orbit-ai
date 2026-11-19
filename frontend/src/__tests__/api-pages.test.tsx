import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { installFetchMock, renderAt } from "../test/mockApi";

const providers = [
  {
    id: "ollama",
    name: "Ollama",
    configured: true,
    capabilities: { streaming: true, tools: false, vision: false, json_mode: true },
  },
  {
    id: "openrouter",
    name: "OpenRouter",
    configured: false,
    capabilities: { streaming: true, tools: true, vision: true, json_mode: true },
  },
];

const models = {
  models: [
    {
      id: "openrouter/one",
      name: "One",
      provider: "openrouter",
      context_length: 128000,
      prompt_price: 0.000001,
      completion_price: 0.000002,
      metadata: {},
    },
    {
      id: "llama3.2:latest",
      name: "Llama 3.2",
      provider: "ollama",
      context_length: null,
      prompt_price: null,
      completion_price: null,
      metadata: {},
    },
  ],
  errors: [
    { provider: "openrouter", code: "provider_unavailable", message: "offline" },
  ],
};

describe("providers page", () => {
  it("lists real provider status and tests a connection", async () => {
    installFetchMock({
      "GET /api/v1/providers": { body: providers },
      "POST /api/v1/providers/ollama/test": {
        body: {
          provider: "ollama",
          ok: true,
          latency_ms: 12.4,
          detail: null,
          model_count: 3,
        },
      },
    });
    const user = userEvent.setup();
    renderAt("/providers");

    expect(await screen.findByRole("heading", { name: "Ollama" })).toBeVisible();
    expect(screen.getByText("Configurado")).toBeVisible();
    expect(screen.getByText("Não configurado")).toBeVisible();

    const card = screen.getByRole("heading", { name: "Ollama" }).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Testar conexão" }));

    expect(await within(card).findByText(/Conexão bem-sucedida/)).toBeVisible();
    expect(within(card).getByText(/12 ms/)).toBeVisible();
    expect(within(card).getByText(/3 modelos/)).toBeVisible();
  });

  it("shows normalized errors with a retry action", async () => {
    const { calls } = installFetchMock({
      "GET /api/v1/providers": {
        status: 502,
        body: {
          error: {
            code: "provider_unavailable",
            message: "upstream down",
            request_id: "req-123",
          },
        },
      },
    });
    const user = userEvent.setup();
    renderAt("/providers");

    expect(
      await screen.findByText("O provider está indisponível."),
    ).toBeVisible();
    expect(screen.getByText(/req-123/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Tentar novamente" }));
    expect(calls.filter((call) => call.method === "GET")).toHaveLength(2);
  });

  it("renders the empty state when no provider is registered", async () => {
    installFetchMock({ "GET /api/v1/providers": { body: [] } });
    renderAt("/providers");

    expect(
      await screen.findByRole("heading", { name: "Nenhum provider disponível" }),
    ).toBeVisible();
  });

  it("localizes a failed connection test and hides the raw provider detail", async () => {
    installFetchMock({
      "GET /api/v1/providers": { body: providers },
      "POST /api/v1/providers/ollama/test": {
        body: {
          provider: "ollama",
          ok: false,
          latency_ms: 3,
          detail: "Could not reach ollama",
          model_count: null,
        },
      },
    });
    const user = userEvent.setup();
    renderAt("/providers");

    const card = (
      await screen.findByRole("heading", { name: "Ollama" })
    ).closest("article")!;
    await user.click(within(card).getByRole("button", { name: "Testar conexão" }));

    expect(
      await within(card).findByText("O provider está indisponível."),
    ).toBeVisible();
    expect(screen.queryByText(/Could not reach ollama/)).not.toBeInTheDocument();
  });
});

describe("models page", () => {
  it("lists discovered models, partial provider errors and the default", async () => {
    installFetchMock({
      "GET /api/v1/models": { body: models },
      "GET /api/v1/models/default": {
        body: { provider: "openrouter", model: "openrouter/one" },
      },
    });
    renderAt("/models");

    expect(await screen.findByText("One")).toBeVisible();
    expect(screen.getByText("Llama 3.2")).toBeVisible();
    expect(screen.getByText("Padrão")).toBeVisible();
    expect(screen.getByText(/Alguns providers não puderam ser consultados/)).toBeVisible();
    expect(screen.getByText(/O provider está indisponível/)).toBeVisible();
    expect(screen.queryByText(/offline/)).not.toBeInTheDocument();
    expect(screen.getByText(/tokens de contexto/)).toBeVisible();
  });

  it("filters models by search and provider", async () => {
    installFetchMock({
      "GET /api/v1/models": { body: models },
      "GET /api/v1/models/default": { body: null },
    });
    const user = userEvent.setup();
    renderAt("/models");

    await screen.findByText("One");
    const search = screen.getByPlaceholderText("Buscar modelos…");
    await user.type(search, "llama");

    expect(screen.queryByText("One")).not.toBeInTheDocument();
    expect(screen.getByText("Llama 3.2")).toBeVisible();

    await user.clear(search);
    await user.selectOptions(
      screen.getByLabelText("Filtrar por provider"),
      "openrouter",
    );
    expect(screen.getByText("One")).toBeVisible();
    expect(screen.queryByText("Llama 3.2")).not.toBeInTheDocument();
  });

  it("sets the default model through the real PUT contract", async () => {
    const { calls } = installFetchMock({
      "GET /api/v1/models": { body: models },
      "GET /api/v1/models/default": { body: null },
      "PUT /api/v1/models/default": {
        body: { provider: "ollama", model: "llama3.2:latest" },
      },
    });
    const user = userEvent.setup();
    renderAt("/models");

    const llamaRow = (await screen.findByText("Llama 3.2")).closest("li")!;
    await user.click(
      within(llamaRow).getByRole("button", { name: "Definir como padrão" }),
    );

    expect(
      await screen.findByText("Modelo padrão atualizado."),
    ).toBeVisible();
    const put = calls.find((call) => call.method === "PUT");
    expect(callBody(calls, "PUT")).toEqual({
      provider: "ollama",
      model: "llama3.2:latest",
    });
    expect(put?.url).toBe("/api/v1/models/default");
  });

  it("renders the empty state when no models are discovered", async () => {
    installFetchMock({
      "GET /api/v1/models": { body: { models: [], errors: [] } },
      "GET /api/v1/models/default": { body: null },
    });
    renderAt("/models");

    expect(
      await screen.findByRole("heading", { name: "Nenhum modelo descoberto" }),
    ).toBeVisible();
  });
});

describe("settings backend data", () => {
  it("shows health and system information from the backend", async () => {
    installFetchMock({
      "GET /health": {
        body: {
          status: "ok",
          version: "0.1.0.dev0",
          checks: { database: "ok" },
        },
      },
      "GET /api/v1/system/info": {
        body: {
          name: "ORBIT AI",
          version: "0.1.0.dev0",
          api_version: "v1",
          environment: "test",
          python: "3.12.3",
          platform: "Linux",
          architecture: "aarch64",
          started_at: "2026-11-18T12:00:00Z",
        },
      },
    });
    renderAt("/settings");

    expect(await screen.findByText("Operacional")).toBeVisible();
    expect(screen.getByText("database")).toBeVisible();
    expect(screen.getByText("test")).toBeVisible();
    expect(screen.getByText("3.12.3")).toBeVisible();
    expect(screen.getByText("aarch64")).toBeVisible();
  });

  it("shows a normalized error when the backend is unavailable", async () => {
    installFetchMock({
      "GET /health": {
        status: 503,
        body: {
          error: {
            code: "provider_unavailable",
            message: "database down",
            request_id: "health-req",
          },
        },
      },
      "GET /api/v1/system/info": {
        body: {
          name: "ORBIT AI",
          version: "0.1.0.dev0",
          api_version: "v1",
          environment: "test",
          python: "3.12.3",
          platform: "Linux",
          architecture: "aarch64",
          started_at: "2026-11-18T12:00:00Z",
        },
      },
    });
    renderAt("/settings");

    expect(
      await screen.findByText("O provider está indisponível."),
    ).toBeVisible();
    expect(screen.getByText(/health-req/)).toBeVisible();
  });
});

function callBody(
  calls: Array<{ method: string; body?: unknown }>,
  method: string,
): unknown {
  return calls.find((call) => call.method === method)?.body;
}