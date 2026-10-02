"""Tool registry - add a new tool in under 10 lines.

Example:
    class MyArgs(BaseModel):
        q: str
    @register_tool("my_tool", "does X", MyArgs)
    async def my_tool(q: str) -> str:
        return f"got {q}"
"""
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Type
from pydantic import BaseModel

logger = logging.getLogger("hackathon.tools")

TOOL_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_tool(name: str, description: str, args_schema: Optional[Type[BaseModel]] = None):
    def deco(fn: Callable):
        TOOL_REGISTRY[name] = {"name": name, "description": description, "args_schema": args_schema, "fn": fn}
        return fn
    return deco


class CalcArgs(BaseModel):
    expression: str


@register_tool("calculator", "Evaluate a simple math expression (numbers + - * / ( )).", CalcArgs)
async def calculator(expression: str) -> str:
    allowed = set("0123456789+-*/(). %")
    if not set(expression) <= allowed:
        return "Error: only numbers and + - * / ( ) allowed"
    try:
        # No builtins, math only.
        result = eval(expression, {"__builtins__": {}}, {})  # noqa: S307 - sandboxed charset above
        return str(result)
    except Exception as e:
        return f"Error: {e}"


class SearchArgs(BaseModel):
    query: str
    top_k: int = 3


@register_tool("text_search", "Keyword search over uploaded/RAG documents.", SearchArgs)
async def text_search(query: str, top_k: int = 3) -> str:
    try:
        from app.rag.service import get_rag
        rag = get_rag()
        qr = await rag.query(query, top_k=top_k)
        if not qr.get("hits"):
            return "No matching documents."
        return qr.get("context", "")[:1500]
    except Exception as e:
        return f"Search unavailable: {e}"


class TimeArgs(BaseModel):
    pass


@register_tool("get_current_time", "Return current UTC time.", TimeArgs)
async def get_current_time() -> str:
    return datetime.now(timezone.utc).isoformat()


async def call_tool(name: str, args: Dict[str, Any]) -> str:
    entry = TOOL_REGISTRY.get(name)
    if not entry:
        return f"Error: unknown tool '{name}'"
    fn = entry["fn"]
    try:
        return await fn(**args)
    except TypeError as e:
        return f"Error: bad args for {name}: {e}"
    except Exception as e:
        logger.warning("tool %s failed: %s", name, e)
        return f"Error: {e}"


def tool_specs() -> str:
    lines = []
    for n, e in TOOL_REGISTRY.items():
        schema = ""
        if e["args_schema"] is not None:
            try:
                schema = str(e["args_schema"].model_json_schema().get("properties", {}).keys())
            except Exception:
                schema = ""
        lines.append(f"- {n}: {e['description']} args={schema}")
    return "\n".join(lines)
