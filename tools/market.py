"""行情工具：实时行情、历史 K 线。"""

from tools.registry import register


@register(
    name="get_quote",
    description="查询某只 A 股的实时行情快照，包括最新价、涨跌幅、成交量等。当用户问'现在多少钱''最新价''今天涨跌'时使用。",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "A 股股票代码，6 位数字，如 600519（贵州茅台）、000001（平安银行）",
            }
        },
        "required": ["code"],
    },
)
def get_quote(code: str) -> dict:
    from data.source import get_quote as _get_quote

    return _get_quote(code)


@register(
    name="get_kline",
    description="查询某只 A 股的历史 K 线数据（OHLCV 日线），用于看走势、算指标。当用户问'最近走势''K线''历史行情'时使用。",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "A 股股票代码，6 位数字",
            },
            "days": {
                "type": "integer",
                "description": "近 N 个交易日，默认 60",
                "default": 60,
            },
        },
        "required": ["code"],
    },
)
def get_kline(code: str, days: int = 60) -> dict:
    from data.source import get_kline as _get_kline

    df = _get_kline(code, period="daily", days=days)
    # 只返回关键字段，且转成易读格式；尾部数据最重要
    cols = ["date", "open", "close", "high", "low", "volume", "pct_change"]
    cols = [c for c in cols if c in df.columns]
    recent = df[cols].tail(min(20, len(df))).copy()
    recent["date"] = recent["date"].astype(str)
    return {
        "code": code,
        "total_days": len(df),
        "recent": recent.to_dict(orient="records"),
    }
