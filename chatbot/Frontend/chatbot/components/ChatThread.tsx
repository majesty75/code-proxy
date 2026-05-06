import {
  AssistantRuntimeProvider,
  ComposerPrimitive,
  MessagePrimitive,
  ThreadPrimitive,
  useMessage,
} from "@assistant-ui/react";

import { Button } from "@/components/ui/button";

import { useChatRuntime } from "../runtime/websocketRuntime";
import type { ChatApi } from "../lib/api";
import type { ContentBlock, MessageDTO } from "../types";
import { ThinkingBlock } from "./ThinkingBlock";
import { ToolCallBlock } from "./ToolCallBlock";

interface ChatThreadProps {
  api: ChatApi;
  wsUrl: string;
  conversationId: number | null;
  initialMessages?: MessageDTO[];
  onConversationCreated?: (id: number, title: string) => void;
}

/** Renders the assistant-ui Thread, wired to our websocket runtime. */
export function ChatThread({
  api,
  wsUrl,
  conversationId,
  initialMessages,
  onConversationCreated,
}: ChatThreadProps) {
  const { runtime } = useChatRuntime({
    api,
    wsUrl,
    conversationId,
    initialMessages,
    onConversationCreated,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ThreadPrimitive.Root className="flex h-full flex-col">
        <ThreadPrimitive.Viewport className="flex-1 overflow-y-auto px-4 py-6">
          <ThreadPrimitive.Messages
            components={{
              UserMessage,
              AssistantMessage,
            }}
          />
        </ThreadPrimitive.Viewport>

        <ComposerPrimitive.Root className="flex items-end gap-2 border-t bg-background px-4 py-3">
          <ComposerPrimitive.Input
            className="flex-1 resize-none rounded-md border px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-1"
            placeholder="Ask anything…"
            rows={2}
          />
          <ComposerPrimitive.Send asChild>
            <Button size="sm">Send</Button>
          </ComposerPrimitive.Send>
        </ComposerPrimitive.Root>
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  );
}

function UserMessage() {
  return (
    <MessagePrimitive.Root className="my-3 flex justify-end">
      <div className="max-w-[80%] rounded-md bg-primary px-3 py-2 text-sm text-primary-foreground">
        <MessagePrimitive.Content />
      </div>
    </MessagePrimitive.Root>
  );
}

function AssistantMessage() {
  const message = useMessage();
  const blocks =
    (message.metadata?.custom as { rawBlocks?: ContentBlock[] } | undefined)
      ?.rawBlocks ?? [];

  return (
    <MessagePrimitive.Root className="my-3 flex justify-start">
      <div className="max-w-[80%] rounded-md bg-muted px-3 py-2 text-sm">
        <RenderBlocks blocks={blocks} />
      </div>
    </MessagePrimitive.Root>
  );
}

function RenderBlocks({ blocks }: { blocks: ContentBlock[] }) {
  // Pair tool_use and tool_result for a single visual card.
  const resultsById = new Map<string, ContentBlock>();
  for (const b of blocks) {
    if (b.type === "tool_result") resultsById.set(b.tool_use_id, b);
  }
  return (
    <>
      {blocks.map((b, i) => {
        if (b.type === "text") {
          return (
            <p key={i} className="whitespace-pre-wrap leading-relaxed">
              {b.text}
            </p>
          );
        }
        if (b.type === "thinking") {
          return <ThinkingBlock key={i} text={b.text} />;
        }
        if (b.type === "tool_use") {
          const result = resultsById.get(b.id);
          const isResult =
            result && result.type === "tool_result" ? result : undefined;
          return (
            <ToolCallBlock
              key={i}
              name={b.name}
              args={b.input}
              result={isResult?.content}
              isError={isResult?.is_error}
              status={isResult ? "complete" : "running"}
            />
          );
        }
        if (b.type === "tool_result") {
          // Already rendered alongside its tool_use.
          return null;
        }
        if (b.type === "image" && (b.url || b.data_url)) {
          return (
            <img
              key={i}
              src={b.url ?? b.data_url}
              alt=""
              className="my-2 max-h-72 rounded"
            />
          );
        }
        return null;
      })}
    </>
  );
}
