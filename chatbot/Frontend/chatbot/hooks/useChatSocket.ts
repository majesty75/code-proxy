import { useCallback, useEffect, useRef, useState } from "react";

import type { ClientEvent, ServerEvent } from "../lib/chat-events";

export interface UseChatSocketOptions {
  url: string; // e.g. "ws://localhost:8000/ws/chat/"
  onEvent: (event: ServerEvent) => void;
  onError?: (err: Event) => void;
  enabled?: boolean;
  retryDelayMs?: number;
}

export interface UseChatSocketResult {
  send: (event: ClientEvent) => void;
  ready: boolean;
  close: () => void;
}

/** Lightweight WS hook with auto-reconnect and JSON framing. */
export function useChatSocket({
  url,
  onEvent,
  onError,
  enabled = true,
  retryDelayMs = 2000,
}: UseChatSocketOptions): UseChatSocketResult {
  const [ready, setReady] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const queueRef = useRef<string[]>([]);
  const closedByUserRef = useRef(false);
  const onEventRef = useRef(onEvent);
  const onErrorRef = useRef(onError);

  onEventRef.current = onEvent;
  onErrorRef.current = onError;

  const flush = useCallback(() => {
    const ws = wsRef.current;
    if (!ws || ws.readyState !== WebSocket.OPEN) return;
    while (queueRef.current.length > 0) {
      ws.send(queueRef.current.shift()!);
    }
  }, []);

  useEffect(() => {
    if (!enabled) return;
    closedByUserRef.current = false;

    let retryTimer: number | undefined;

    const connect = () => {
      const ws = new WebSocket(url);
      wsRef.current = ws;
      ws.onopen = () => {
        setReady(true);
        flush();
      };
      ws.onmessage = (e) => {
        try {
          const parsed = JSON.parse(e.data) as ServerEvent;
          onEventRef.current(parsed);
        } catch {
          // ignore non-JSON frames
        }
      };
      ws.onerror = (e) => onErrorRef.current?.(e);
      ws.onclose = () => {
        setReady(false);
        wsRef.current = null;
        if (!closedByUserRef.current) {
          retryTimer = window.setTimeout(connect, retryDelayMs);
        }
      };
    };

    connect();

    return () => {
      closedByUserRef.current = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [url, enabled, retryDelayMs, flush]);

  const send = useCallback(
    (event: ClientEvent) => {
      const payload = JSON.stringify(event);
      const ws = wsRef.current;
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(payload);
      } else {
        queueRef.current.push(payload);
      }
    },
    [],
  );

  const close = useCallback(() => {
    closedByUserRef.current = true;
    wsRef.current?.close();
  }, []);

  return { send, ready, close };
}
