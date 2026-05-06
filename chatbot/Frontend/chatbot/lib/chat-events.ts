// Wire protocol mirrored in chatbot/Backend/chat/consumers.py.
// Frame shape on both sides: { type, data }.

import type { ContentBlock } from "../types";

// --- Client -> server ---------------------------------------------------- //

export type ClientChatSend = {
  type: "chat.send";
  data: {
    conversation_id?: number;
    content_blocks: ContentBlock[];
    model?: string;
    base_url?: string;
  };
};

export type ClientChatCancel = {
  type: "chat.cancel";
  data: { conversation_id: number };
};

export type ClientEvent = ClientChatSend | ClientChatCancel;

// --- Server -> client ---------------------------------------------------- //

export type ServerConversationCreated = {
  type: "conversation.created";
  data: { conversation_id: number; title: string };
};

export type ServerMessageStart = {
  type: "message.start";
  data: { message_id: number; role: "assistant" };
};

export type ServerMessageSaved = {
  type: "message.saved";
  data: { message_id: number; role: string; content_blocks: ContentBlock[] };
};

export type ServerMessageDelta = {
  type: "message.delta";
  data: {
    block_index: number;
    type: "text" | "thinking";
    delta: string;
  };
};

export type ServerToolCallStart = {
  type: "tool_call.start";
  data: {
    block_index: number;
    id: string;
    name: string;
    args: Record<string, unknown>;
  };
};

export type ServerToolCallEnd = {
  type: "tool_call.end";
  data: {
    block_index: number;
    id: string;
    output: unknown;
    is_error: boolean;
  };
};

export type ServerMessageEnd = {
  type: "message.end";
  data: {
    message_id: number;
    finish_reason: string;
    usage: Record<string, unknown>;
  };
};

export type ServerError = {
  type: "error";
  data: { message: string; recoverable?: boolean };
};

export type ServerEvent =
  | ServerConversationCreated
  | ServerMessageStart
  | ServerMessageSaved
  | ServerMessageDelta
  | ServerToolCallStart
  | ServerToolCallEnd
  | ServerMessageEnd
  | ServerError;
