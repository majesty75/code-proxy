"""WebSocket consumer for /ws/chat/.

Wire shape (client <-> server) is mirrored in
``Frontend/chatbot/lib/chat-events.ts``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.contrib.auth.models import AnonymousUser
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from .agent import build_agent, stream_to_ws
from .models import Attachment, Conversation, Message, UserMeta


# -- helpers -------------------------------------------------------------- #

def _to_lc_messages(rows: list[Message], system_prompt: str) -> list[Any]:
    """Convert DB Message rows to LangChain message objects."""
    out: list[Any] = []
    if system_prompt:
        out.append(SystemMessage(content=system_prompt))
    for row in rows:
        text_parts = [
            b.get("text", "")
            for b in (row.content_blocks or [])
            if b.get("type") == "text"
        ]
        text = "".join(text_parts)
        if row.role == Message.ROLE_USER:
            out.append(HumanMessage(content=_user_content(row.content_blocks)))
        elif row.role == Message.ROLE_ASSISTANT:
            out.append(AIMessage(content=text))
        elif row.role == Message.ROLE_TOOL:
            tool_use_id = next(
                (
                    b.get("tool_use_id", "")
                    for b in (row.content_blocks or [])
                    if b.get("type") == "tool_result"
                ),
                "",
            )
            out.append(ToolMessage(content=text, tool_call_id=tool_use_id))
    return out


def _user_content(blocks: list[dict[str, Any]]) -> Any:
    """Build a multi-modal content list for a user turn (OpenAI-compatible)."""
    parts: list[dict[str, Any]] = []
    for b in blocks or []:
        kind = b.get("type")
        if kind == "text":
            parts.append({"type": "text", "text": b.get("text", "")})
        elif kind == "image":
            url = b.get("data_url") or b.get("url")
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})
        elif kind == "file":
            # Most OpenAI-compatible servers don't accept arbitrary files; degrade
            # to a text reference so the model at least sees a label.
            parts.append(
                {"type": "text", "text": f"[file attachment: {b.get('mime_type','file')}]"}
            )
    if not parts:
        parts.append({"type": "text", "text": ""})
    if len(parts) == 1 and parts[0]["type"] == "text":
        return parts[0]["text"]
    return parts


@database_sync_to_async
def _hydrate_attachments(blocks: list[dict[str, Any]], user_id: int) -> list[dict[str, Any]]:
    """Replace ``attachment_id`` references with absolute file URLs."""
    ids = [
        b["attachment_id"]
        for b in blocks
        if isinstance(b, dict) and b.get("attachment_id")
    ]
    if not ids:
        return blocks
    by_id = {
        a.id: a
        for a in Attachment.objects.filter(id__in=ids, user_id=user_id)
    }
    out: list[dict[str, Any]] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("attachment_id") and b["attachment_id"] in by_id:
            attachment = by_id[b["attachment_id"]]
            new_block = dict(b)
            new_block["url"] = attachment.file.url
            out.append(new_block)
        else:
            out.append(b)
    return out


# -- consumer ------------------------------------------------------------- #

class ChatConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self) -> None:
        user = self.scope.get("user")
        if user is None or isinstance(user, AnonymousUser) or not user.is_authenticated:
            await self.close(code=4401)
            return
        self.user = user
        self._cancel_event: dict[int, asyncio.Event] = {}
        await self.accept()

    async def disconnect(self, code: int) -> None:
        for evt in self._cancel_event.values():
            evt.set()

    async def receive_json(self, content: dict[str, Any], **kwargs: Any) -> None:
        kind = content.get("type")
        data = content.get("data") or {}
        try:
            if kind == "chat.send":
                await self._handle_send(data)
            elif kind == "chat.cancel":
                evt = self._cancel_event.get(int(data.get("conversation_id", 0)))
                if evt:
                    evt.set()
            else:
                await self.send_json({"type": "error", "data": {"message": f"unknown type: {kind}"}})
        except Exception as exc:  # noqa: BLE001
            await self.send_json({
                "type": "error",
                "data": {"message": str(exc), "recoverable": True},
            })

    # -- core turn ---------------------------------------------------- #

    async def _handle_send(self, data: dict[str, Any]) -> None:
        conversation_id = data.get("conversation_id")
        content_blocks = data.get("content_blocks") or []

        conversation, created = await self._get_or_create_conversation(
            conversation_id=conversation_id,
            content_blocks=content_blocks,
            model=data.get("model"),
            base_url=data.get("base_url"),
        )
        if created:
            await self.send_json({
                "type": "conversation.created",
                "data": {"conversation_id": conversation.id, "title": conversation.title},
            })

        hydrated_blocks = await _hydrate_attachments(content_blocks, self.user.id)
        user_message = await self._save_message(
            conversation, role=Message.ROLE_USER, blocks=hydrated_blocks
        )
        await self.send_json({
            "type": "message.saved",
            "data": {
                "message_id": user_message.id,
                "role": Message.ROLE_USER,
                "content_blocks": hydrated_blocks,
            },
        })

        meta = await self._get_meta()
        bundle = await build_agent(conversation, meta)
        try:
            history = await self._load_history(conversation)
            inputs = {"messages": _to_lc_messages(history, bundle.system_prompt)}

            placeholder = await self._save_message(
                conversation, role=Message.ROLE_ASSISTANT, blocks=[]
            )

            cancel = asyncio.Event()
            self._cancel_event[conversation.id] = cancel

            blocks, finish, usage = await self._race_cancel(
                stream_to_ws(
                    bundle.graph,
                    inputs,
                    self.send_json,
                    message_id=placeholder.id,
                ),
                cancel,
            )
            await self._finalize_message(placeholder, blocks, finish, usage)
        finally:
            await bundle.aclose()
            self._cancel_event.pop(conversation.id, None)

    async def _race_cancel(self, coro, cancel_event: asyncio.Event):
        task = asyncio.ensure_future(coro)
        cancel_task = asyncio.ensure_future(cancel_event.wait())
        done, pending = await asyncio.wait(
            {task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancel_task in done and task not in done:
            task.cancel()
            return [], "cancelled", {}
        cancel_task.cancel()
        return await task

    # -- persistence -------------------------------------------------- #

    @database_sync_to_async
    def _get_or_create_conversation(
        self,
        *,
        conversation_id: int | None,
        content_blocks: list[dict[str, Any]],
        model: str | None,
        base_url: str | None,
    ) -> tuple[Conversation, bool]:
        if conversation_id:
            conv = Conversation.objects.get(id=conversation_id, user=self.user)
            return conv, False
        title = ""
        for b in content_blocks:
            if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
                title = b["text"][:60]
                break
        conv = Conversation.objects.create(
            user=self.user,
            title=title,
            model_name=model or "",
            base_url=base_url or "",
        )
        return conv, True

    @database_sync_to_async
    def _save_message(
        self, conversation: Conversation, *, role: str, blocks: list[dict[str, Any]]
    ) -> Message:
        return Message.objects.create(
            conversation=conversation, role=role, content_blocks=blocks
        )

    @database_sync_to_async
    def _finalize_message(
        self,
        message: Message,
        blocks: list[dict[str, Any]],
        finish_reason: str,
        usage: dict[str, Any],
    ) -> None:
        message.content_blocks = blocks
        message.finish_reason = finish_reason
        message.token_usage = usage or {}
        message.save(update_fields=("content_blocks", "finish_reason", "token_usage"))
        Conversation.objects.filter(id=message.conversation_id).update()  # bump updated_at

    @database_sync_to_async
    def _load_history(self, conversation: Conversation) -> list[Message]:
        return list(conversation.messages.all().order_by("created_at", "id"))

    @database_sync_to_async
    def _get_meta(self) -> UserMeta:
        meta, _ = UserMeta.objects.get_or_create(user=self.user)
        return meta
