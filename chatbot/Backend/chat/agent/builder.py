"""Assemble the LangGraph agent for a conversation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.tools import BaseTool

from ..models import Conversation, UserMeta
from .llm import get_llm
from .mcp import build_mcp_client
from .prompts import resolve_system_prompt
from .tools import collect_db_tools


@dataclass
class AgentBundle:
    """A built agent + everything that needs to be cleaned up after one turn."""

    graph: Any
    system_prompt: str
    tools: list[BaseTool]
    mcp_client: Any  # MultiServerMCPClient | None

    async def aclose(self) -> None:
        if self.mcp_client is not None and hasattr(self.mcp_client, "aclose"):
            try:
                await self.mcp_client.aclose()
            except Exception:  # noqa: BLE001
                pass


async def build_agent(conversation: Conversation, meta: UserMeta | None) -> AgentBundle:
    # Imported lazily because LangGraph is the heaviest dep.
    from langgraph.prebuilt import create_react_agent

    llm = get_llm(conversation, meta)
    system_prompt = resolve_system_prompt(conversation)

    db_tools = collect_db_tools(conversation)
    mcp_client, mcp_tools = await build_mcp_client(conversation)

    tools: list[BaseTool] = [*db_tools, *mcp_tools]

    graph = create_react_agent(model=llm, tools=tools, prompt=system_prompt)

    return AgentBundle(
        graph=graph,
        system_prompt=system_prompt,
        tools=tools,
        mcp_client=mcp_client,
    )
