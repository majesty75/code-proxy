"""Tool registry.

Three sources are unioned at agent build time:
    1. `_BUILTINS`   : in-process Python functions hard-coded here.
    2. DB `Tool` rows enabled on the conversation (kind=builtin/http/sql).
    3. MCP tools     : see ``mcp.py``.

DB-defined tools store their schema in ``config``. ``http`` tools call out to a
URL using ``requests``; ``sql`` tools run a parameterised, read-only query.
Both wrap the result as a string so the agent can consume it.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import requests
from django.db import connections
from langchain_core.tools import StructuredTool, BaseTool
from pydantic import BaseModel, create_model

from ..models import Conversation, Tool


# --- builtins -------------------------------------------------------------- #

def _current_time(tz: str = "UTC") -> str:
    """Return the current ISO-8601 UTC timestamp."""
    return datetime.now(timezone.utc).isoformat()


_BUILTINS: dict[str, Callable[..., Any]] = {
    "current_time": _current_time,
}


def _builtin_tool(row: Tool) -> BaseTool | None:
    fn_name = (row.config or {}).get("fn", row.name)
    fn = _BUILTINS.get(fn_name)
    if fn is None:
        return None
    return StructuredTool.from_function(
        func=fn, name=row.name, description=row.description
    )


# --- HTTP tool ------------------------------------------------------------- #

def _schema_from_dict(name: str, body_schema: dict[str, Any]) -> type[BaseModel]:
    """Build a tiny pydantic model from a {field: {type, required, description}} dict."""
    type_map = {
        "string": str,
        "integer": int,
        "number": float,
        "boolean": bool,
        "object": dict,
        "array": list,
    }
    fields: dict[str, tuple[type, Any]] = {}
    for fname, spec in (body_schema or {}).items():
        py_type = type_map.get((spec or {}).get("type", "string"), str)
        default = ... if (spec or {}).get("required") else None
        fields[fname] = (py_type, default)
    if not fields:
        fields["input"] = (str, "")
    return create_model(f"{name}Args", **fields)  # type: ignore[arg-type]


def _http_tool(row: Tool) -> BaseTool:
    cfg = row.config or {}
    url = cfg.get("url", "")
    method = (cfg.get("method") or "POST").upper()
    headers = cfg.get("headers") or {}
    timeout = cfg.get("timeout", 30)
    schema = _schema_from_dict(row.name, cfg.get("body_schema") or {})

    def _call(**kwargs: Any) -> str:
        if not url:
            return "tool misconfigured: missing url"
        resp = requests.request(
            method, url, headers=headers, json=kwargs, timeout=timeout
        )
        return f"{resp.status_code}\n{resp.text[:8000]}"

    return StructuredTool.from_function(
        func=_call,
        name=row.name,
        description=row.description,
        args_schema=schema,
    )


# --- SQL tool -------------------------------------------------------------- #

def _sql_tool(row: Tool) -> BaseTool:
    cfg = row.config or {}
    connection_alias = cfg.get("connection", "default")
    query_template = cfg.get("query_template", "")
    schema = _schema_from_dict(row.name, cfg.get("params_schema") or {})

    def _call(**kwargs: Any) -> str:
        if not query_template:
            return "tool misconfigured: missing query_template"
        with connections[connection_alias].cursor() as cur:
            cur.execute(query_template, kwargs)
            cols = [c[0] for c in cur.description] if cur.description else []
            rows = cur.fetchmany(200)
        return "\n".join([",".join(cols), *[",".join(map(str, r)) for r in rows]])

    return StructuredTool.from_function(
        func=_call,
        name=row.name,
        description=row.description,
        args_schema=schema,
    )


_FACTORIES = {
    Tool.KIND_BUILTIN: _builtin_tool,
    Tool.KIND_HTTP: _http_tool,
    Tool.KIND_SQL: _sql_tool,
}


def collect_db_tools(conversation: Conversation) -> list[BaseTool]:
    rows = conversation.enabled_tools.filter(enabled=True)
    out: list[BaseTool] = []
    for row in rows:
        factory = _FACTORIES.get(row.kind)
        if not factory:
            continue
        try:
            tool = factory(row)
        except Exception:  # noqa: BLE001 - tool defs come from the DB
            continue
        if tool is not None:
            out.append(tool)
    return out
