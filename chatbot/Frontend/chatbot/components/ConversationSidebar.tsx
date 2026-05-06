import { Link } from "@tanstack/react-router";

import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";

import {
  useConversations,
  useCreateConversation,
  useDeleteConversation,
} from "../hooks/useConversations";
import type { ChatApi } from "../lib/api";

interface ConversationSidebarProps {
  api: ChatApi;
  activeId: number | null;
}

export function ConversationSidebar({
  api,
  activeId,
}: ConversationSidebarProps) {
  const { data = [], isLoading } = useConversations(api);
  const create = useCreateConversation(api);
  const remove = useDeleteConversation(api);

  return (
    <aside className="flex h-full w-64 flex-col border-r bg-background">
      <div className="flex items-center justify-between border-b px-3 py-2">
        <span className="text-sm font-semibold">Conversations</span>
        <Button
          size="sm"
          variant="outline"
          onClick={() =>
            create.mutate({ title: "New conversation" })
          }
        >
          New
        </Button>
      </div>
      <ScrollArea className="flex-1">
        {isLoading ? (
          <div className="px-3 py-2 text-xs text-muted-foreground">
            Loading…
          </div>
        ) : (
          <ul className="space-y-1 p-2">
            {data.map((c) => (
              <li
                key={c.id}
                className={`group flex items-center justify-between rounded px-2 py-1 text-sm hover:bg-muted ${
                  c.id === activeId ? "bg-muted" : ""
                }`}
              >
                <Link
                  to="/chat/$conversationId"
                  params={{ conversationId: String(c.id) }}
                  className="flex-1 truncate"
                >
                  {c.title || `Conversation #${c.id}`}
                </Link>
                <Button
                  size="sm"
                  variant="ghost"
                  className="hidden h-6 px-2 group-hover:inline-flex"
                  onClick={() => remove.mutate(c.id)}
                >
                  ×
                </Button>
              </li>
            ))}
          </ul>
        )}
      </ScrollArea>
    </aside>
  );
}
