// Adapter that turns our WS protocol into the shape `assistant-ui` expects.
//
// `assistant-ui` exposes `useExternalStoreRuntime` which lets us own the
// message store. We give it:
//   - messages (read from TanStack Query, plus an in-flight assistant message)
//   - onNew  (called when the user submits in the composer)
//   - onCancel (Stop button)
//
// We translate our `ContentBlock[]` into assistant-ui's `ThreadMessage` shape
// on the way out, and translate composer input back into a `chat.send` frame
// on the way in.

import { useMemo, useRef, useState, useCallback, useEffect } from "react";
import {
  useExternalStoreRuntime,
  type AppendMessage,
  type ThreadMessageLike,
} from "@assistant-ui/react";

import type { ChatApi } from "../lib/api";
import type {
  ClientChatSend,
  ServerEvent,
} from "../lib/chat-events";
import type {
  AttachmentDTO,
  ContentBlock,
  ConversationDetailDTO,
  MessageDTO,
} from "../types";
import { useChatSocket } from "../hooks/useChatSocket";

export interface UseChatRuntimeOptions {
  api: ChatApi;
  wsUrl: string;
  conversationId: number | null;
  initialMessages?: MessageDTO[];
  onConversationCreated?: (id: number, title: string) => void;
}

interface UIMessage extends ThreadMessageLike {
  id: string;
  role: "user" | "assistant" | "system";
  content: ThreadMessageLike["content"];
  status?: ThreadMessageLike["status"];
  metadata?: { custom?: { thinking?: string; rawBlocks?: ContentBlock[] } };
}

