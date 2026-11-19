"""Conversation engine: context, model resolution, generation and SSE events."""

from orbit.chat.context import ContextBudget, budget_for, build_context, estimate_tokens
from orbit.chat.engine import (
    ConversationEngine,
    GenerationHandle,
    GenerationOutcome,
    GenerationRegistry,
    GenerationStream,
    ModelResolver,
    ResolvedModel,
)
from orbit.chat.events import (
    ContentDelta,
    GenerationEvent,
    MessageCancelled,
    MessageCompleted,
    MessageFailed,
    MessageStarted,
)

__all__ = [
    "ContentDelta",
    "ContextBudget",
    "ConversationEngine",
    "GenerationEvent",
    "GenerationHandle",
    "GenerationOutcome",
    "GenerationRegistry",
    "GenerationStream",
    "MessageCancelled",
    "MessageCompleted",
    "MessageFailed",
    "MessageStarted",
    "ModelResolver",
    "ResolvedModel",
    "budget_for",
    "build_context",
    "estimate_tokens",
]
