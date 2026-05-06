"""LangChain/LangGraph agent layer for the chat app.

The pieces here are intentionally small and side-effect-free so they can be
exercised from the WS consumer, REST views, or unit tests:

    - llm.py        : ChatOpenAI factory (OpenAI-compatible base_url)
    - prompts.py    : resolve a SystemPrompt for a Conversation
    - tools.py      : built-in registry + DB-backed Tool loader
    - mcp.py        : MultiServerMCPClient construction from DB
    - builder.py    : assemble the LangGraph agent
    - streaming.py  : translate astream_events -> WS events
"""

from .builder import build_agent
from .streaming import stream_to_ws

__all__ = ["build_agent", "stream_to_ws"]
