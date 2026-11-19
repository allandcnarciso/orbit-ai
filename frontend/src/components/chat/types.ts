export type LiveTurnStatus =
  | "streaming"
  | "cancelling"
  | "completed"
  | "failed"
  | "cancelled";

export type LiveTurn = {
  conversationId: string;
  userContent: string;
  userId: string | null;
  assistantId: string | null;
  assistantContent: string;
  provider: string | null;
  model: string | null;
  status: LiveTurnStatus;
  errorCode: string | null;
  errorMessage: string | null;
};