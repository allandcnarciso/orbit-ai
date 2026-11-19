import type { MessageKey, Translate } from "../i18n";
import { ApiError, NetworkError } from "./errors";

const codeKeys: Record<string, MessageKey> = {
  provider_not_configured: "errors.providerNotConfigured",
  provider_unavailable: "errors.providerUnavailable",
  provider_timeout: "errors.providerTimeout",
  provider_auth_error: "errors.providerAuth",
  provider_rate_limited: "errors.providerRateLimited",
  provider_invalid_response: "errors.invalidResponse",
  model_not_found: "errors.modelNotFound",
  not_found: "errors.notFound",
  validation_error: "errors.validation",
  invalid_response: "errors.invalidResponse",
  idempotency_conflict: "errors.conflict",
  generation_in_progress: "errors.generationInProgress",
  conversation_deleted: "errors.conversationDeleted",
  server_shutting_down: "errors.serverShuttingDown",
};

export function describeError(error: unknown, t: Translate): string {
  if (error instanceof NetworkError) {
    return t(error.kind === "timeout" ? "errors.timeout" : "errors.offline");
  }
  if (error instanceof ApiError) {
    return describeErrorCode(error.code, t);
  }
  return t("errors.generic");
}

export function describeErrorCode(code: string | null, t: Translate): string {
  if (code === null) {
    return t("errors.generic");
  }
  const key = codeKeys[code];
  return key ? t(key) : t("errors.requestFailed");
}

/**
 * Localise a known error code, or return null when the catalog has no entry.
 *
 * SSE failures carry a server-authored message; the UI prefers its own
 * translation when the code is known and only falls back to that text otherwise.
 */
export function localizedErrorForCode(code: string | null, t: Translate): string | null {
  if (code === null) {
    return null;
  }
  const key = codeKeys[code];
  return key ? t(key) : null;
}