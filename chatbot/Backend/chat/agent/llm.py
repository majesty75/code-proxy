"""ChatOpenAI factory for vLLM / LM Studio / llama.cpp / TGI / any OpenAI-compatible
endpoint. Reads model + base_url + api_key from the conversation, then UserMeta,
then Django settings, in that order.
"""

from __future__ import annotations

from django.conf import settings
from langchain_openai import ChatOpenAI

from .. import crypto
from ..models import Conversation, UserMeta


_API_KEY_FIELD = "openai_api_key"


def _resolve_api_key(meta: UserMeta | None) -> str:
    if meta is not None:
        encrypted = (meta.encrypted_secrets or {}).get(_API_KEY_FIELD)
        if encrypted:
            decrypted = crypto.decrypt(encrypted)
            if decrypted:
                return decrypted
    # vLLM with no auth still requires *something*; "EMPTY" is the convention.
    return getattr(settings, "CHAT_DEFAULT_API_KEY", "EMPTY")


def _resolve(value: str, *fallbacks: str) -> str:
    for v in (value, *fallbacks):
        if v:
            return v
    return ""


def get_llm(conversation: Conversation, meta: UserMeta | None = None) -> ChatOpenAI:
    base_url = _resolve(
        conversation.base_url,
        meta.default_base_url if meta else "",
        getattr(settings, "CHAT_DEFAULT_BASE_URL", ""),
    )
    model = _resolve(
        conversation.model_name,
        meta.default_model if meta else "",
        getattr(settings, "CHAT_DEFAULT_MODEL", ""),
    )
    if not base_url:
        raise RuntimeError(
            "No LLM base_url configured. Set CHAT_DEFAULT_BASE_URL or "
            "UserMeta.default_base_url or Conversation.base_url."
        )
    if not model:
        raise RuntimeError(
            "No model configured. Set CHAT_DEFAULT_MODEL or UserMeta.default_model "
            "or Conversation.model_name."
        )

    extra_body = getattr(settings, "CHAT_LLM_EXTRA_BODY", None) or {}
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=_resolve_api_key(meta),
        streaming=True,
        # vLLM exposes reasoning content via OpenAI's `reasoning_content` field
        # when the model emits it; LangChain forwards anything unknown via
        # `additional_kwargs` on AIMessageChunk.
        extra_body=extra_body,
    )
