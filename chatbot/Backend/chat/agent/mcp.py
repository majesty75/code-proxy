"""MCP tool loader using ``langchain-mcp-adapters``.

We translate the union of the conversation's enabled MCP servers into the
``MultiServerMCPClient`` config dict shape, then return the resulting
LangChain tools.

The client owns subprocesses (for stdio transports), so callers should hold a
reference to it for the lifetime of the conversation turn and call ``aclose()``
when done. ``build_mcp_client`` returns the client so the caller controls it.
"""

from __future__ import annotations

from typing import Any

from langchain_core.tools import BaseTool

from ..models import Conversation, MCPServer


def _server_to_config(server: MCPServer) -> dict[str, Any]:
    cfg = dict(server.config or {})
    cfg["transport"] = server.transport
    return cfg


async def build_mcp_client(conversation: Conversation):
    """Return ``(client, tools)`` or ``(None, [])`` if no MCP servers are enabled."""
    servers = list(
        conversation.enabled_mcp_servers.filter(enabled=True).all()
    )
    if not servers:
        return None, []

    # Imported lazily so the app boots even if the dep is missing in dev.
    from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore

    config = {s.name: _server_to_config(s) for s in servers}
    client = MultiServerMCPClient(config)
    tools: list[BaseTool] = await client.get_tools()
    return client, tools
