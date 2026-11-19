import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Conversation, Message } from "../api/types";
import { installFetchMock, renderAt } from "../test/mockApi";

const BASE_TIME = "2026-11-18T12:00:00Z";

function conversation(id: string, title: string): Conversation {
  return {
    id,
    title,
    provider: null,
    model: null,
    status: "active",
    created_at: BASE_TIME,
    updated_at: BASE_TIME,
    last_message_at: null,
  };
}

function message(
  id: string,
  conversationId: string,
  sequence: number,
  role: "user" | "assistant",
  content: string,
  status = "completed",
): Message {
  return {
    id,
    conversation_id: conversationId,
    sequence,
    role,
    content,
    status,
    provider: role === "assistant" ? "fake" : null,
    model: role === "assistant" ? "fake-model" : null,
    finish_reason: "stop",
    prompt_tokens: 1,
    completion_tokens: 2,
    total_tokens: 3,
    error_code: null,
    error_message: null,
    created_at: BASE_TIME,
    updated_at: BASE_TIME,
  };
}

function frame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function streamResponse(frames: string[], signal?: AbortSignal | null): Response {
  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      signal?.addEventListener("abort", () => {
        controller.error(new DOMException("Aborted", "AbortError"));
      });
      for (const item of frames) {
        controller.enqueue(encoder.encode(item));
      }
      controller.close();
    },
  });
  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "X-Request-ID": "sse-request",
    },
  });
}

function errorResponse(code: string, message: string, status = 502): Response {
  return new Response(
    JSON.stringify({ error: { code, message, request_id: "req-error" } }),
    {
      status,
      headers: {
        "Content-Type": "application/json",
        "X-Request-ID": "req-error",
      },
    },
  );
}

const conversationList = (items: Conversation[]) => ({
  body: { items, total: items.length, limit: 50, offset: 0 },
});

