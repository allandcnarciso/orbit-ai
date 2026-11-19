import { render } from "@testing-library/react";
import { vi } from "vitest";

import App from "../App";

export function renderAt(path: string) {
  window.history.pushState({}, "", path);
  return render(<App />);
}

export type MockRoute =
  | {
      status?: number;
      body?: unknown;
      headers?: Record<string, string>;
      response?: Response;
    }
  | ((init: RequestInit) => {
      status?: number;
      body?: unknown;
      headers?: Record<string, string>;
      response?: Response;
    });

export type FetchCall = {
  url: string;
  method: string;
  body?: unknown;
};

export function installFetchMock(routes: Record<string, MockRoute>) {
  const calls: FetchCall[] = [];

  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
      const url =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.toString()
            : input.url;
      const method = (init?.method ?? "GET").toUpperCase();
      const key = `${method} ${url}`;
      const requestBody =
        typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      calls.push({ url, method, body: requestBody });

      const pathname = new URL(url, "http://localhost").pathname;
      const route =
        routes[key] ?? routes[`${method} ${pathname}`];
      if (route === undefined) {
        return new Response(
          JSON.stringify({
            error: { code: "not_found", message: `no mock for ${key}` },
          }),
          {
            status: 404,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": "mock-request",
            },
          },
        );
      }

      const resolved = typeof route === "function" ? route(init ?? {}) : route;
      if (resolved.response !== undefined) {
        return resolved.response;
      }
      const headers = {
        "Content-Type": "application/json",
        "X-Request-ID": "mock-request",
        ...resolved.headers,
      };

      return new Response(
        resolved.body === undefined ? null : JSON.stringify(resolved.body),
        { status: resolved.status ?? 200, headers },
      );
    },
  );

  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, calls };
}