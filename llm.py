"""xAI Grok 客户端封装（OpenAI 兼容 API）。

默认走 Grok：https://api.x.ai/v1
提供 chat_with_tools：发送消息 + 工具定义，返回 LLM 响应。
响应可能是最终文本，也可能是 tool_calls（交给 agent 循环处理）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from config import XAI_API_KEY, XAI_BASE_URL, XAI_MODEL

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        if not XAI_API_KEY:
            raise RuntimeError(
                "未配置 XAI_API_KEY，请在 .env 中设置（参考 .env.example）\n"
                "申请地址：https://console.x.ai"
            )
        _client = OpenAI(api_key=XAI_API_KEY, base_url=XAI_BASE_URL)
    return _client


@dataclass
class LLMResponse:
    """LLM 一次调用的结果。"""

    content: str | None  # 文本回复（若已有最终回答）
    tool_calls: list[dict]  # 每个含 id / name / arguments(dict)
    raw: Any  # 原始响应，调试用


def chat_with_tools(
    messages: list[dict],
    tools: list[dict],
    temperature: float = 0.7,
) -> LLMResponse:
    """调用 Grok，支持 function calling。

    Args:
        messages: 对话历史，每条 {"role": ..., "content": ...}
        tools: 工具 schema 列表（registry.all_schemas() 的输出，function 本体）
    """
    client = _get_client()

    # OpenAI / xAI tools 格式：[{"type": "function", "function": {...}}]
    openai_tools = (
        [{"type": "function", "function": t} for t in tools] if tools else None
    )

    kwargs: dict = {
        "model": XAI_MODEL,
        "messages": messages,
        "temperature": temperature,
    }
    if openai_tools:
        kwargs["tools"] = openai_tools
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
            tool_calls.append(
                {
                    "id": tc.id or f"call_{len(tool_calls)}",
                    "name": tc.function.name,
                    "arguments": args,
                }
            )

    return LLMResponse(content=msg.content, tool_calls=tool_calls, raw=resp)
