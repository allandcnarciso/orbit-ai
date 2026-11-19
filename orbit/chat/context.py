"""Deterministic context construction with conservative token budgeting."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from orbit.conversations.enums import MessageRole, MessageStatus
from orbit.conversations.errors import ContextTooLarge
from orbit.providers.base import ChatMessage, Role
from orbit.storage.models import Message

DEFAULT_CONTEXT_WINDOW = 8192
DEFAULT_MAX_OUTPUT = 1024
CHARS_PER_TOKEN = 4

_ROLE_MAP = {
    MessageRole.USER.value: Role.USER,
    MessageRole.ASSISTANT.value: Role.ASSISTANT,
    MessageRole.SYSTEM.value: Role.SYSTEM,
}


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_tokens: int
    reserve_tokens: int

    @property
    def available_tokens(self) -> int:
        return max(0, self.max_tokens - self.reserve_tokens)


def estimate_tokens(text: str) -> int:
    """Conservative character-based estimate (about four characters per token)."""
    if not text:
        return 0
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def budget_for(*, context_length: int | None, max_output_tokens: int | None) -> ContextBudget:
    max_tokens = context_length if context_length and context_length > 0 else DEFAULT_CONTEXT_WINDOW
    requested_output = max_output_tokens or DEFAULT_MAX_OUTPUT
    reserve = min(max(1, requested_output), max_tokens)
    return ContextBudget(max_tokens=max_tokens, reserve_tokens=reserve)


def _eligible(message: Message) -> bool:
    return message.status == MessageStatus.COMPLETED.value and message.role in _ROLE_MAP


def build_context(
    messages: Sequence[Message],
    *,
    context_length: int | None = None,
    max_output_tokens: int | None = None,
    system_prompt: str | None = None,
) -> list[ChatMessage]:
    """Build provider messages, trimming oldest turns first.

    ``messages`` must be ordered by sequence. The newest entry is expected to be
    the latest user message (the engine appends it before calling); it is never
    dropped: if it alone exceeds the budget, ``ContextTooLarge`` is raised.
    """
    budget = budget_for(context_length=context_length, max_output_tokens=max_output_tokens)
    eligible = [message for message in messages if _eligible(message)]

    if not eligible:
        return [ChatMessage(role=Role.SYSTEM, content=system_prompt)] if system_prompt else []

    latest_user_index: int | None = None
    for index, message in enumerate(eligible):
        if message.role == MessageRole.USER.value:
            latest_user_index = index

    selected: list[Message] = []
    used = 0
    for index in range(len(eligible) - 1, -1, -1):
        message = eligible[index]
        cost = estimate_tokens(message.content)
        if used + cost > budget.available_tokens:
            if index == latest_user_index:
                raise ContextTooLarge(
                    "The latest message exceeds the model context window.",
                    conversation_id=message.conversation_id,
                )
            break
        selected.append(message)
        used += cost

    if latest_user_index is not None and not any(
        message.role == MessageRole.USER.value for message in selected
    ):
        raise ContextTooLarge(
            "The latest user message exceeds the model context window.",
            conversation_id=eligible[latest_user_index].conversation_id,
        )

    selected.reverse()
    built = [
        ChatMessage(role=_ROLE_MAP[message.role], content=message.content) for message in selected
    ]
    if system_prompt:
        built.insert(0, ChatMessage(role=Role.SYSTEM, content=system_prompt))
    return built
