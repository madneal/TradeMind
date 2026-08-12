"""TradeMind MCP Server（stdio）——把注册工具暴露给 Claude Code 等 agent。

用法（Claude Code 示例）:
  claude mcp add trademind -- uv run --directory /path/to/TradeMind python mcp_server.py

协议：极简 JSON-RPC over stdin/stdout（tools/list + tools/call）。
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def main() -> None:
    import tools  # noqa: F401
    from tools.registry import all_schemas, call_tool, list_tools

    _log(f"TradeMind MCP: {len(list_tools())} tools ready")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _respond({"jsonrpc": "2.0", "error": {"code": -32700, "message": "parse error"}, "id": None})
            continue

        rid = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            _respond({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "trademind", "version": "0.2.0"},
                },
            })
        elif method == "notifications/initialized":
            continue
        elif method == "tools/list":
            tools_out = []
            for sch in all_schemas():
                tools_out.append({
                    "name": sch["name"],
                    "description": sch.get("description") or "",
                    "inputSchema": sch.get("parameters") or {"type": "object", "properties": {}},
                })
            _respond({"jsonrpc": "2.0", "id": rid, "result": {"tools": tools_out}})
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments") or {}
            if not name:
                _respond({
                    "jsonrpc": "2.0",
                    "id": rid,
                    "error": {"code": -32602, "message": "missing tool name"},
                })
                continue
            text = call_tool(name, args)
            _respond({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "content": [{"type": "text", "text": text}],
                    "isError": text.startswith("错误") or text.startswith("工具"),
                },
            })
        elif method == "ping":
            _respond({"jsonrpc": "2.0", "id": rid, "result": {}})
        else:
            # 忽略未知 notification
            if rid is None:
                continue
            _respond({
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"method not found: {method}"},
            })


def _respond(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
