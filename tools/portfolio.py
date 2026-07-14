"""持仓分析工具：get_portfolio / analyze_pnl / analyze_portfolio_risk。

LLM 可通过这些工具对用户的持仓进行行情概览、盈亏分析、组合风险评估。
"""

from __future__ import annotations

from tools.registry import register


def _load_and_quote() -> tuple[list, list]:
    """加载持仓 + 批量拉行情。返回 (positions, quotes)。"""
    from portfolio import load_positions
    from data.source import get_quotes

    positions = load_positions()
    if not positions:
        return [], []
    codes = [p.code for p in positions]
    quotes = get_quotes(codes)
    return positions, quotes


@register(
    name="get_portfolio",
    description="获取用户持仓概览：每只持仓的实时价格、涨跌幅、市值、占组合比例。当用户问'我的持仓怎么样''持仓概览''持仓情况'时使用。",
    parameters={
        "type": "object",
        "properties": {},
    },
)
def get_portfolio() -> dict:
    positions, quotes = _load_and_quote()
    if not positions:
        return {"message": "持仓为空，请先用 add 命令添加持仓（uv run trademind portfolio add 600519 100 1500）"}

    quote_map = {q["code"]: q for q in quotes}
    total_market_value = 0.0
    items = []
    for p in positions:
        q = quote_map.get(p.code, {})
        price = q.get("price") or 0
        market_value = price * p.shares
        total_market_value += market_value
        items.append({
            "code": p.code,
            "name": q.get("name", ""),
            "shares": p.shares,
            "cost_price": p.cost_price,
            "price": price,
            "pct_change": q.get("pct_change"),
            "market_value": round(market_value, 2),
        })

    # 计算占比
    for item in items:
        item["weight_pct"] = round(item["market_value"] / total_market_value * 100, 2) if total_market_value else 0

    return {
        "total_market_value": round(total_market_value, 2),
        "count": len(items),
        "positions": items,
    }


@register(
    name="analyze_pnl",
    description="分析用户持仓的盈亏情况：每只持仓的浮盈浮亏金额、收益率，以及组合总投入、总市值、总盈亏。当用户问'我赚了多少''盈亏分析''持仓收益'时使用。",
    parameters={
        "type": "object",
        "properties": {},
    },
)
def analyze_pnl() -> dict:
    positions, quotes = _load_and_quote()
    if not positions:
        return {"message": "持仓为空"}

    quote_map = {q["code"]: q for q in quotes}
    total_cost = 0.0
    total_market = 0.0
    items = []
    for p in positions:
        q = quote_map.get(p.code, {})
        price = q.get("price") or 0
        cost = p.cost_price * p.shares
        market = price * p.shares
        pnl = market - cost
        pnl_pct = round(pnl / cost * 100, 2) if cost else 0
        total_cost += cost
        total_market += market
        items.append({
            "code": p.code,
            "name": q.get("name", ""),
            "shares": p.shares,
            "cost_price": p.cost_price,
            "price": price,
            "cost_value": round(cost, 2),
            "market_value": round(market, 2),
            "pnl": round(pnl, 2),
            "pnl_pct": pnl_pct,
        })

    total_pnl = total_market - total_cost
    total_pnl_pct = round(total_pnl / total_cost * 100, 2) if total_cost else 0

    # 按收益率排序
    items.sort(key=lambda x: x["pnl_pct"], reverse=True)

    return {
        "total_cost": round(total_cost, 2),
        "total_market_value": round(total_market, 2),
        "total_pnl": round(total_pnl, 2),
        "total_pnl_pct": total_pnl_pct,
        "positions": items,
    }


@register(
    name="analyze_portfolio_risk",
    description="分析用户持仓组合的风险特征：行业分布、集中度（HHI 指数）、持仓数量、是否有单只占比过高的情况。当用户问'持仓风险''行业分布''是不是太集中'时使用。",
    parameters={
        "type": "object",
        "properties": {},
    },
)
def analyze_portfolio_risk() -> dict:
    from data.industry import get_industry

    positions, quotes = _load_and_quote()
    if not positions:
        return {"message": "持仓为空"}

    quote_map = {q["code"]: q for q in quotes}
    total_market_value = 0.0

    # 按行业归集市值
    industry_value: dict[str, float] = {}
    item_details = []
    for p in positions:
        q = quote_map.get(p.code, {})
        price = q.get("price") or 0
        market_value = price * p.shares
        total_market_value += market_value
        industry = get_industry(p.code, q.get("name", ""))
        industry_value[industry] = industry_value.get(industry, 0) + market_value
        item_details.append({
            "code": p.code,
            "name": q.get("name", ""),
            "industry": industry,
            "market_value": round(market_value, 2),
            "weight_pct": 0,  # 稍后填充
        })

    # 计算行业占比
    industry_items = []
    for ind, val in sorted(industry_value.items(), key=lambda x: x[1], reverse=True):
        pct = round(val / total_market_value * 100, 2) if total_market_value else 0
        industry_items.append({"industry": ind, "market_value": round(val, 2), "weight_pct": pct})

    # HHI 指数（0~10000，越高越集中）
    hhi = sum((v / total_market_value) ** 2 for v in industry_value.values()) * 10000 if total_market_value else 0
    hhi = round(hhi, 0)

    # 单只持仓占比
    for item in item_details:
        item["weight_pct"] = round(item["market_value"] / total_market_value * 100, 2) if total_market_value else 0

    # 风险提示
    warnings = []
    single_max = max((item["weight_pct"] for item in item_details), default=0)
    if single_max > 40:
        warnings.append(f"单只持仓占比过高（{single_max}%），建议分散到 30% 以下")
    if hhi > 2500:
        warnings.append(f"行业集中度偏高（HHI={int(hhi)}），建议覆盖 3 个以上行业")
    if len(positions) < 3:
        warnings.append(f"持仓数量较少（{len(positions)} 只），分散化不足")
    industry_top = industry_items[0]["weight_pct"] if industry_items else 0
    if industry_top > 50:
        warnings.append(f"单一行业占比过高（{industry_top}%），行业风险集中")

    return {
        "count": len(positions),
        "total_market_value": round(total_market_value, 2),
        "industry_distribution": industry_items,
        "hhi": int(hhi),
        "max_single_weight": single_max,
        "warnings": warnings if warnings else ["组合分散度良好"],
        "positions": item_details,
    }
