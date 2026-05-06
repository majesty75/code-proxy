# Chatbot scaffold

A drop-in chatbot for the existing Django + React/TanStack/shadcn stack.

```
chatbot/
├── Backend/chat/         # Django app — copy into your apps directory
└── Frontend/chatbot/     # React module — copy into your frontend feature folder
```

This is **a scaffold**, not a finished product. It assumes you already have:
- Django with `channels` + `channels-redis` configured for ASGI.
- Django REST Framework.
- Standard auth: middleware that puts `request.user` (and `scope["user"]` for WS) on the request.
- React + TanStack Router + TanStack Query + shadcn/ui set up in the frontend.

## What you get

- 7 models: `UserMeta`, `SystemPrompt`, `MCPServer`, `Tool`, `Conversation`, `Message`, `Attachment`.
- A WebSocket consumer that streams a LangChain/LangGraph agent turn back to the client (text + thinking + tool calls).
- An OpenAI-compatible LLM factory (`base_url` + `api_key` + `model` per conversation/user) — works with vLLM, LM Studio, llama.cpp server, TGI, or any other OpenAI-shaped endpoint.
- An MCP loader using `langchain-mcp-adapters` (`MultiServerMCPClient`) — register MCP servers in the Django admin and toggle them per conversation.
- A DB-backed `Tool` registry: `builtin`, `http`, or parameterised read-only `sql`.
- A frontend chat thread built on `assistant-ui`, with custom blocks for **thinking** and **tool calls**, plus image/file attachments.

## Backend integration

1. **Copy** `chatbot/Backend/chat` into your apps directory and add to `INSTALLED_APPS`:

   ```python
   INSTALLED_APPS = [
       ...,
       "rest_framework",
       "channels",
       "chat",
   ]
   ```

2. **Mount** REST + WebSocket URLs:

   ```python
   # urls.py
   from django.urls import include, path
   urlpatterns += [path("api/chat/", include("chat.urls"))]

   # asgi.py — merge into your existing routing
   from channels.auth import AuthMiddlewareStack
   from channels.routing import ProtocolTypeRouter, URLRouter
   from chat.routing import websocket_urlpatterns

   application = ProtocolTypeRouter({
       "http": django_asgi_app,
       "websocket": AuthMiddlewareStack(URLRouter(websocket_urlpatterns)),
   })
   ```

3. **Settings**:

   ```python
   CHAT_DEFAULT_BASE_URL = "http://vllm:8000/v1"
   CHAT_DEFAULT_MODEL    = "qwen2.5:7b-instruct"
   CHAT_DEFAULT_API_KEY  = "EMPTY"        # vLLM with no auth

   # 32-byte urlsafe-base64 key for encrypting per-user API keys at rest.
   # Generate with:  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
   CHAT_FERNET_KEY = os.environ["CHAT_FERNET_KEY"]
   ```

4. **Install** Python deps:

   ```
   pip install langchain langgraph langchain-openai langchain-mcp-adapters cryptography
   ```

5. **Migrate + seed**:

   ```
   python manage.py makemigrations chat
   python manage.py migrate
   python manage.py seed_chat
   ```

## Frontend integration

1. **Copy** `chatbot/Frontend/chatbot` into your features folder (e.g. `src/features/chatbot/`).

2. **Install** deps:

   ```
   pnpm add @assistant-ui/react @assistant-ui/react-markdown
   ```

   (`@tanstack/react-query`, `@tanstack/react-router`, and shadcn `ui/button|card|dialog|input|label|switch|scroll-area|badge` are assumed to already exist.)

3. **Wire routes** — `routes/chat.tsx` and `routes/chat.$conversationId.tsx` are written for TanStack Router's file-based routing. If your project uses code-based routing instead, lift `ChatLayout` and `ChatRoute` into your route tree.

4. **Auth** — `lib/api.ts` accepts a `getAuthHeaders` callback. Wire it from your existing auth context to inject your bearer/cookie/CSRF header.

## How extensibility works

| Add a…             | Where                                                                     |
|--------------------|---------------------------------------------------------------------------|
| MCP server         | `/admin/chat/mcpserver/add/` or `POST /api/chat/mcp-servers/` then enable on a conversation |
| Built-in tool      | Register a Python function in `chat/agent/tools.py::_BUILTINS`, create a `Tool` row pointing at it |
| HTTP tool          | `Tool` row, `kind=http`, `config={url, method, headers, body_schema}`     |
| SQL tool           | `Tool` row, `kind=sql`, `config={connection, query_template, params_schema}` |
| System prompt      | `SystemPrompt` row, link from `Conversation.system_prompt`                |
| Per-user API key   | `PATCH /api/chat/me/meta/` with `{set_secrets: {openai_api_key: "..."}}`  |

## End-to-end smoke test

1. Start Django ASGI server (e.g. `daphne` or `uvicorn ... --interface asgi3`).
2. Start your React dev server.
3. Visit `/chat`, click **New**, then click into the conversation.
4. Send "hi" → expect text streaming back.
5. Open Settings → enable the `current_time` tool on the conversation. Ask "what time is it?" → tool call card appears with args + result.
6. Drop a PNG into the composer → expect the model to describe it (requires a multi-modal model on the LLM endpoint).
7. Register an MCP server (e.g. `mcp-server-fetch` over stdio) in admin, enable it on the conversation, ask the model to fetch a URL.
