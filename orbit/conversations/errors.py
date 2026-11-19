"""Domain errors for conversations and message persistence."""

from __future__ import annotations


class ConversationError(Exception):
    """Base class for conversation-domain failures."""

    code = "conversation_error"
    http_status = 400

    def __init__(self, message: str, *, conversation_id: str | None = None) -> None:
        self.message = message
        self.conversation_id = conversation_id
        super().__init__(message)


class ConversationNotFound(ConversationError):
    code = "conversation_not_found"
    http_status = 404


class ConversationArchived(ConversationError):
    code = "conversation_archived"
    http_status = 409


class GenerationInProgress(ConversationError):
    code = "generation_in_progress"
    http_status = 409


class IdempotencyConflict(ConversationError):
    code = "idempotency_conflict"
    http_status = 409


class InvalidStatusTransition(ConversationError):
    code = "invalid_status_transition"
    http_status = 409


class ServerShuttingDown(ConversationError):
    """Raised when a generation starts while the application is shutting down.

    Uvicorn stops accepting connections before the lifespan shutdown runs, so
    this is a safety net for in-flight requests, never a normal runtime state.
    """

    code = "server_shutting_down"
    http_status = 503


class InvalidSelection(ConversationError):
    code = "invalid_selection"
    http_status = 400


class InvalidGenerationParameters(ConversationError):
    code = "invalid_generation_parameters"
    http_status = 400


class NoModelSelected(ConversationError):
    code = "no_model_selected"
    http_status = 400


class ModelNotAvailable(ConversationError):
    code = "model_not_found"
    http_status = 400


class ContextTooLarge(ConversationError):
    code = "context_too_large"
    http_status = 400