describe("chat experience", () => {
  it("creates a conversation, streams a reply, renders markdown and reloads history", async () => {
    let conversations: Conversation[] = [];
    let finished = false;
    const user = userEvent.setup();

    const { calls } = installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "POST /api/v1/conversations": (init) => {
        const body = JSON.parse(String(init.body)) as { title?: string };
        const created = conversation("c1", body.title ?? "Nova conversa");
        conversations = [created];
        return { status: 201, body: created };
      },
      "GET /api/v1/conversations/c1/messages": () => ({
        body: finished
          ? {
              items: [
                message("u1", "c1", 1, "user", "Hello"),
                message("a1", "c1", 2, "assistant", "**Hello** there"),
              ],
              has_more: false,
              next_before_sequence: null,
            }
          : { items: [], has_more: false, next_before_sequence: null },
      }),
      "POST /api/v1/conversations/c1/messages": () => {
        finished = true;
        return {
          body: undefined,
          headers: { "Content-Type": "text/event-stream" },
          // replaced below with a real streaming Response
        };
      },
    });

    // Replace the placeholder with a streaming response route.
    const fetchMock = globalThis.fetch as unknown as {
      getMockImplementation: () => (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    };
    const original = fetchMock.getMockImplementation();
    (globalThis.fetch as unknown as { mockImplementation: (fn: unknown) => void }).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/messages")
        ) {
          calls.push({
            url,
            method: "POST",
            body: init.body ? JSON.parse(String(init.body)) : undefined,
          });
          finished = true;
          return streamResponse([
            frame("message.started", {
              conversation_id: "c1",
              message_id: "a1",
              user_message_id: "u1",
              provider: "fake",
              model: "fake-model",
              sequence: 2,
            }),
            frame("content.delta", { message_id: "a1", delta: "**Hello**" }),
            frame("content.delta", { message_id: "a1", delta: " there" }),
            frame("message.completed", {
              message_id: "a1",
              content: "**Hello** there",
              provider: "fake",
              model: "fake-model",
              finish_reason: "stop",
              usage: null,
            }),
          ]);
        }
        if (original === undefined) {
          throw new Error("missing base fetch mock");
        }
        return original(input, init);
      },
    );

    renderAt("/chat");

    expect(
      await screen.findByRole("heading", { name: "Como posso ajudar?" }),
    ).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Nova conversa" }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Nova conversa" }),
    ).toBeVisible();

    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText(/there/)).toBeVisible();
    expect(screen.getAllByText("Hello").length).toBeGreaterThan(0);

    const post = calls.find(
      (call) =>
        call.method === "POST" &&
        call.url.endsWith("/api/v1/conversations/c1/messages"),
    );
    expect(post?.body).toMatchObject({
      content: "Hello",
      stream: true,
      client_message_id: expect.any(String),
    });

    await waitFor(() => {
      expect(screen.queryByText("Gerando resposta…")).not.toBeInTheDocument();
    });
    expect(screen.getByText(/fake · fake-model/)).toBeVisible();
  });

  it("reconciles dropped deltas with the authoritative terminal content", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let streaming = false;
    const user = userEvent.setup();

    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => {
        if (streaming) {
          // Never resolves: keeps the live bubble mounted, so the assertion
          // proves the terminal event replaced the deltas (not a history reload).
          return {
            response: new Response(new ReadableStream<Uint8Array>({ start() {} }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          };
        }
        return { body: { items: [], has_more: false, next_before_sequence: null } };
      },
    });

    const mock = globalThis.fetch as unknown as {
      getMockImplementation: () => (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    };
    const original = mock.getMockImplementation();
    (globalThis.fetch as unknown as { mockImplementation: (fn: unknown) => void }).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/messages")
        ) {
          streaming = true;
          return streamResponse([
            frame("message.started", {
              conversation_id: "c1",
              message_id: "a1",
              user_message_id: "u1",
              provider: "fake",
              model: "fake-model",
              sequence: 2,
            }),
            // Only a prefix arrives as deltas, as if the rest was dropped under
            // backpressure; the terminal event carries the full reply.
            frame("content.delta", { message_id: "a1", delta: "Hel" }),
            frame("message.completed", {
              message_id: "a1",
              content: "Hello there from fake",
              provider: "fake",
              model: "fake-model",
              finish_reason: "stop",
              usage: null,
            }),
          ]);
        }
        if (original === undefined) {
          throw new Error("missing base fetch mock");
        }
        return original(input, init);
      },
    );

    renderAt("/chat");

    const composer = await screen.findByLabelText("Escreva uma mensagem…");
    await user.type(composer, "Hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText("Hello there from fake")).toBeVisible();
  });

  it("finishes a short final chunk and re-enables the composer (H04)", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let finished = false;
    const user = userEvent.setup();

    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => ({
        body: finished
          ? {
              items: [
                message("u1", "c1", 1, "user", "Olá"),
                message("a1", "c1", 2, "assistant", "Hello from the mock provider with"),
              ],
              has_more: false,
              next_before_sequence: null,
            }
          : { items: [], has_more: false, next_before_sequence: null },
      }),
    });

    const mock = globalThis.fetch as unknown as {
      getMockImplementation: () => (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    };
    const original = mock.getMockImplementation();
    (globalThis.fetch as unknown as { mockImplementation: (fn: unknown) => void }).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/messages")
        ) {
          finished = true;
          return streamResponse([
            frame("message.started", {
              conversation_id: "c1",
              message_id: "a1",
              user_message_id: "u1",
              provider: "ollama",
              model: "mock:latest",
              sequence: 2,
            }),
            ...["Hello", " from", " the", " mock", " provider", " with"].map((delta) =>
              frame("content.delta", { message_id: "a1", delta }),
            ),
            frame("message.completed", {
              message_id: "a1",
              content: "Hello from the mock provider with",
              provider: "ollama",
              model: "mock:latest",
              finish_reason: "stop",
              usage: { prompt_tokens: 5, completion_tokens: 5, total_tokens: 10 },
            }),
          ]);
        }
        if (original === undefined) {
          throw new Error("missing base fetch mock");
        }
        return original(input, init);
      },
    );

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Olá");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText("Hello from the mock provider with")).toBeVisible();
    expect(await screen.findByText("Resposta concluída.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.queryByText("Gerando resposta…")).not.toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "Interromper" }),
    ).not.toBeInTheDocument();

    // The composer accepts input again once the generation ended.
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Nova");
    expect(screen.getByRole("button", { name: "Enviar" })).toBeEnabled();
  });

  it("cancels an active generation", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let finished = false;
    const user = userEvent.setup();

    const { calls } = installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => ({
        body: finished
          ? {
              items: [
                message("u1", "c1", 1, "user", "Hi"),
                message("a1", "c1", 2, "assistant", "Partial", "cancelled"),
              ],
              has_more: false,
              next_before_sequence: null,
            }
          : { items: [], has_more: false, next_before_sequence: null },
      }),
      "POST /api/v1/conversations/c1/messages": () => ({
        status: 200,
        body: undefined,
      }),
      "POST /api/v1/conversations/c1/cancel": () => {
        finished = true;
        return { body: { cancelled: true, message_id: "a1" } };
      },
    });

    // Swap the SSE route for a streaming Response while keeping the call log.
    const mock = globalThis.fetch as unknown as {
      getMockImplementation: () => (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    };
    const base = mock.getMockImplementation();
    const encoder = new TextEncoder();
    let controllerRef: ReadableStreamDefaultController<Uint8Array> | null = null;
    (globalThis.fetch as unknown as { mockImplementation: (fn: unknown) => void }).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/messages")
        ) {
          calls.push({ url, method: "POST", body: JSON.parse(String(init.body)) });
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controllerRef = controller;
              controller.enqueue(
                encoder.encode(
                  frame("message.started", {
                    conversation_id: "c1",
                    message_id: "a1",
                    user_message_id: "u1",
                    provider: "fake",
                    model: "fake-model",
                    sequence: 2,
                  }),
                ),
              );
              controller.enqueue(
                encoder.encode(
                  frame("content.delta", { message_id: "a1", delta: "Partial" }),
                ),
              );
            },
          });
          return new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          });
        }
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/cancel")
        ) {
          finished = true;
          controllerRef?.enqueue(
            encoder.encode(
              frame("message.cancelled", {
                message_id: "a1",
                content: "Partial",
                reason: "cancelled",
              }),
            ),
          );
          controllerRef?.close();
          calls.push({ url, method: "POST", body: undefined });
          return new Response(
            JSON.stringify({ cancelled: true, message_id: "a1" }),
            { status: 200, headers: { "Content-Type": "application/json" } },
          );
        }
        if (base === undefined) {
          throw new Error("missing base fetch mock");
        }
        return base(input, init);
      },
    );

    renderAt("/chat/c1");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Chat one" }),
    ).toBeVisible();

    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hi");
    await user.click(screen.getByRole("button", { name: "Enviar" }));
    await screen.findByText("Partial");

    await user.click(await screen.findByRole("button", { name: "Interromper" }));

    expect(await screen.findByText(/Cancelada/)).toBeVisible();
    expect(
      calls.some((call) => call.url.endsWith("/api/v1/conversations/c1/cancel")),
    ).toBe(true);
  });

  it("retries a failed send with the same client_message_id", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let attempts = 0;
    let finished = false;
    const user = userEvent.setup();

    const baseRoutes = {
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => ({
        body: finished
          ? {
              items: [
                message("u1", "c1", 1, "user", "Hello"),
                message("a2", "c1", 2, "assistant", "Retried"),
              ],
              has_more: false,
              next_before_sequence: null,
            }
          : { items: [], has_more: false, next_before_sequence: null },
      }),
    };

    const { calls } = installFetchMock(baseRoutes);

    const mock = globalThis.fetch as unknown as {
      getMockImplementation: () => (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    };
    const base = mock.getMockImplementation();
    const encoder = new TextEncoder();
    (globalThis.fetch as unknown as { mockImplementation: (fn: unknown) => void }).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/messages")
        ) {
          calls.push({ url, method: "POST", body: JSON.parse(String(init.body)) });
          attempts += 1;
          if (attempts === 1) {
            return errorResponse(
              "provider_unavailable",
              "upstream down",
              502,
            );
          }
          finished = true;
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              controller.enqueue(
                encoder.encode(
                  frame("message.started", {
                    conversation_id: "c1",
                    message_id: "a2",
                    user_message_id: "u1",
                    provider: "fake",
                    model: "fake-model",
                    sequence: 2,
                  }),
                ),
              );
              controller.enqueue(
                encoder.encode(
                  frame("message.completed", {
                    message_id: "a2",
                    content: "Retried",
                    provider: "fake",
                    model: "fake-model",
                    finish_reason: "stop",
                    usage: null,
                  }),
                ),
              );
              controller.close();
            },
          });
          return new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          });
        }
        if (base === undefined) {
          throw new Error("missing base fetch mock");
        }
        return base(input, init);
      },
    );

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });

    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(
      await screen.findByText("O provider está indisponível."),
    ).toBeVisible();
    await user.click(
      await screen.findByRole("button", { name: "Tentar novamente" }),
    );

    expect(await screen.findByText("Retried")).toBeVisible();

    const posts = calls.filter(
      (call) =>
        call.method === "POST" &&
        call.url.endsWith("/api/v1/conversations/c1/messages"),
    );
    expect(posts).toHaveLength(2);
    const firstBody = posts[0]?.body as { client_message_id: string };
    const secondBody = posts[1]?.body as { client_message_id: string };
    expect(firstBody.client_message_id).toBeTruthy();
    expect(secondBody.client_message_id).toBe(firstBody.client_message_id);
  });

  it("isolates conversations and aborts streaming when switching", async () => {
    const conversations = [
      conversation("c1", "Chat one"),
      conversation("c2", "Chat two"),
    ];
    let aborted = false;
    const user = userEvent.setup();

    const { calls } = installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": {
        body: {
          items: [message("m1", "c1", 1, "user", "C1 message")],
          has_more: false,
          next_before_sequence: null,
        },
      },
      "GET /api/v1/conversations/c2/messages": {
        body: {
          items: [message("m2", "c2", 1, "user", "C2 message")],
          has_more: false,
          next_before_sequence: null,
        },
      },
    });

    const mock = globalThis.fetch as unknown as {
      getMockImplementation: () => (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    };
    const base = mock.getMockImplementation();
    const encoder = new TextEncoder();
    (globalThis.fetch as unknown as { mockImplementation: (fn: unknown) => void }).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/messages")
        ) {
          calls.push({ url, method: "POST", body: JSON.parse(String(init.body)) });
          const stream = new ReadableStream<Uint8Array>({
            start(controller) {
              init.signal?.addEventListener("abort", () => {
                aborted = true;
                controller.error(new DOMException("Aborted", "AbortError"));
              });
              controller.enqueue(
                encoder.encode(
                  frame("message.started", {
                    conversation_id: "c1",
                    message_id: "a1",
                    user_message_id: "u1",
                    provider: "fake",
                    model: "fake-model",
                    sequence: 2,
                  }),
                ),
              );
              controller.enqueue(
                encoder.encode(
                  frame("content.delta", { message_id: "a1", delta: "Streaming" }),
                ),
              );
            },
          });
          return new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          });
        }
        if (base === undefined) {
          throw new Error("missing base fetch mock");
        }
        return base(input, init);
      },
    );

    renderAt("/chat");
    expect(await screen.findByText("C1 message")).toBeVisible();

    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hi");
    await user.click(screen.getByRole("button", { name: "Enviar" }));
    await screen.findByText("Streaming");

    const sidebar = screen.getByLabelText("Conversas");
    await user.click(within(sidebar).getByRole("button", { name: /Chat two/ }));

    expect(await screen.findByText("C2 message")).toBeVisible();
    expect(screen.queryByText("C1 message")).not.toBeInTheDocument();
    await waitFor(() => expect(aborted).toBe(true));
  });

  it("loads older messages with the backend cursor", async () => {
    const conversations = [conversation("c1", "Chat one")];
    const user = userEvent.setup();

    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages?limit=100": {
        body: {
          items: [message("m2", "c1", 2, "user", "Second message")],
          has_more: true,
          next_before_sequence: 2,
        },
      },
      "GET /api/v1/conversations/c1/messages?limit=100&before_sequence=2": {
        body: {
          items: [message("m1", "c1", 1, "user", "First message")],
          has_more: false,
          next_before_sequence: null,
        },
      },
    });

    renderAt("/chat/c1");

    expect(await screen.findByText("Second message")).toBeVisible();
    await user.click(
      await screen.findByRole("button", {
        name: "Carregar mensagens anteriores",
      }),
    );

    expect(await screen.findByText("First message")).toBeVisible();
    expect(screen.getByText("Second message")).toBeVisible();
  });
});
describe("streaming failures", () => {
  it("preserves partial content when the connection drops mid-stream", async () => {
    const conversations = [conversation("c1", "Chat one")];
    const encoder = new TextEncoder();
    const user = userEvent.setup();

    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": {
        body: { items: [], has_more: false, next_before_sequence: null },
      },
      "POST /api/v1/conversations/c1/messages": () => {
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(
              encoder.encode(
                frame("message.started", {
                  conversation_id: "c1",
                  message_id: "a1",
                  user_message_id: "u1",
                  provider: "fake",
                  model: "fake-model",
                  sequence: 2,
                }),
              ),
            );
            controller.enqueue(
              encoder.encode(
                frame("content.delta", { message_id: "a1", delta: "Partial reply" }),
              ),
            );
            window.setTimeout(() => controller.close(), 10);
          },
        });
        return {
          response: new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        };
      },
    });

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });

    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hi");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText(/Partial reply/)).toBeVisible();
    expect(
      screen.getAllByText("A conexão de streaming terminou inesperadamente.")
        .length,
    ).toBeGreaterThan(0);
    expect(await screen.findByText(/Falhou/)).toBeVisible();
  });
});

