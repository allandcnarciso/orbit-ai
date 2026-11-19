"""Conversation application service.

Owns transaction boundaries and business rules; routes stay thin and never see
SQLAlchemy models.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from orbit.conversations.enums import ConversationStatus
from orbit.conversations.errors import (
    ConversationNotFound,
    InvalidSelection,
    InvalidStatusTransition,
    ModelNotAvailable,
)
from orbit.conversations.repository import ConversationRepository
from orbit.providers.errors import ProviderNotConfigured
from orbit.providers.registry import ProviderRegistry
from orbit.storage.models import Conversation, Message, utcnow


@dataclass(frozen=True, slots=True)
class ConversationUpdate:
    """Partial conversation update; ``fields`` lists attributes the client sent."""

    title: str | None = None
    provider: str | None = None
    model: str | None = None
    status: ConversationStatus | None = None
    fields: frozenset[str] = field(default_factory=frozenset)


class ConversationService:
    """Business operations for conversations and message history."""

    def __init__(self, session: AsyncSession, *, registry: ProviderRegistry | None = None) -> None:
        self._session = session
        self._repo = ConversationRepository(session)
        self._registry = registry

    async def create_conversation(
        self,
        *,
        title: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ) -> Conversation:
        self._validate_selection(provider, model)
        await self._ensure_model_available(provider, model)
        conversation = await self._repo.create_conversation(
            title=(title or "New conversation"),
            provider=provider,
            model=model,
        )
        await self._session.commit()
        return conversation

    async def list_conversations(
        self,
        *,
        limit: int = 50,
        offset: int = 0,
        status: ConversationStatus | None = None,
    ) -> tuple[list[Conversation], int]:
        return await self._repo.list_conversations(limit=limit, offset=offset, status=status)

    async def get_conversation(self, conversation_id: str) -> Conversation:
        conversation = await self._repo.get_conversation(conversation_id)
        if conversation is None:
            raise ConversationNotFound("Conversation not found.", conversation_id=conversation_id)
        return conversation

    async def update_conversation(
        self, conversation_id: str, update: ConversationUpdate
    ) -> Conversation:
        conversation = await self.get_conversation(conversation_id)
        changed = False

        proposed_title = conversation.title
        if "title" in update.fields:
            title = (update.title or "").strip()
            if not title:
                raise InvalidSelection("Title must not be empty.", conversation_id=conversation_id)
            proposed_title = title[:200]
            changed = True

        proposed_provider = conversation.provider
        proposed_model = conversation.model
        if "provider" in update.fields:
            proposed_provider = update.provider.strip() if update.provider else None
            if proposed_provider is None:
                proposed_model = None
            changed = True
        if "model" in update.fields:
            proposed_model = update.model.strip() if update.model else None
            changed = True

        if "provider" in update.fields or "model" in update.fields:
            self._validate_selection(
                proposed_provider, proposed_model, conversation_id=conversation_id
            )
            await self._ensure_model_available(
                proposed_provider, proposed_model, conversation_id=conversation_id
            )

        if "status" in update.fields and update.status is not None:
            changed = self._apply_status(conversation, update.status) or changed

        if changed:
            conversation.title = proposed_title
            if "provider" in update.fields or "model" in update.fields:
                conversation.provider = proposed_provider
                conversation.model = proposed_model
            conversation.updated_at = utcnow()
            await self._session.commit()
        return conversation

    async def delete_conversation(self, conversation_id: str) -> None:
        deleted = await self._repo.delete_conversation(conversation_id)
        if not deleted:
            raise ConversationNotFound("Conversation not found.", conversation_id=conversation_id)
        await self._session.commit()

    async def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before_sequence: int | None = None,
    ) -> tuple[list[Message], bool]:
        await self.get_conversation(conversation_id)
        return await self._repo.list_messages(
            conversation_id, limit=limit, before_sequence=before_sequence
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _validate_selection(
        self,
        provider: str | None,
        model: str | None,
        *,
        conversation_id: str | None = None,
    ) -> None:
        if model is not None and not model.strip():
            raise InvalidSelection("Model must not be empty.", conversation_id=conversation_id)
        if model is not None and provider is None:
            raise InvalidSelection(
                "Selecting a model requires a provider.", conversation_id=conversation_id
            )
        if provider is not None:
            if not provider.strip():
                raise InvalidSelection(
                    "Provider must not be empty.", conversation_id=conversation_id
                )
            if self._registry is not None:
                selected = self._registry.get(provider)
                if selected is None:
                    raise InvalidSelection(
                        f"Unknown provider: {provider}", conversation_id=conversation_id
                    )
                if not selected.configured:
                    raise ProviderNotConfigured(
                        f"Provider {provider} is not configured.", provider=provider
                    )

    async def _ensure_model_available(
        self,
        provider: str | None,
        model: str | None,
        *,
        conversation_id: str | None = None,
    ) -> None:
        """Validate a concrete model against the provider's shared catalog.

        Provider discovery failures propagate unchanged (timeout/unavailable),
        so callers never persist a selection when availability is unknown.
        """
        if provider is None or model is None or self._registry is None:
            return
        selected = self._registry.get(provider)
        if selected is None:
            raise InvalidSelection(f"Unknown provider: {provider}", conversation_id=conversation_id)
        models = await self._registry.discover_models(selected)
        if not any(item.id == model for item in models):
            raise ModelNotAvailable(
                f"Model {model} is not available for provider {provider}.",
                conversation_id=conversation_id,
            )

    def _apply_status(self, conversation: Conversation, status: ConversationStatus) -> bool:
        current = ConversationStatus(conversation.status)
        if current is status:
            return False
        if current is ConversationStatus.ARCHIVED:
            raise InvalidStatusTransition(
                "Archived conversations cannot be reactivated.",
                conversation_id=conversation.id,
            )
        conversation.status = status.value
        return True
