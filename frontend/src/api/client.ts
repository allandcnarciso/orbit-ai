import { API_BASE, HEALTH_URL } from "../config";
import { ApiError, NetworkError } from "./errors";
import type {
  AggregatedModelsResponse,
  CancelGenerationResponse,
  ConnectionTestResponse,
  Conversation,
  ConversationListResponse,
  ErrorEnvelope,
  HealthResponse,
  Message,
  MessageListResponse,
  ModelSelection,
  ProviderStatus,
  SendMessagePayload,
  SystemInfoResponse,
} from "./types";

const DEFAULT_TIMEOUT_MS = 20_000;

type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  body?: unknown;
  signal?: AbortSignal | undefined;
  timeoutMs?: number;
};

function mergeSignals(external: AbortSignal | undefined, controller: AbortController) {
  if (!external) {
    return () => undefined;
  }
  if (external.aborted) {
    controller.abort();
    return () => undefined;
  }
  const onAbort = () => controller.abort();
  external.addEventListener("abort", onAbort);
  return () => external.removeEventListener("abort", onAbort);
}

async function parseEnvelope(response: Response): Promise<ErrorEnvelope | null> {
  try {
    const payload: unknown = await response.json();
    if (
      typeof payload === "object" &&
      payload !== null &&
      "error" in payload &&
      typeof payload.error === "object" &&
      payload.error !== null
    ) {
      return payload as ErrorEnvelope;
    }
  } catch {
    // Non-JSON error bodies are normalized below.
  }
  return null;
}

async function throwResponseError(response: Response): Promise<never> {
  const requestId = response.headers.get("X-Request-ID");
  const envelope = await parseEnvelope(response);
  throw new ApiError({
    status: response.status,
    code: envelope?.error.code ?? "request_failed",
    message:
      envelope?.error.message ?? `Request failed with status ${response.status}`,
    requestId: envelope?.error.request_id ?? requestId,
    details: envelope?.error.details,
  });
}

export async function apiRequest<T>(
  path: string,
  { method = "GET", body, signal, timeoutMs = DEFAULT_TIMEOUT_MS }: RequestOptions = {},
): Promise<T> {
  const controller = new AbortController();
  const detach = mergeSignals(signal, controller);
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);

  let response: Response;
  try {
    const init: RequestInit = {
      method,
      headers: {
        Accept: "application/json",
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      },
      signal: controller.signal,
      credentials: "same-origin",
    };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }
    response = await fetch(path, init);
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }
    if (controller.signal.aborted) {
      throw new NetworkError("timeout");
    }
    throw new NetworkError("offline");
  } finally {
    window.clearTimeout(timer);
    detach();
  }

  const requestId = response.headers.get("X-Request-ID");

  if (!response.ok) {
    await throwResponseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (text.length === 0) {
    return undefined as T;
  }

  try {
    return JSON.parse(text) as T;
  } catch {
    throw new ApiError({
      status: response.status,
      code: "invalid_response",
      message: "The backend returned an invalid response.",
      requestId,
    });
  }
}

export const api = {
  health: (signal?: AbortSignal) =>
    apiRequest<HealthResponse>(HEALTH_URL, { signal }),

  systemInfo: (signal?: AbortSignal) =>
    apiRequest<SystemInfoResponse>(`${API_BASE}/system/info`, { signal }),

  listProviders: (signal?: AbortSignal) =>
    apiRequest<ProviderStatus[]>(`${API_BASE}/providers`, { signal }),

  testProvider: (providerId: string, signal?: AbortSignal) =>
    apiRequest<ConnectionTestResponse>(
      `${API_BASE}/providers/${encodeURIComponent(providerId)}/test`,
      { method: "POST", signal, timeoutMs: 60_000 },
    ),

  listModels: (signal?: AbortSignal) =>
    apiRequest<AggregatedModelsResponse>(`${API_BASE}/models`, {
      signal,
      timeoutMs: 60_000,
    }),

  getDefaultModel: (signal?: AbortSignal) =>
    apiRequest<ModelSelection | null>(`${API_BASE}/models/default`, { signal }),

  setDefaultModel: (selection: ModelSelection) =>
    apiRequest<ModelSelection>(`${API_BASE}/models/default`, {
      method: "PUT",
      body: selection,
    }),

  listConversations: ({
    limit = 50,
    offset = 0,
    status = "active",
    signal,
  }: {
    limit?: number;
    offset?: number;
    status?: "active" | "archived";
    signal?: AbortSignal | undefined;
  } = {}) =>
    apiRequest<ConversationListResponse>(
      `${API_BASE}/conversations?limit=${limit}&offset=${offset}&status=${status}`,
      { signal },
    ),

  createConversation: (
    input: { title?: string; provider?: string | null; model?: string | null },
    signal?: AbortSignal,
  ) =>
    apiRequest<Conversation>(`${API_BASE}/conversations`, {
      method: "POST",
      body: input,
      signal,
    }),

  listMessages: (
    conversationId: string,
    {
      limit = 100,
      beforeSequence,
      signal,
    }: {
      limit?: number;
      beforeSequence?: number | null;
      signal?: AbortSignal | undefined;
    } = {},
  ) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (beforeSequence !== null && beforeSequence !== undefined) {
      query.set("before_sequence", String(beforeSequence));
    }
    return apiRequest<MessageListResponse>(
      `${API_BASE}/conversations/${encodeURIComponent(conversationId)}/messages?${query.toString()}`,
      { signal },
    );
  },

  cancelGeneration: (conversationId: string, signal?: AbortSignal) =>
    apiRequest<CancelGenerationResponse>(
      `${API_BASE}/conversations/${encodeURIComponent(conversationId)}/cancel`,
      { method: "POST", signal },
    ),
};

/**
 * Opens the POST/SSE generation stream. Unlike apiRequest it keeps the body
 * unread so the caller can parse events incrementally.
 */
export async function openMessageStream(
  conversationId: string,
  payload: SendMessagePayload,
  signal: AbortSignal,
  { connectTimeoutMs = 30_000 }: { connectTimeoutMs?: number } = {},
): Promise<Response> {
  const controller = new AbortController();
  const relayAbort = () => controller.abort();
  if (signal.aborted) {
    controller.abort();
  } else {
    signal.addEventListener("abort", relayAbort);
  }
  const timer = window.setTimeout(() => controller.abort(), connectTimeoutMs);

  let response: Response;
  try {
    response = await fetch(
      `${API_BASE}/conversations/${encodeURIComponent(conversationId)}/messages`,
      {
        method: "POST",
        headers: {
          Accept: "text/event-stream",
          "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
        signal: controller.signal,
        credentials: "same-origin",
      },
    );
  } catch (error) {
    if (signal.aborted) {
      throw error;
    }
    if (controller.signal.aborted) {
      throw new NetworkError("timeout");
    }
    throw new NetworkError("offline");
  } finally {
    window.clearTimeout(timer);
    // The abort relay stays attached for the stream lifetime so switching
    // conversations or unmounting also cancels the response body.
  }

  if (!response.ok) {
    await throwResponseError(response);
  }
  if (response.body === null) {
    throw new ApiError({
      status: response.status,
      code: "invalid_response",
      message: "The backend returned an empty stream.",
      requestId: response.headers.get("X-Request-ID"),
    });
  }
  return response;
}

export type { Message, Conversation };