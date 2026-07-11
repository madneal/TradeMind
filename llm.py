"""智谱 GLM 客户端封装。

提供 chat_with_tools：发送消息 + 工具定义，返回 LLM 响应。
响应可能是最终文本，也可能是 tool_calls（交给 agent 循环处理）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zhipuai import ZhipuAI

from config import ZHIPU_API_KEY, ZHIPU_MODEL

_client: ZhipuAI | None = None


def _get_client() -> ZhipuAI:
    global _client
    if _client is None:
        if not ZHIPU_API_KEY:
            raise RuntimeError(
                "未配置 ZHIPU_API_KEY，请在 .env 中设置（参考 .env.example）"
            )
        _client = ZhipuAI(api_key=ZHIPU_API_KEY)
    return _client


@dataclass
class LLMResponse:
    """LLM 一次调用的结果。"""
    content: str | None  # 文本回复（若已有最终回答）
    tool_calls: list[dict]  # 工具调用列表，每个含 name 和 arguments(dict)
    raw: Any  # 原始响应，调试用


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.7,
) -> LLMResponse:
    """调用 GLM，支持 function calling。

    Args:
        messages: 对话历史，每条 {"role": ..., "content": ...}
        tools: 工具 schema 列表（registry.all_schemas() 的输出，会被包装成智谱格式）
    """
    client = _get_client()

    # 智谱 tools 格式：[{"type": "function", "function": {...}}]
    zhipu_tools = [{"type": "function", "function": t} for t in tools] if tools else None

    kwargs: dict = {
        "model": ZHIPU_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if zhipu_tools:
        kwargs["tools"] = zhipu_tools
        kwargs["tool_choice"] = "auto"

    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    msg = choice.message

    # 解析 tool_calls
    tool_calls: list[dict] = []
    if msg.tool_calls:
        import json

        for tc in msg.tool_calls:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {"_raw": args}
            tool_calls.append({"name": tc.function.name, "arguments": args})

    return LLMResponse(content=msg.content, tool_calls=tool_calls, raw=resp)
