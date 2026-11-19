"""Mapping helpers between persistence models and API schemas."""

from __future__ import annotations

from orbit.api.schemas import ConversationResponse, MessageResponse
from orbit.storage.models import Conversation, Message


def conversation_to_schema(conversation: Conversation) -> ConversationResponse:
    return ConversationResponse(
        id=conversation.id,
        title=conversation.title,
        provider=conversation.provider,
        model=conversation.model,
        status=conversation.status,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        last_message_at=conversation.last_message_at,
    )


def message_to_schema(message: Message) -> MessageResponse:
    return MessageResponse(
        id=message.id,
        conversation_id=message.conversation_id,
        sequence=message.sequence,
        role=message.role,
        content=message.content,
        status=message.status,
        provider=message.provider,
        model=message.model,
        finish_reason=message.finish_reason,
        prompt_tokens=message.prompt_tokens,
        completion_tokens=message.completion_tokens,
        total_tokens=message.total_tokens,
        error_code=message.error_code,
        error_message=message.error_message,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )
