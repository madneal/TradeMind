"""管道 / 扫描 / 自选 / 清仓账本 工具注册。"""

from __future__ import annotations

from tools.registry import register


@register(
    name="score_strong",
    description="对单只 A 股按强势评分表打分（MA20/相对强度/量价）。≥7 且无否决才可按强者策略。",
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "6 位代码"},
        },
        "required": ["code"],
    },
)
def score_strong(code: str) -> dict:
    from strategy.strong_score import score_code

    return score_code(code)


@register(
    name="buy_pipeline",
    description=(
        "新开仓/加仓完整管道：事实底稿+强势分+F0/F1+decide+知识库提醒+反思清单。"
        "用户问能不能买、适合建仓时优先使用。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "days": {"type": "integer", "default": 90},
        },
        "required": ["code"],
    },
)
def buy_pipeline(code: str, days: int = 90) -> dict:
    from strategy.pipeline import run_buy_pipeline

    return run_buy_pipeline(code, days=days)


@register(
    name="debate_code",
    description=(
        "单票多空辩论：同一事实底稿上的多方/空方要点+主持验证清单+规则 decide 收尾。"
        "不替代纪律红灯；终点是验证清单而非荐股。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string"},
            "days": {"type": "integer", "default": 90},
        },
        "required": ["code"],
    },
)
def debate_code(code: str, days: int = 90) -> dict:
    from strategy.pipeline import run_debate

    return run_debate(code, days=days)


@register(
    name="scan_strong_stocks",
    description="扫描当日强势池：强势分≥阈值且过 F0/F1 过滤。返回 preferred/黄灯/红灯列表。",
    parameters={
        "type": "object",
        "properties": {
            "min_score": {"type": "integer", "default": 7},
            "top_n": {"type": "integer", "default": 12},
        },
        "required": [],
    },
)
def scan_strong_stocks(min_score: int = 7, top_n: int = 12) -> dict:
    from strategy.scan_strong import scan_strong_market

    return scan_strong_market(min_score=min_score, top_n=top_n)


@register(
    name="list_watchlist",
    description="查看本地自选股列表（watchlist.toml）。",
    parameters={"type": "object", "properties": {}},
)
def list_watchlist() -> dict:
    from watchlist import load_watchlist

    codes = load_watchlist()
    return {"codes": codes, "count": len(codes)}


@register(
    name="list_closed_positions",
    description="查看已清仓账本（closed.toml），用于复盘。",
    parameters={"type": "object", "properties": {}},
)
def list_closed_positions() -> dict:
    from closed_ledger import load_closed

    rows = load_closed()
    return {
        "count": len(rows),
        "closed": [
            {
                "code": r.code,
                "name": r.name,
                "shares": r.shares,
                "cost_price": r.cost_price,
                "exit_price": r.exit_price,
                "pnl_pct": r.pnl_pct,
                "closed_date": r.closed_date,
                "note": r.note,
            }
            for r in rows
        ],
    }
