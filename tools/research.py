"""研究类工具：市场热点 / 板块资金 / 打板情绪 / 公告 / 指数。

客观数据 only；买卖动作仍须走 decide_code / decide_portfolio。
"""

from __future__ import annotations

from tools.registry import register


@register(
    name="get_hot_stocks",
    description=(
        "获取当日 A 股强势股列表及题材归因（同花顺），含主题词频。"
        "用于市场主线、题材热度；不构成买卖建议。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "top_n": {
                "type": "integer",
                "description": "返回强势股条数，默认 25",
                "default": 25,
            },
            "trade_date": {
                "type": "string",
                "description": "可选 YYYY-MM-DD；默认自动取最近有数据交易日",
            },
        },
        "required": [],
    },
)
def get_hot_stocks(top_n: int = 25, trade_date: str | None = None) -> dict:
    from data.research_market import ths_hot_reason

    return ths_hot_reason(trade_date=trade_date, top_n=top_n)


@register(
    name="get_board_fund_flow",
    description=(
        "A 股行业/概念板块主力资金净流入排名（东财）。"
        "用于板块轮动与持仓主题对照；不构成买卖建议。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "board_type": {
                "type": "string",
                "description": "industry | concept | region，默认 industry",
                "default": "industry",
            },
            "period": {
                "type": "string",
                "description": "today | 5d | 10d，默认 today",
                "default": "today",
            },
            "top_n": {
                "type": "integer",
                "description": "返回条数，默认 12",
                "default": 12,
            },
        },
        "required": [],
    },
)
def get_board_fund_flow(
    board_type: str = "industry",
    period: str = "today",
    top_n: int = 12,
) -> dict:
    from data.research_market import board_fund_flow

    return board_fund_flow(board_type=board_type, period=period, top_n=top_n)


@register(
    name="get_limit_sentiment",
    description=(
        "A 股涨停/炸板/跌停情绪摘要：数量、炸板率、连板高度与代表票。"
        "客观榜单事实，不荐股。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "trade_date": {
                "type": "string",
                "description": "可选 YYYYMMDD；默认最近有数据交易日",
            },
        },
        "required": [],
    },
)
def get_limit_sentiment(trade_date: str | None = None) -> dict:
    from data.research_market import limit_up_sentiment

    return limit_up_sentiment(trade_date=trade_date)


@register(
    name="get_announcements",
    description="查询某只 A 股近期公告标题列表（东财）。事件/风险排查时使用。",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "6 位股票代码",
            },
            "page_size": {
                "type": "integer",
                "description": "条数，默认 8",
                "default": 8,
            },
        },
        "required": ["code"],
    },
)
def get_announcements(code: str, page_size: int = 8) -> dict:
    from data.research_market import stock_announcements

    return stock_announcements(code, page_size=page_size)


@register(
    name="get_indices",
    description="主要 A 股指数快照：上证/深成/创业板/沪深300 等涨跌。",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
def get_indices() -> dict:
    from data.research_market import index_snapshot

    return index_snapshot()


@register(
    name="daily_review",
    description=(
        "组装今日 A 股复盘数据包：指数、涨停情绪、板块资金、强势题材、持仓结构与纪律提示。"
        "返回结构化 JSON；落盘请用 CLI `trademind review`。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "include_fundamentals_scan": {
                "type": "boolean",
                "description": "是否扫描持仓 F0/F1（慢，默认 false）",
                "default": False,
            },
        },
        "required": [],
    },
)
def daily_review(include_fundamentals_scan: bool = False) -> dict:
    from tools.review import collect_daily_review

    return collect_daily_review(include_fundamentals_scan=include_fundamentals_scan)


@register(
    name="build_stock_dossier",
    description=(
        "组装单票「事实底稿」：行情 + 近期 K 摘要 + F0/F1 财务质量 + 公告标题。"
        "用于研究/辩论前；买卖动作须另调 decide_code。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "6 位代码"},
            "days": {
                "type": "integer",
                "description": "K 线天数，默认 60",
                "default": 60,
            },
        },
        "required": ["code"],
    },
)
def build_stock_dossier(code: str, days: int = 60) -> dict:
    """底稿先行：不经 LLM 的固定字段包。"""
    from data.source import get_quote, get_kline, normalize_code
    from data.research_market import stock_announcements
    from strategy.fundamentals import evaluate_fundamentals

    code = normalize_code(code)
    missing: list[str] = []
    quote: dict = {}
    try:
        quote = get_quote(code) or {}
        if not quote.get("price"):
            missing.append("quote.price")
    except Exception as e:
        missing.append(f"quote:{e}")
        quote = {"error": str(e)}

    kline_tail: list = []
    ret20 = None
    above_ma20 = None
    try:
        df = get_kline(code, period="daily", days=max(days, 60))
        if df is not None and not df.empty:
            cols = [c for c in ("date", "close", "pct_change", "volume") if c in df.columns]
            tail = df[cols].tail(5).copy()
            tail["date"] = tail["date"].astype(str)
            kline_tail = tail.to_dict(orient="records")
            close = df["close"].astype(float)
            if len(close) >= 21:
                ret20 = round(float(close.iloc[-1] / close.iloc[-21] - 1) * 100, 2)
            if len(close) >= 20:
                ma20 = float(close.tail(20).mean())
                above_ma20 = bool(float(close.iloc[-1]) >= ma20)
        else:
            missing.append("kline")
    except Exception as e:
        missing.append(f"kline:{e}")

    name = quote.get("name") or ""
    fund = evaluate_fundamentals(code, name)
    fund_d = fund.to_dict() if hasattr(fund, "to_dict") else {}

    ann = stock_announcements(code, page_size=5)
    if ann.get("error"):
        missing.append("announcements")

    return {
        "as_of": quote.get("time") or None,
        "code": code,
        "name": name,
        "quote": {
            "price": quote.get("price"),
            "pct_change": quote.get("pct_change"),
            "source": quote.get("source"),
        },
        "structure": {
            "ret20_pct": ret20,
            "above_ma20": above_ma20,
            "kline_tail": kline_tail,
        },
        "fundamentals": {
            "level": fund_d.get("level"),
            "forbid_buy": fund_d.get("forbid_buy"),
            "reasons": (fund_d.get("reasons") or [])[:5],
            "metrics": {
                k: (fund_d.get("metrics") or {}).get(k)
                for k in (
                    "report_name",
                    "revenue_yoy",
                    "netprofit_yoy",
                    "ocf_to_profit",
                    "gross_margin",
                )
            },
        },
        "announcements": ann.get("items") if not ann.get("error") else [],
        "missing": missing,
        "note": "事实底稿；买卖请调用 decide_code。规则信号不构成投资建议。",
    }
