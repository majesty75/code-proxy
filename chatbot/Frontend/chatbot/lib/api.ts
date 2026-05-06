// REST client for /api/chat/*. The base URL is configurable so it works
// whether the frontend is co-served (relative `/api/chat/`) or split across
// origins (absolute URL, with credentials).

import type {
  AttachmentDTO,
  ConversationDTO,
  ConversationDetailDTO,
  MCPServerDTO,
  MessageDTO,
  SystemPromptDTO,
  ToolDTO,
  UserMetaDTO,
} from "../types";

export interface ChatApiConfig {
  baseUrl: string; // e.g. "/api/chat" or "https://api.example.com/api/chat"
  fetchImpl?: typeof fetch;
  getAuthHeaders?: () => Record<string, string> | Promise<Record<string, string>>;
}

export class ChatApi {
  constructor(private cfg: ChatApiConfig) {}

  private async request<T>(
    path: string,
    init: RequestInit = {},
  ): Promise<T> {
    const f = this.cfg.fetchImpl ?? fetch;
    const auth = (await this.cfg.getAuthHeaders?.()) ?? {};
    const headers: Record<string, string> = {
      Accept: "application/json",
      ...auth,
      ...((init.headers as Record<string, string>) ?? {}),
    };
    if (init.body && !(init.body instanceof FormData)) {
      headers["Content-Type"] = headers["Content-Type"] ?? "application/json";
    }
    const res = await f(`${this.cfg.baseUrl}${path}`, {
      credentials: "include",
      ...init,
      headers,
    });
    if (!res.ok) {
      const text = await res.text().catch(() => "");
      throw new Error(`${res.status} ${res.statusText} ${text}`);
    }
    if (res.status === 204) return undefined as unknown as T;
    return (await res.json()) as T;
  }

  listConversations() {
    return this.request<ConversationDTO[]>("/conversations/");
  }

  getConversation(id: number) {
    return this.request<ConversationDetailDTO>(`/conversations/${id}/`);
  }

  createConversation(body: Partial<ConversationDTO>) {
    return this.request<ConversationDTO>("/conversations/", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  updateConversation(id: number, body: Partial<ConversationDTO>) {
    return this.request<ConversationDTO>(`/conversations/${id}/`, {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  deleteConversation(id: number) {
    return this.request<void>(`/conversations/${id}/`, { method: "DELETE" });
  }

  listMessages(conversationId: number) {
    return this.request<MessageDTO[]>(`/conversations/${conversationId}/messages/`);
  }

  listMcpServers() {
    return this.request<MCPServerDTO[]>("/mcp-servers/");
  }

  listTools() {
    return this.request<ToolDTO[]>("/tools/");
  }

  listSystemPrompts() {
    return this.request<SystemPromptDTO[]>("/system-prompts/");
  }

  getMeta() {
    return this.request<UserMetaDTO>("/me/meta/");
  }

  patchMeta(body: {
    default_model?: string;
    default_base_url?: string;
    settings?: Record<string, unknown>;
    set_secrets?: Record<string, string>;
    delete_secrets?: string[];
  }) {
    return this.request<UserMetaDTO>("/me/meta/", {
      method: "PATCH",
      body: JSON.stringify(body),
    });
  }

  uploadAttachment(file: File) {
    const fd = new FormData();
    fd.append("file", file);
    return this.request<AttachmentDTO>("/attachments/", {
      method: "POST",
      body: fd,
    });
  }
}