const newId = () => `m_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;

function blocksToUiContent(blocks: ContentBlock[]): UIMessage["content"] {
  const parts: UIMessage["content"] = [];
  for (const b of blocks) {
    if (b.type === "text" && b.text) {
      parts.push({ type: "text", text: b.text });
    } else if (b.type === "thinking" && b.text) {
      parts.push({ type: "reasoning", text: b.text });
    } else if (b.type === "tool_use") {
      parts.push({
        type: "tool-call",
        toolCallId: b.id,
        toolName: b.name,
        args: b.input ?? {},
      });
    } else if (b.type === "tool_result") {
      // Attach the result onto the matching tool-call part.
      const idx = parts.findIndex(
        (p) => p.type === "tool-call" && p.toolCallId === b.tool_use_id,
      );
      if (idx >= 0) {
        const call = parts[idx] as Extract<
          UIMessage["content"][number],
          { type: "tool-call" }
        >;
        parts[idx] = {
          ...call,
          result: b.content,
        } as typeof call;
      }
    } else if (b.type === "image") {
      const url = b.url ?? b.data_url;
      if (url) parts.push({ type: "image", image: url });
    }
  }
  return parts;
}

function dtoToUi(m: MessageDTO): UIMessage {
  return {
    id: String(m.id),
    role: m.role === "tool" ? "assistant" : (m.role as UIMessage["role"]),
    content: blocksToUiContent(m.content_blocks ?? []),
    metadata: { custom: { rawBlocks: m.content_blocks } },
  };
}

async function appendToBlocks(
  api: ChatApi,
  msg: AppendMessage,
): Promise<ContentBlock[]> {
  const blocks: ContentBlock[] = [];
  for (const part of msg.content) {
    if (part.type === "text" && part.text) {
      blocks.push({ type: "text", text: part.text });
    } else if (part.type === "image") {
      // assistant-ui exposes an `image` URL string; we forward as-is.
      blocks.push({
        type: "image",
        mime_type: "image/*",
        url: typeof part.image === "string" ? part.image : "",
      });
    }
  }
  // Upload any File attachments hung off the AppendMessage.
  const attachments = (msg.attachments ?? []) as Array<{ file?: File }>;
  for (const att of attachments) {
    if (att.file) {
      const uploaded: AttachmentDTO = await api.uploadAttachment(att.file);
      const isImage = uploaded.mime_type.startsWith("image/");
      blocks.push({
        type: isImage ? "image" : "file",
        mime_type: uploaded.mime_type,
        attachment_id: uploaded.id,
        url: uploaded.url,
      });
    }
  }
  return blocks;
}

export function useChatRuntime({
  api,
  wsUrl,
  conversationId,
  initialMessages = [],
  onConversationCreated,
}: UseChatRuntimeOptions) {
  const [messages, setMessages] = useState<UIMessage[]>(() =>
    initialMessages.map(dtoToUi),
  );
  const [isRunning, setIsRunning] = useState(false);
  const inflightIdRef = useRef<string | null>(null);
  const inflightBlocksRef = useRef<ContentBlock[]>([]);
  const conversationIdRef = useRef<number | null>(conversationId);

  useEffect(() => {
    conversationIdRef.current = conversationId;
    setMessages(initialMessages.map(dtoToUi));
    // initialMessages reference changes on every render in some setups; we
    // intentionally key only on conversationId.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [conversationId]);

  const updateInflight = useCallback(() => {
    const id = inflightIdRef.current;
    if (!id) return;
    setMessages((prev) =>
      prev.map((m) =>
        m.id === id
          ? { ...m, content: blocksToUiContent(inflightBlocksRef.current) }
          : m,
      ),
    );
  }, []);

  const handleEvent = useCallback(
    (event: ServerEvent) => {
      switch (event.type) {
        case "conversation.created":
          conversationIdRef.current = event.data.conversation_id;
          onConversationCreated?.(event.data.conversation_id, event.data.title);
          break;

        case "message.start": {
          const id = String(event.data.message_id);
          inflightIdRef.current = id;
          inflightBlocksRef.current = [];
          setMessages((prev) => [
            ...prev,
            {
              id,
              role: "assistant",
              content: [],
              status: { type: "running" },
            },
          ]);
          setIsRunning(true);
          break;
        }

        case "message.delta": {
          const idx = event.data.block_index;
          const blocks = inflightBlocksRef.current;
          while (blocks.length <= idx) {
            blocks.push({ type: event.data.type, text: "" } as ContentBlock);
          }
          const target = blocks[idx];
          if (target.type === "text" || target.type === "thinking") {
            target.text += event.data.delta;
          }
          updateInflight();
          break;
        }

        case "tool_call.start": {
          const idx = event.data.block_index;
          const blocks = inflightBlocksRef.current;
          while (blocks.length <= idx) {
            blocks.push({ type: "text", text: "" });
          }
          blocks[idx] = {
            type: "tool_use",
            id: event.data.id,
            name: event.data.name,
            input: event.data.args,
          };
          updateInflight();
          break;
        }

        case "tool_call.end": {
          const idx = event.data.block_index;
          const blocks = inflightBlocksRef.current;
          while (blocks.length <= idx) {
            blocks.push({ type: "text", text: "" });
          }
          blocks[idx] = {
            type: "tool_result",
            tool_use_id: event.data.id,
            content: event.data.output,
            is_error: event.data.is_error,
          };
          updateInflight();
          break;
        }

        case "message.end": {
          const id = inflightIdRef.current;
          if (id) {
            setMessages((prev) =>
              prev.map((m) =>
                m.id === id
                  ? {
                      ...m,
                      status: { type: "complete", reason: "stop" },
                      metadata: {
                        custom: { rawBlocks: [...inflightBlocksRef.current] },
                      },
                    }
                  : m,
              ),
            );
          }
          inflightIdRef.current = null;
          inflightBlocksRef.current = [];
          setIsRunning(false);
          break;
        }

        case "error": {
          setIsRunning(false);
          // eslint-disable-next-line no-console
          console.error("chat error", event.data);
          break;
        }

        default:
          break;
      }
    },
    [onConversationCreated, updateInflight],
  );

  const { send } = useChatSocket({ url: wsUrl, onEvent: handleEvent });

  const onNew = useCallback(
    async (msg: AppendMessage) => {
      const blocks = await appendToBlocks(api, msg);
      setMessages((prev) => [
        ...prev,
        { id: newId(), role: "user", content: blocksToUiContent(blocks) },
      ]);
      const frame: ClientChatSend = {
        type: "chat.send",
        data: {
          conversation_id: conversationIdRef.current ?? undefined,
          content_blocks: blocks,
        },
      };
      send(frame);
      setIsRunning(true);
    },
    [api, send],
  );

  const onCancel = useCallback(() => {
    const id = conversationIdRef.current;
    if (id == null) return;
    send({ type: "chat.cancel", data: { conversation_id: id } });
  }, [send]);

  const runtime = useExternalStoreRuntime<UIMessage>({
    isRunning,
    messages,
    convertMessage: (m) => m,
    onNew,
    onCancel,
  });

  return useMemo(() => ({ runtime, isRunning }), [runtime, isRunning]);
}

export type { UIMessage };
export { dtoToUi };