describe("chat error handling", () => {
  it("surfaces 409 generation conflicts without offering a safe retry", async () => {
    const conversations = [conversation("c1", "Chat one")];
    const user = userEvent.setup();
    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": {
        body: { items: [], has_more: false, next_before_sequence: null },
      },
      "POST /api/v1/conversations/c1/messages": {
        response: errorResponse(
          "generation_in_progress",
          "A generation is already running",
          409,
        ),
      },
    });

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(
      await screen.findByText("Já existe uma geração em andamento nesta conversa."),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Tentar novamente" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the terminal content when the history reload fails", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let messageCalls = 0;
    const user = userEvent.setup();
    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => {
        messageCalls += 1;
        if (messageCalls === 1) {
          return {
            body: { items: [], has_more: false, next_before_sequence: null },
          };
        }
        return {
          status: 500,
          body: { error: { code: "internal_error", message: "boom" } },
        };
      },
      "POST /api/v1/conversations/c1/messages": {
        response: streamResponse([
          frame("message.started", {
            conversation_id: "c1",
            message_id: "a1",
            user_message_id: "u1",
            provider: "fake",
            model: "fake-model",
            sequence: 2,
          }),
          frame("message.completed", {
            message_id: "a1",
            content: "Persisted reply",
            provider: "fake",
            model: "fake-model",
            finish_reason: "stop",
            usage: null,
          }),
        ]),
      },
    });

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(await screen.findByText("Persisted reply")).toBeVisible();
    expect(
      await screen.findByText(/Não foi possível confirmar o histórico/),
    ).toBeVisible();
  });

  it("localizes conversation_deleted terminal failures over SSE", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let streaming = false;
    const user = userEvent.setup();

    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => {
        if (streaming) {
          return {
            response: new Response(new ReadableStream<Uint8Array>({ start() {} }), {
              status: 200,
              headers: { "Content-Type": "application/json" },
            }),
          };
        }
        return { body: { items: [], has_more: false, next_before_sequence: null } };
      },
    });

    const mock = globalThis.fetch as unknown as {
      getMockImplementation: () => (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;
    };
    const original = mock.getMockImplementation();
    (globalThis.fetch as unknown as { mockImplementation: (fn: unknown) => void }).mockImplementation(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = typeof input === "string" ? input : input.toString();
        if (
          init?.method?.toUpperCase() === "POST" &&
          url.endsWith("/api/v1/conversations/c1/messages")
        ) {
          streaming = true;
          return streamResponse([
            frame("message.started", {
              conversation_id: "c1",
              message_id: "a1",
              user_message_id: "u1",
              provider: "fake",
              model: "fake-model",
              sequence: 2,
            }),
            frame("content.delta", { message_id: "a1", delta: "Hel" }),
            frame("message.failed", {
              message_id: "a1",
              error: {
                code: "conversation_deleted",
                message: "Conversation was deleted during generation.",
                retryable: false,
              },
            }),
          ]);
        }
        if (original === undefined) {
          throw new Error("missing base fetch mock");
        }
        return original(input, init);
      },
    );

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hi");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(
      await screen.findByText(/A conversa foi excluída durante a geração\./),
    ).toBeVisible();
    expect(
      screen.queryByText(/Conversation was deleted during generation/),
    ).not.toBeInTheDocument();
  });

  it("localizes server_shutting_down and keeps the retry affordance", async () => {
    const conversations = [conversation("c1", "Chat one")];
    const user = userEvent.setup();
    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": {
        body: { items: [], has_more: false, next_before_sequence: null },
      },
      "POST /api/v1/conversations/c1/messages": {
        response: errorResponse(
          "server_shutting_down",
          "The server is shutting down; no new generation can start.",
          503,
        ),
      },
    });

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hi");
    await user.click(screen.getByRole("button", { name: "Enviar" }));

    expect(
      await screen.findByText(
        "O servidor está sendo encerrado. Tente novamente em instantes.",
      ),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Tentar novamente" }),
    ).toBeVisible();
  });

  it("reconciles the conversation when the cancel endpoint fails", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let released = false;
    let aborted = false;
    const user = userEvent.setup();
    const encoder = new TextEncoder();

    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => ({
        body: released
          ? {
              items: [
                message("u1", "c1", 1, "user", "Hello"),
                message("a1", "c1", 2, "assistant", "Partial", "cancelled"),
              ],
              has_more: false,
              next_before_sequence: null,
            }
          : { items: [], has_more: false, next_before_sequence: null },
      }),
      "POST /api/v1/conversations/c1/messages": ({ signal }) => {
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            signal?.addEventListener("abort", () => {
              aborted = true;
              controller.error(new DOMException("Aborted", "AbortError"));
            });
            controller.enqueue(
              encoder.encode(
                frame("message.started", {
                  conversation_id: "c1",
                  message_id: "a1",
                  user_message_id: "u1",
                  provider: "fake",
                  model: "fake-model",
                  sequence: 2,
                }),
              ),
            );
            controller.enqueue(
              encoder.encode(
                frame("content.delta", {
                  message_id: "a1",
                  delta: "Partial",
                }),
              ),
            );
          },
        });
        return {
          response: new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        };
      },
      "POST /api/v1/conversations/c1/cancel": () => {
        released = true;
        return {
          status: 500,
          body: { error: { code: "internal_error", message: "cancel failed" } },
        };
      },
    });

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText("Partial")).toBeVisible();

    await user.click(
      await screen.findByRole("button", { name: "Interromper" }),
    );

    expect(
      await screen.findByText("Não foi possível interromper a geração."),
    ).toBeVisible();
    expect(await screen.findByText(/Cancelada/)).toBeVisible();
    await waitFor(() => expect(aborted).toBe(true));
  });

  it("aborts and reconciles after the 8s cancel fallback", async () => {
    const conversations = [conversation("c1", "Chat one")];
    let released = false;
    let aborted = false;
    const user = userEvent.setup();
    const encoder = new TextEncoder();

    installFetchMock({
      "GET /api/v1/models/default": { body: null },
      "GET /api/v1/conversations": () => conversationList(conversations),
      "GET /api/v1/conversations/c1/messages": () => ({
        body: released
          ? {
              items: [
                message("u1", "c1", 1, "user", "Hello"),
                message("a1", "c1", 2, "assistant", "Slow", "cancelled"),
              ],
              has_more: false,
              next_before_sequence: null,
            }
          : { items: [], has_more: false, next_before_sequence: null },
      }),
      "POST /api/v1/conversations/c1/messages": ({ signal }) => {
        const stream = new ReadableStream<Uint8Array>({
          start(controller) {
            signal?.addEventListener("abort", () => {
              aborted = true;
              released = true;
              controller.error(new DOMException("Aborted", "AbortError"));
            });
            controller.enqueue(
              encoder.encode(
                frame("message.started", {
                  conversation_id: "c1",
                  message_id: "a1",
                  user_message_id: "u1",
                  provider: "fake",
                  model: "fake-model",
                  sequence: 2,
                }),
              ),
            );
            controller.enqueue(
              encoder.encode(
                frame("content.delta", { message_id: "a1", delta: "Slow" }),
              ),
            );
          },
        });
        return {
          response: new Response(stream, {
            status: 200,
            headers: { "Content-Type": "text/event-stream" },
          }),
        };
      },
      "POST /api/v1/conversations/c1/cancel": {
        body: { cancelled: true, message_id: "a1" },
      },
    });

    renderAt("/chat/c1");
    await screen.findByRole("heading", { level: 1, name: "Chat one" });
    await user.type(screen.getByLabelText("Escreva uma mensagem…"), "Hello");
    await user.click(screen.getByRole("button", { name: "Enviar" }));
    expect(await screen.findByText("Slow")).toBeVisible();

    await user.click(
      await screen.findByRole("button", { name: "Interromper" }),
    );

    expect(aborted).toBe(false);
    expect(
      await screen.findByText(/Cancelada/, {}, { timeout: 12_000 }),
    ).toBeVisible();
    expect(aborted).toBe(true);
  }, 20_000);
});
