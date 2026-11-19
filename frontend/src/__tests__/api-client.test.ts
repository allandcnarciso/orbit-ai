import { afterEach, describe, expect, it, vi } from "vitest";

import { api, apiRequest, openMessageStream } from "../api/client";
import { ApiError, NetworkError } from "../api/errors";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "X-Request-ID": "header-request-id",
    },
  });
}

describe("apiRequest", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("calls the real endpoint paths and parses JSON", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse([{ id: "ollama", name: "Ollama", configured: true }]),
    );
    vi.stubGlobal("fetch", fetchMock);

    const providers = await api.listProviders();

    expect(providers).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/providers",
      expect.objectContaining({ method: "GET" }),
    );
  });

  it("normalizes backend error envelopes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: "provider_unavailable",
              message: "upstream down",
              request_id: "body-request-id",
            },
          },
          502,
        ),
      ),
    );

    await expect(api.testProvider("openrouter")).rejects.toMatchObject({
      status: 502,
      code: "provider_unavailable",
      requestId: "body-request-id",
    });
  });

  it("falls back to the response header request id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(null, {
            status: 500,
            headers: { "X-Request-ID": "header-request-id" },
          }),
      ),
    );

    const error = await api.health().catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).requestId).toBe("header-request-id");
  });

  it("reports invalid JSON as a normalized error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("not json", { status: 200 })),
    );

    await expect(api.systemInfo()).rejects.toMatchObject({
      code: "invalid_response",
    });
  });

  it("reports network failures", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))),
    );

    await expect(api.listProviders()).rejects.toBeInstanceOf(NetworkError);
  });

  it("aborts slow requests as timeouts", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          }),
      ),
    );

    const pending = apiRequest("/api/v1/models", { timeoutMs: 1_000 });
    const assertion = expect(pending).rejects.toMatchObject({ kind: "timeout" });

    await vi.advanceTimersByTimeAsync(1_001);
    await assertion;
  });

  it("preserves caller aborts instead of reporting a timeout", async () => {
    const controller = new AbortController();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
            controller.abort();
          }),
      ),
    );

    await expect(
      apiRequest("/api/v1/models", { signal: controller.signal }),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("times out the SSE connection separately from the generation", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        (_input: RequestInfo | URL, init?: RequestInit) =>
          new Promise<Response>((_resolve, reject) => {
            init?.signal?.addEventListener("abort", () => {
              reject(new DOMException("Aborted", "AbortError"));
            });
          }),
      ),
    );

    const controller = new AbortController();
    const pending = openMessageStream(
      "c1",
      {
        content: "hello",
        stream: true,
        client_message_id: "client-1",
      },
      controller.signal,
      { connectTimeoutMs: 1_000 },
    );
    const assertion = expect(pending).rejects.toMatchObject({ kind: "timeout" });

    await vi.advanceTimersByTimeAsync(1_001);
    await assertion;
    vi.useRealTimers();
  });
});