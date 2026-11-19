"""Conversation domain: enums, errors and persistence repository."""

from orbit.conversations.enums import ConversationStatus, MessageRole, MessageStatus
from orbit.conversations.errors import (
    ConversationArchived,
    ConversationError,
    ConversationNotFound,
    GenerationInProgress,
    IdempotencyConflict,
    ServerShuttingDown,
)
from orbit.conversations.repository import (
    ConversationRepository,
    RecoveryReport,
    StartedTurn,
)

__all__ = [
    "ConversationArchived",
    "ConversationError",
    "ConversationNotFound",
    "ConversationRepository",
    "ConversationStatus",
    "GenerationInProgress",
    "IdempotencyConflict",
    "MessageRole",
    "MessageStatus",
    "RecoveryReport",
    "ServerShuttingDown",
    "StartedTurn",
]
