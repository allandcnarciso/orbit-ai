"""Conversation and message-history endpoints."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from orbit.api.deps import get_session
from orbit.api.schemas import (
    CancelGenerationResponse,
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationResponse,
    ConversationUpdateRequest,
    MessageListResponse,
    SendMessageRequest,
    SendMessageResponse,
)
from orbit.api.serializers import conversation_to_schema, message_to_schema
from orbit.chat.engine import ConversationEngine, GenerationStream
from orbit.conversations.enums import ConversationStatus
from orbit.conversations.service import ConversationService, ConversationUpdate
from orbit.providers.registry import ProviderRegistry

router = APIRouter(prefix="/conversations", tags=["conversations"])

ConversationId = Annotated[str, Path(min_length=1, max_length=64)]


def get_conversation_service(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> ConversationService:
    registry: ProviderRegistry = request.app.state.providers
    return ConversationService(session, registry=registry)


ServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=201,
    summary="Create a conversation",
)
async def create_conversation(
    payload: ConversationCreateRequest, service: ServiceDep
) -> ConversationResponse:
    conversation = await service.create_conversation(
        title=payload.title, provider=payload.provider, model=payload.model
    )
    return conversation_to_schema(conversation)


@router.get("", response_model=ConversationListResponse, summary="List conversations")
async def list_conversations(
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    status_filter: Annotated[Literal["active", "archived"] | None, Query(alias="status")] = None,
) -> ConversationListResponse:
    status = ConversationStatus(status_filter) if status_filter else None
    items, total = await service.list_conversations(limit=limit, offset=offset, status=status)
    return ConversationListResponse(
        items=[conversation_to_schema(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Retrieve a conversation",
)
async def get_conversation(
    conversation_id: ConversationId, service: ServiceDep
) -> ConversationResponse:
    return conversation_to_schema(await service.get_conversation(conversation_id))


@router.patch(
    "/{conversation_id}",
    response_model=ConversationResponse,
    summary="Rename, reselect or archive a conversation",
)
async def update_conversation(
    conversation_id: ConversationId,
    payload: ConversationUpdateRequest,
    service: ServiceDep,
) -> ConversationResponse:
    update = ConversationUpdate(
        title=payload.title,
        provider=payload.provider,
        model=payload.model,
        status=ConversationStatus(payload.status) if payload.status else None,
        fields=frozenset(payload.model_fields_set),
    )
    conversation = await service.update_conversation(conversation_id, update)
    return conversation_to_schema(conversation)


@router.delete(
    "/{conversation_id}",
    status_code=204,
    response_class=Response,
    summary="Delete a conversation and its messages",
)
async def delete_conversation(conversation_id: ConversationId, service: ServiceDep) -> Response:
    await service.delete_conversation(conversation_id)
    return Response(status_code=204)


@router.get(
    "/{conversation_id}/messages",
    response_model=MessageListResponse,
    summary="List messages in chronological order",
)
async def list_messages(
    conversation_id: ConversationId,
    service: ServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    before_sequence: Annotated[int | None, Query(ge=1)] = None,
) -> MessageListResponse:
    messages, has_more = await service.list_messages(
        conversation_id, limit=limit, before_sequence=before_sequence
    )
    return MessageListResponse(
        items=[message_to_schema(message) for message in messages],
        has_more=has_more,
        next_before_sequence=messages[0].sequence if has_more and messages else None,
    )


async def _sse_events(stream: GenerationStream) -> AsyncIterator[str]:
    """Serialise engine events, closing the generation when the client goes away.

    Starlette cancels this generator on ``http.disconnect``. The explicit
    ``finally`` makes that path deterministic: the producer is cancelled and
    awaited here instead of relying on garbage collection of the nested async
    generator, so the terminal state is persisted before the request ends.
    """
    try:
        async for event in stream:
            yield event.to_sse()
    finally:
        await stream.close()


@router.post(
    "/{conversation_id}/messages",
    response_model=SendMessageResponse,
    summary="Send a user message and generate an assistant reply",
)
async def send_message(
    conversation_id: ConversationId,
    payload: SendMessageRequest,
    request: Request,
) -> SendMessageResponse | Response:
    engine: ConversationEngine = request.app.state.engine
    if payload.stream:
        stream = await engine.start_stream(
            conversation_id,
            content=payload.content,
            provider=payload.provider,
            model=payload.model,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            client_message_id=payload.client_message_id,
        )
        return StreamingResponse(
            _sse_events(stream),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    outcome = await engine.generate(
        conversation_id,
        content=payload.content,
        provider=payload.provider,
        model=payload.model,
        temperature=payload.temperature,
        max_tokens=payload.max_tokens,
        client_message_id=payload.client_message_id,
    )
    return SendMessageResponse(
        user_message=message_to_schema(outcome.user_message),
        assistant_message=message_to_schema(outcome.assistant_message),
    )


@router.post(
    "/{conversation_id}/cancel",
    response_model=CancelGenerationResponse,
    summary="Cancel the active generation in a conversation",
)
async def cancel_generation(
    conversation_id: ConversationId,
    request: Request,
    service: ServiceDep,
) -> CancelGenerationResponse:
    await service.get_conversation(conversation_id)
    engine: ConversationEngine = request.app.state.engine
    message_id = await engine.cancel(conversation_id)
    return CancelGenerationResponse(cancelled=message_id is not None, message_id=message_id)
