// Domain types mirroring chatbot/Backend/chat/models.py.

export type ContentBlock =
  | { type: "text"; text: string }
  | { type: "thinking"; text: string }
  | {
      type: "tool_use";
      id: string;
      name: string;
      input: Record<string, unknown>;
    }
  | {
      type: "tool_result";
      tool_use_id: string;
      content: unknown;
      is_error: boolean;
    }
  | {
      type: "image";
      mime_type: string;
      attachment_id?: number;
      url?: string;
      data_url?: string;
    }
  | {
      type: "file";
      mime_type: string;
      attachment_id?: number;
      url?: string;
    };

export type Role = "user" | "assistant" | "system" | "tool";

export interface MessageDTO {
  id: number;
  role: Role;
  content_blocks: ContentBlock[];
  finish_reason: string;
  token_usage: Record<string, unknown>;
  created_at: string;
}

export interface ConversationDTO {
  id: number;
  title: string;
  system_prompt: number | null;
  model_name: string;
  base_url: string;
  enabled_mcp_servers: number[];
  enabled_tools: number[];
  archived: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetailDTO extends ConversationDTO {
  messages: MessageDTO[];
}

export interface MCPServerDTO {
  id: number;
  name: string;
  transport: "stdio" | "sse" | "streamable_http";
  config: Record<string, unknown>;
  enabled: boolean;
  owner: number | null;
}

export interface ToolDTO {
  id: number;
  name: string;
  description: string;
  kind: "builtin" | "http" | "sql";
  config: Record<string, unknown>;
  enabled: boolean;
  owner: number | null;
}

export interface SystemPromptDTO {
  id: number;
  name: string;
  content: string;
  is_default: boolean;
  owner: number | null;
}

export interface AttachmentDTO {
  id: number;
  url: string;
  mime_type: string;
  size: number;
  created_at: string;
}

export interface UserMetaDTO {
  default_model: string;
  default_base_url: string;
  settings: Record<string, unknown>;
  secret_keys: string[];
}
