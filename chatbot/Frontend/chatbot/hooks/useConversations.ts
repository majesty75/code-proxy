import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { ChatApi } from "../lib/api";
import type { ConversationDTO, MessageDTO } from "../types";

const QK = {
  all: ["chat", "conversations"] as const,
  one: (id: number) => ["chat", "conversation", id] as const,
  messages: (id: number) => ["chat", "conversation", id, "messages"] as const,
  meta: ["chat", "me", "meta"] as const,
  mcpServers: ["chat", "mcp-servers"] as const,
  tools: ["chat", "tools"] as const,
  systemPrompts: ["chat", "system-prompts"] as const,
};

export function useConversations(api: ChatApi) {
  return useQuery({
    queryKey: QK.all,
    queryFn: () => api.listConversations(),
  });
}

export function useConversation(api: ChatApi, id: number | null) {
  return useQuery({
    queryKey: id ? QK.one(id) : ["chat", "conversation", "none"],
    queryFn: () => api.getConversation(id as number),
    enabled: id != null,
  });
}

export function useMessages(api: ChatApi, id: number | null) {
  return useQuery({
    queryKey: id ? QK.messages(id) : ["chat", "messages", "none"],
    queryFn: () => api.listMessages(id as number),
    enabled: id != null,
  });
}

export function useCreateConversation(api: ChatApi) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: Partial<ConversationDTO>) => api.createConversation(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.all }),
  });
}

export function useUpdateConversation(api: ChatApi) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: number; body: Partial<ConversationDTO> }) =>
      api.updateConversation(id, body),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: QK.all });
      qc.invalidateQueries({ queryKey: QK.one(vars.id) });
    },
  });
}

export function useDeleteConversation(api: ChatApi) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: number) => api.deleteConversation(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: QK.all }),
  });
}

export function useUserMeta(api: ChatApi) {
  return useQuery({ queryKey: QK.meta, queryFn: () => api.getMeta() });
}

export function useMcpServers(api: ChatApi) {
  return useQuery({ queryKey: QK.mcpServers, queryFn: () => api.listMcpServers() });
}

export function useTools(api: ChatApi) {
  return useQuery({ queryKey: QK.tools, queryFn: () => api.listTools() });
}

export function useSystemPrompts(api: ChatApi) {
  return useQuery({
    queryKey: QK.systemPrompts,
    queryFn: () => api.listSystemPrompts(),
  });
}

export const chatQueryKeys = QK;
export type { MessageDTO };
