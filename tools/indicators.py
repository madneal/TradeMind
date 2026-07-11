"""技术指标工具：MA / MACD / RSI / KDJ / BOLL。

依赖 pandas-ta，用缓存的 K 线数据计算。
"""

from tools.registry import register

# 支持的指标列表
SUPPORTED = ["MA", "MACD", "RSI", "KDJ", "BOLL"]


def _calc(df, indicators: list[str]) -> dict:
    """在 K 线 DataFrame 上计算指标，返回最近若干天的值。"""
    import pandas_ta as ta

    result = {}
    close = df["close"]
    high = df["high"]
    low = df["low"]

    for ind in indicators:
        ind_up = ind.upper()
        if ind_up == "MA":
            # 常用周期 5/10/20/60
            for p in (5, 10, 20, 60):
                if len(df) >= p:
                    result[f"MA{p}"] = round(float(close.rolling(p).mean().iloc[-1]), 3)
        elif ind_up == "MACD":
            macd = ta.macd(close, fast=12, slow=26, signal=9)
            if macd is not None and not macd.empty:
                last = macd.iloc[-1]
                result["MACD_DIF"] = round(float(last.iloc[0]), 4)
                result["MACD_DEA"] = round(float(last.iloc[1]), 4)
                result["MACD_HIST"] = round(float(last.iloc[2]), 4)
        elif ind_up == "RSI":
            for p in (6, 14):
                rsi = ta.rsi(close, length=p)
                if rsi is not None and not rsi.empty:
                    result[f"RSI{p}"] = round(float(rsi.iloc[-1]), 2)
        elif ind_up == "KDJ":
            stoch = ta.stoch(high, low, close, k=9, d=3, smooth_k=1, smooth_d=1)
            if stoch is not None and not stoch.empty:
                last = stoch.iloc[-1]
                result["KDJ_K"] = round(float(last.iloc[0]), 2)
                result["KDJ_D"] = round(float(last.iloc[1]), 2)
                result["KDJ_J"] = round(float(last.iloc[2]), 2)
        elif ind_up == "BOLL":
            bb = ta.bbands(close, length=20, std=2)
            if bb is not None and not bb.empty:
                last = bb.iloc[-1]
                result["BOLL_UPPER"] = round(float(last.iloc[0]), 3)
                result["BOLL_MID"] = round(float(last.iloc[1]), 3)
                result["BOLL_LOWER"] = round(float(last.iloc[2]), 3)
    return result


@register(
    name="calc_indicators",
    description="计算某只 A 股的技术指标（MA/MACD/RSI/KDJ/BOLL）。会先取历史 K 线再计算，返回最新指标值。当用户问'算一下MACD''技术指标''RSI多少'时使用。",
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": "A 股股票代码，6 位数字",
            },
            "indicators": {
                "type": "array",
                "items": {"type": "string", "enum": SUPPORTED},
                "description": "要计算的指标列表，如 ['MACD','RSI']",
            },
            "days": {
                "type": "integer",
                "description": "用于计算的 K 线天数，默认 60。算 MA60 至少需 60 天。",
                "default": 60,
            },
        },
        "required": ["code", "indicators"],
    },
)
def calc_indicators(code: str, indicators: list[str], days: int = 60) -> dict:
    from data.source import get_kline

    # 算 MA60 / BOLL20 需要足够数据
    needed = max(days, 60)
    df = get_kline(code, period="daily", days=needed)
    if df.empty:
        return {"error": f"未取到 {code} 的 K 线数据"}

    result = _calc(df, indicators)
    # 附带最新收盘价便于解读
    result["last_close"] = round(float(df["close"].iloc[-1]), 3)
    result["last_date"] = str(df["date"].iloc[-1].date()) if hasattr(df["date"].iloc[-1], "date") else str(df["date"].iloc[-1])
    return result
