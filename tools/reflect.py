"""反思审计（轻量）：对已有分析文本做结构性质询清单。

不调用外网模型时：返回「自检清单」供 Agent/人填写；
有 LLM 的 chat 路径可在 system 中要求对照本工具输出做审计。
"""

from __future__ import annotations

from tools.registry import register


@register(
    name="reflect_analysis",
    description=(
        "对一段已写好的投研/持仓分析做「反思审计」框架：列出需核对的数据支撑、"
        "可能脑补点、最脆弱假设、验证清单。不产生买卖结论。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "待审计的分析正文（可截断至约 8000 字）",
            },
            "title": {
                "type": "string",
                "description": "可选标题",
            },
        },
        "required": ["text"],
    },
)
def reflect_analysis(text: str, title: str = "") -> dict:
    body = (text or "").strip()
    if len(body) > 8000:
        body = body[:8000] + "\n…(已截断)"
    # 启发式：数字与断言密度
    import re

    numbers = re.findall(r"-?\d+(?:\.\d+)?%?", body)
    strong_words = re.findall(
        r"必须|一定|肯定|稳了|翻倍|抄底|无风险|保证|主升浪", body
    )
    return {
        "title": title or "反思审计",
        "char_len": len(body),
        "number_tokens_found": len(numbers),
        "strong_language_hits": strong_words[:20],
        "checklist": [
            "哪些结论有工具 JSON / 财报字段直接支撑？请逐条标注来源。",
            "哪些表述无法对应数据（如「机构广泛认可」「资金疯狂」）？标为推测。",
            "若最终判断错误，最可能错在哪一环（估值/资金/财报/情绪/仓位）？",
            "F0/F1 与强势分是否检查？红灯是否仍被叙事覆盖？",
            "有无违反 A1 无退出、A2 主题仓位、B4 摊平、B5 超卖当买点？",
            "下一步最小验证：要看什么数据、哪里看、何时更新？",
        ],
        "instruction_for_llm": (
            "请对照 checklist 审计用户分析：分条回答「有数据 / 推测 / 脆弱点 / 验证清单」。"
            "禁止新增买卖指令；可引用 decide_* 已有动作。"
        ),
        "excerpt_preview": body[:400],
    }
