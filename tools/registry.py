"""工具注册表。

每个工具注册时声明 JSON Schema（供 LLM function calling）。
Agent 通过 registry 调用工具并拿到结果。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema
    func: Callable[..., Any]

    def to_schema(self) -> dict:
        """转为 OpenAI / xAI function calling 的 function 本体。"""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


_REGISTRY: dict[str, Tool] = {}


def register(name: str, description: str, parameters: dict) -> Callable:
    """装饰器：注册一个工具。"""

    def decorator(func: Callable) -> Callable:
        _REGISTRY[name] = Tool(name=name, description=description, parameters=parameters, func=func)
        return func

    return decorator


def get_tool(name: str) -> Tool | None:
    return _REGISTRY.get(name)


def list_tools() -> list[Tool]:
    return list(_REGISTRY.values())


def call_tool(name: str, arguments: dict | str) -> str:
    """调用工具并返回字符串结果（供 LLM 读取）。

    arguments 支持 dict 或 JSON 字符串。
    """
    tool = get_tool(name)
    if tool is None:
        return f"错误：未找到工具 '{name}'"
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError:
            return f"错误：工具 '{name}' 参数不是合法 JSON：{arguments}"
    try:
        result = tool.func(**arguments)
        # 结果统一转字符串
        if isinstance(result, str):
            return result
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return f"工具 '{name}' 执行出错：{type(e).__name__}: {e}"


def all_schemas() -> list[dict]:
    """所有工具的 schema，传给 LLM。"""
    return [t.to_schema() for t in _REGISTRY.values()]
