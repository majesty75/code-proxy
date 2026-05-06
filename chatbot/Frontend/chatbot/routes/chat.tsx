// TanStack Router file-based route: /chat
// Drop into your routes tree (e.g. src/routes/chat.tsx). The route renders the
// sidebar plus a placeholder when no conversation is selected.

import { Outlet, createFileRoute } from "@tanstack/react-router";

import { ChatApi } from "../lib/api";
import { ConversationSidebar } from "../components/ConversationSidebar";

// In a real app, build `api` from your existing auth context. Exported so
// child routes can reuse it via the route loader.
export const chatApi = new ChatApi({ baseUrl: "/api/chat" });

export const Route = createFileRoute("/chat")({
  component: ChatLayout,
});

function ChatLayout() {
  return (
    <div className="flex h-[calc(100vh-3.5rem)]">
      <ConversationSidebar api={chatApi} activeId={null} />
      <main className="flex-1">
        <Outlet />
      </main>
    </div>
  );
}
