// TanStack Router file-based route: /chat/$conversationId

import { createFileRoute, useNavigate } from "@tanstack/react-router";

import { ChatThread } from "../components/ChatThread";
import { SettingsDialog } from "../components/SettingsDialog";
import { useConversation } from "../hooks/useConversations";
import { chatApi } from "./chat";

export const Route = createFileRoute("/chat/$conversationId")({
  component: ChatRoute,
});

function ChatRoute() {
  const { conversationId } = Route.useParams();
  const navigate = useNavigate();
  const idNum = conversationId === "new" ? null : Number(conversationId);
  const { data: conversation } = useConversation(chatApi, idNum);

  // Build ws URL from current origin if a relative-ish API base was used.
  const wsUrl = (() => {
    if (typeof window === "undefined") return "";
    const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${proto}//${window.location.host}/ws/chat/`;
  })();

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b px-4 py-2">
        <div className="truncate text-sm font-medium">
          {conversation?.title ?? "New conversation"}
        </div>
        <SettingsDialog api={chatApi} conversation={conversation ?? null} />
      </header>
      <div className="flex-1 overflow-hidden">
        <ChatThread
          api={chatApi}
          wsUrl={wsUrl}
          conversationId={idNum}
          initialMessages={conversation?.messages}
          onConversationCreated={(id) => {
            navigate({
              to: "/chat/$conversationId",
              params: { conversationId: String(id) },
            });
          }}
        />
      </div>
    </div>
  );
}
