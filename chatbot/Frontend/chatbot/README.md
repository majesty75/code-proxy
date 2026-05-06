# `chatbot/` — frontend module

Drop into your features folder, e.g. `src/features/chatbot/`.

```
chatbot/
├── routes/                       # TanStack file-based routes
├── components/                   # shadcn/assistant-ui pieces
├── runtime/websocketRuntime.ts   # bridges WS protocol → assistant-ui store
├── hooks/                        # WS hook + TanStack Query helpers
├── lib/                          # REST client + wire types
└── types.ts                      # DTOs mirrored from the backend
```

The WebSocket runtime is the only opinionated piece — it translates our
`{type, data}` frames into `assistant-ui`'s message store. If you need a
different chat UI, keep `useChatSocket` and write a new adapter.

## Wire types

`lib/chat-events.ts` mirrors `chatbot/Backend/chat/consumers.py`. If you change
the backend protocol, update this file by hand.

## Dependencies

Required:
- `@assistant-ui/react` (with `@assistant-ui/react-markdown` if you render
  assistant text as markdown).
- `@tanstack/react-query`
- `@tanstack/react-router`
- shadcn `ui/button|card|dialog|input|label|switch|scroll-area|badge`

The components import shadcn UI from `@/components/ui/*`. Adjust the import
alias to match your project.
