export type ApiErrorOptions = {
  status: number;
  code: string;
  message: string;
  requestId?: string | null;
  details?: unknown;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string | null;
  readonly details: unknown;

  constructor({ status, code, message, requestId, details }: ApiErrorOptions) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId ?? null;
    this.details = details;
  }
}

export class NetworkError extends Error {
  readonly kind: "offline" | "timeout";

  constructor(kind: "offline" | "timeout") {
    super(kind === "timeout" ? "Request timed out" : "Network request failed");
    this.name = "NetworkError";
    this.kind = kind;
  }
}