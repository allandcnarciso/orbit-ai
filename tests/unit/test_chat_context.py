"""Unit tests for deterministic context construction."""

from __future__ import annotations

import pytest

from orbit.chat.context import budget_for, build_context, estimate_tokens
from orbit.conversations.enums import MessageRole, MessageStatus
from orbit.conversations.errors import ContextTooLarge
from orbit.storage.models import Message


def _message(
    sequence: int,
    role: MessageRole,
    content: str,
    status: MessageStatus = MessageStatus.COMPLETED,
) -> Message:
    return Message(
        id=f"m{sequence}",
        conversation_id="conv",
        sequence=sequence,
        role=role.value,
        content=content,
        status=status.value,
    )


def test_estimate_tokens_is_conservative() -> None:
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 400) == 100


def test_budget_reserves_output_tokens() -> None:
    budget = budget_for(context_length=1000, max_output_tokens=200)
    assert budget.max_tokens == 1000
    assert budget.reserve_tokens == 200
    assert budget.available_tokens == 800

    capped = budget_for(context_length=100, max_output_tokens=1000)
    assert capped.reserve_tokens == 100
    assert capped.available_tokens == 0


def test_context_preserves_order_and_roles() -> None:
    messages = [
        _message(1, MessageRole.USER, "first"),
        _message(2, MessageRole.ASSISTANT, "second"),
        _message(3, MessageRole.USER, "third"),
    ]
    built = build_context(messages, context_length=8192)
    assert [(item.role.value, item.content) for item in built] == [
        ("user", "first"),
        ("assistant", "second"),
        ("user", "third"),
    ]


def test_context_trims_oldest_messages_first() -> None:
    messages = [
        _message(
            index,
            MessageRole.USER if index % 2 else MessageRole.ASSISTANT,
            f"message-{index}-" + "x" * 90,
        )
        for index in range(1, 8)
    ]
    built = build_context(messages, context_length=200, max_output_tokens=100)

    assert "message-1-" not in "".join(item.content for item in built)
    assert built[-1].content.startswith("message-7-")
    assert len(built) == 4


def test_context_never_drops_latest_user_message() -> None:
    messages = [
        _message(1, MessageRole.USER, "old"),
        _message(2, MessageRole.ASSISTANT, "reply"),
        _message(3, MessageRole.USER, "latest"),
    ]
    built = build_context(messages, context_length=8192)
    assert built[-1].content == "latest"


def test_context_rejects_oversized_latest_message() -> None:
    messages = [_message(1, MessageRole.USER, "x" * 500)]
    with pytest.raises(ContextTooLarge):
        build_context(messages, context_length=40, max_output_tokens=10)


def test_context_excludes_incomplete_and_failed_messages() -> None:
    messages = [
        _message(1, MessageRole.USER, "kept"),
        _message(2, MessageRole.ASSISTANT, "failed", MessageStatus.FAILED),
        _message(3, MessageRole.ASSISTANT, "streaming", MessageStatus.STREAMING),
        _message(4, MessageRole.ASSISTANT, "pending", MessageStatus.PENDING),
        _message(5, MessageRole.USER, "latest"),
    ]
    built = build_context(messages, context_length=8192)
    assert [item.content for item in built] == ["kept", "latest"]


def test_system_prompt_is_prepended() -> None:
    messages = [_message(1, MessageRole.USER, "hi")]
    built = build_context(messages, system_prompt="be brief")
    assert built[0].role.value == "system"
    assert built[0].content == "be brief"


def test_context_excludes_cancelled_messages() -> None:
    messages = [
        _message(1, MessageRole.USER, "kept"),
        _message(2, MessageRole.ASSISTANT, "cancelled", MessageStatus.CANCELLED),
        _message(3, MessageRole.USER, "latest"),
    ]
    built = build_context(messages, context_length=8192)
    assert [item.content for item in built] == ["kept", "latest"]
