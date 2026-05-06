"""Translate ``graph.astream_events`` into the WebSocket protocol.

Yields nothing; calls ``send(event)`` for each WS frame to push to the client.
At the end, returns the assembled ``content_blocks`` for the assistant turn so
the consumer can persist exactly one Message row.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from langchain_core.messages import AIMessageChunk


SendFn = Callable[[dict[str, Any]], Awaitable[None]]


def _to_text(content: Any) -> str:
    """LangChain AIMessageChunk.content can be str OR list[block]. Coerce to str."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict) and part.get("type") == "text":
                out.append(part.get("text", ""))
        return "".join(out)
    return ""


def _reasoning_text(chunk: AIMessageChunk) -> str:
    extra = getattr(chunk, "additional_kwargs", {}) or {}
    # vLLM / DeepSeek-R1 / Qwen reasoning models surface this field.
    val = extra.get("reasoning_content")
    if isinstance(val, str):
        return val
    return ""


class _Accumulator:
    """Builds the final content_blocks list as the model streams."""

    def __init__(self) -> None:
        self.blocks: list[dict[str, Any]] = []
        self._text_idx: int | None = None
        self._think_idx: int | None = None
        self._tool_idx: dict[str, int] = {}  # tool_use_id -> block index

    def push_text(self, delta: str) -> int:
        if self._text_idx is None:
            self.blocks.append({"type": "text", "text": ""})
            self._text_idx = len(self.blocks) - 1
        self.blocks[self._text_idx]["text"] += delta
        return self._text_idx

    def push_thinking(self, delta: str) -> int:
        if self._think_idx is None:
            self.blocks.append({"type": "thinking", "text": ""})
            self._think_idx = len(self.blocks) - 1
        self.blocks[self._think_idx]["text"] += delta
        return self._think_idx

    def open_tool_use(self, tool_id: str, name: str, args: Any) -> int:
        block = {"type": "tool_use", "id": tool_id, "name": name, "input": args or {}}
        self.blocks.append(block)
        idx = len(self.blocks) - 1
        self._tool_idx[tool_id] = idx
        # Reset text/thinking accumulators so subsequent text starts a fresh block.
        self._text_idx = None
        self._think_idx = None
        return idx

    def close_tool_use(self, tool_id: str, output: Any, is_error: bool) -> int:
        block = {
            "type": "tool_result",
            "tool_use_id": tool_id,
            "content": output,
            "is_error": is_error,
        }
        self.blocks.append(block)
        return len(self.blocks) - 1


def _coerce_json(v: Any) -> Any:
    if isinstance(v, str):
        try:
            return json.loads(v)
        except (ValueError, TypeError):
            return v
    return v


async def stream_to_ws(
    graph: Any,
    inputs: dict[str, Any],
    send: SendFn,
    *,
    message_id: int | str,
) -> tuple[list[dict[str, Any]], str, dict[str, Any]]:
    """Drive ``graph.astream_events`` and forward as WS frames.

    Returns ``(content_blocks, finish_reason, usage)`` for persistence.
    """

    acc = _Accumulator()
    finish_reason = ""
    usage: dict[str, Any] = {}

    await send({"type": "message.start", "data": {"message_id": message_id, "role": "assistant"}})

    async for event in graph.astream_events(inputs, version="v2"):
        kind = event.get("event")
        data = event.get("data") or {}

        if kind == "on_chat_model_stream":
            chunk = data.get("chunk")
            if not isinstance(chunk, AIMessageChunk):
                continue

            think = _reasoning_text(chunk)
            if think:
                idx = acc.push_thinking(think)
                await send({
                    "type": "message.delta",
                    "data": {"block_index": idx, "type": "thinking", "delta": think},
                })

            text = _to_text(chunk.content)
            if text:
                idx = acc.push_text(text)
                await send({
                    "type": "message.delta",
                    "data": {"block_index": idx, "type": "text", "delta": text},
                })

        elif kind == "on_tool_start":
            name = event.get("name", "")
            run_id = str(event.get("run_id", ""))
            args = _coerce_json(data.get("input"))
            idx = acc.open_tool_use(run_id, name, args)
            await send({
                "type": "tool_call.start",
                "data": {"block_index": idx, "id": run_id, "name": name, "args": args},
            })

        elif kind == "on_tool_end":
            run_id = str(event.get("run_id", ""))
            output = data.get("output")
            output_text = output if isinstance(output, str) else _coerce_json(output)
            is_error = isinstance(output, BaseException)
            idx = acc.close_tool_use(run_id, output_text, is_error)
            await send({
                "type": "tool_call.end",
                "data": {
                    "block_index": idx,
                    "id": run_id,
                    "output": output_text,
                    "is_error": is_error,
                },
            })

        elif kind == "on_chat_model_end":
            output = data.get("output")
            meta = getattr(output, "response_metadata", None) or {}
            if meta.get("finish_reason"):
                finish_reason = meta["finish_reason"]
            uobj = getattr(output, "usage_metadata", None)
            if uobj:
                usage = dict(uobj)

    await send({
        "type": "message.end",
        "data": {
            "message_id": message_id,
            "finish_reason": finish_reason,
            "usage": usage,
        },
    })
    return acc.blocks, finish_reason, usage
