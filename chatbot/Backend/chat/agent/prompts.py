"""Resolve the active system prompt for a conversation."""

from __future__ import annotations

from ..models import Conversation, SystemPrompt


_FALLBACK = (
    "You are a helpful assistant. If you can think step-by-step, do so before "
    "responding. Use tools when they would produce a more accurate answer."
)


def resolve_system_prompt(conversation: Conversation) -> str:
    if conversation.system_prompt_id:
        return conversation.system_prompt.content

    default = (
        SystemPrompt.objects.filter(is_default=True, owner__isnull=True)
        .order_by("id")
        .first()
    )
    if default:
        return default.content
    return _FALLBACK
