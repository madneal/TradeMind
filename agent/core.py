"""Agent 主循环：ReAct（Reason + Act）实现。

核心流程：
1. 用户输入 + 系统提示词 → 调 LLM
2. LLM 返回 tool_calls → 执行工具 → 结果回灌
3. 重复，直到 LLM 不再调用工具，给出最终回答
"""

from __future__ import annotations

from typing import Callable

from agent.prompts import SYSTEM_PROMPT
from config import MAX_TOOL_ITERATIONS
from llm import chat_with_tools
from tools.registry import all_schemas, call_tool

# 工具执行回调：(tool_name, arguments) -> None，供 CLI 显示进度
ToolObserver = Callable[[str, dict], None]


def run(
    user_input: str,
    history: list[dict] | None = None,
    on_tool_call: ToolObserver | None = None,
) -> str:
    """运行一次 agent 对话。

    Args:
        user_input: 用户本轮输入
        history: 之前的对话历史（不含本轮），支持多轮
        on_tool_call: 工具调用时的回调（用于 CLI 显示调用过程）

    Returns:
        agent 的最终文本回答
    """
    import tools  # noqa: F401  触发工具注册

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_input})

    tool_schemas = all_schemas()

    for iteration in range(MAX_TOOL_ITERATIONS):
        resp = chat_with_tools(messages, tool_schemas)

        if not resp.tool_calls:
            # 没有工具调用，说明 LLM 给出了最终回答
            return resp.content or "(无回答)"

        # 把 assistant 的 tool_calls 消息加入历史（OpenAI / xAI 格式）
        messages.append({
            "role": "assistant",
            "content": resp.content or "",
            "tool_calls": [
                {
                    "id": tc.get("id") or f"call_{i}",
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": _stringify_args(tc["arguments"]),
                    },
                }
                for i, tc in enumerate(resp.tool_calls)
            ],
        })

        # 执行每个工具调用，把结果作为 tool 角色消息回灌
        for i, tc in enumerate(resp.tool_calls):
            name = tc["name"]
            args = tc["arguments"]
            call_id = tc.get("id") or f"call_{i}"
            if on_tool_call:
                on_tool_call(name, args)
            result = call_tool(name, args)
            messages.append({
                "role": "tool",
                "content": result,
                "tool_call_id": call_id,
            })

    # 超过最大迭代仍未完成
    return "（已达到最大工具调用次数，未能完成分析。请尝试缩小问题范围或稍后重试。）"


def _stringify_args(args: dict) -> str:
    import json

    return json.dumps(args, ensure_ascii=False)
