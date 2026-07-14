"""固定策略工具：策略目录 / 单票决策 / 持仓决策清单。"""

from tools.registry import register


@register(
    name="list_strategies",
    description="列出 TradeMind 固定分析策略与买卖规则（均线/MACD/RSI/BOLL/持仓纪律）。当用户问'有哪些策略''买卖规则是什么''策略说明'时使用。",
    parameters={"type": "object", "properties": {}},
)
def list_strategies() -> dict:
    from strategy.rules import STRATEGY_CATALOG

    return {
        "strategies": STRATEGY_CATALOG,
        "note": "最终动作由 D1_DECISION 合成：买入/加仓/卖出/减仓/观望",
        "disclaimer": "规则信号不构成投资建议",
    }


@register(
    name="decide_code",
    description="按固定策略对单只股票/ETF 给出买入/卖出/观望决策及每条规则理由。当用户问'该不该买''能不能卖''某某代码操作建议'时使用。",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "6 位代码，如 518880、600418",
            },
            "days": {
                "type": "integer",
                "description": "K 线天数，默认 90",
                "default": 90,
            },
        },
        "required": ["code"],
    },
)
def decide_code(code: str, days: int = 90) -> dict:
    from strategy.engine import evaluate_code
    from portfolio import load_positions
    from data.source import normalize_code, get_quotes
    from data.industry import get_industry

    code = normalize_code(code)
    held = False
    shares = 0
    cost_price = 0.0
    weight_pct = 0.0
    pnl_pct = None
    gold_theme_weight = 0.0
    name = ""
    industry = ""

    positions = load_positions()
    if positions:
        from tools.portfolio import get_portfolio
        from strategy.engine import _is_gold_theme

        pf = get_portfolio()
        total = pf.get("total_market_value") or 0
        for item in pf.get("positions", []):
            n = item.get("name") or ""
            ind = get_industry(item["code"], n)
            if _is_gold_theme(item["code"], n, ind):
                gold_theme_weight += item.get("market_value") or 0
        if total:
            gold_theme_weight = gold_theme_weight / total * 100

        for p in positions:
            if p.code == code:
                held = True
                shares = p.shares
                cost_price = p.cost_price
                for item in pf.get("positions", []):
                    if item["code"] == code:
                        weight_pct = item.get("weight_pct") or 0
                        name = item.get("name") or ""
                        price = item.get("price") or 0
                        cost_v = cost_price * shares
                        if cost_v > 0 and price:
                            pnl_pct = (price * shares - cost_v) / cost_v * 100
                        break
                break

    d = evaluate_code(
        code,
        held=held,
        shares=shares,
        cost_price=cost_price,
        weight_pct=weight_pct,
        pnl_pct=pnl_pct,
        name=name,
        industry=industry or get_industry(code, name),
        gold_theme_weight=gold_theme_weight,
        days=days,
    )
    return d.to_dict()


@register(
    name="decide_portfolio",
    description="对全部持仓按固定策略给出每只的买入/加仓/卖出/减仓/观望清单。当用户问'持仓怎么操作''哪些该卖''调仓建议''买卖清单'时使用。",
    parameters={
        "type": "object",
        "properties": {
            "days": {
                "type": "integer",
                "description": "K 线天数，默认 90",
                "default": 90,
            },
        },
    },
)
def decide_portfolio(days: int = 90) -> dict:
    from strategy.engine import evaluate_portfolio

    return evaluate_portfolio(days=days)
