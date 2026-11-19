export type HealthResponse = {
  status: string;
  version: string;
  checks: Record<string, string>;
};

export type SystemInfoResponse = {
  name: string;
  version: string;
  api_version: string;
  environment: string;
  python: string;
  platform: string;
  architecture: string;
  started_at: string;
};

export type ProviderCapabilities = {
  streaming: boolean;
  tools: boolean;
  vision: boolean;
  json_mode: boolean;
};

export type ProviderStatus = {
  id: string;
  name: string;
  configured: boolean;
  capabilities: ProviderCapabilities;
};

export type ModelInfo = {
  id: string;
  name: string;
  provider: string;
  context_length: number | null;
  prompt_price: number | null;
  completion_price: number | null;
  metadata: Record<string, unknown>;
};

export type ProviderErrorInfo = {
  provider: string;
  code: string;
  message: string;
};

export type AggregatedModelsResponse = {
  models: ModelInfo[];
  errors: ProviderErrorInfo[];
};

export type ModelSelection = {
  provider: string;
  model: string;
};

export type ConnectionTestResponse = {
  provider: string;
  ok: boolean;
  latency_ms: number;
  detail: string | null;
  code?: string | null;
  model_count: number | null;
};

export type ErrorDetail = {
  code: string;
  message: string;
  request_id?: string;
  details?: unknown;
};

export type ErrorEnvelope = {
  error: ErrorDetail;
};

export type Conversation = {
  id: string;
  title: string;
  provider: string | null;
  model: string | null;
  status: string;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
};

export type ConversationListResponse = {
  items: Conversation[];
  total: number;
  limit: number;
  offset: number;
};

export type Message = {
  id: string;
  conversation_id: string;
  sequence: number;
  role: string;
  content: string;
  status: string;
  provider: string | null;
  model: string | null;
  finish_reason: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
};

export type MessageListResponse = {
  items: Message[];
  has_more: boolean;
  next_before_sequence: number | null;
};

export type SendMessagePayload = {
  content: string;
  stream: boolean;
  client_message_id: string;
  provider?: string | null;
  model?: string | null;
};

export type CancelGenerationResponse = {
  cancelled: boolean;
  message_id: string | null;
};

export type MessageStartedData = {
  conversation_id: string;
  message_id: string;
  user_message_id: string;
  provider: string;
  model: string;
  sequence: number;
};

export type ContentDeltaData = {
  message_id: string;
  delta: string;
};

export type MessageCompletedData = {
  message_id: string;
  content: string;
  provider: string;
  model: string;
  finish_reason: string | null;
  usage: {
    prompt_tokens: number;
    completion_tokens: number;
    total_tokens: number;
  } | null;
};

export type MessageFailedData = {
  message_id: string;
  error: { code: string; message: string; retryable: boolean };
};

export type MessageCancelledData = {
  message_id: string;
  content: string;
  reason: string;
};