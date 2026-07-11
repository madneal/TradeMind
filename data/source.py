"""AKShare 数据源封装。

统一处理 A 股代码归一化、历史 K 线取数、实时行情（带降级）。
"""

import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd

from data import cache


def _retry(fn, *args, retries: int = 3, delay: float = 1.5, **kwargs):
    """AKShare 请求偶发断连，做简单重试。"""
    last_err = None
    for i in range(retries):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_err = e
            if i < retries - 1:
                time.sleep(delay)
    raise last_err  # type: ignore[misc]


def normalize_code(code: str) -> str:
    """归一化 A 股代码：接受 '600519' / 'sh600519' / '600519.SH' 等，返回 6 位代码。"""
    import re

    code = re.sub(r"[\s.\-]", "", code.strip().lower())
    code = re.sub(r"^(sh|sz|bj)", "", code)
    code = re.sub(r"(sh|sz|bj)$", "", code)
    code = code.zfill(6)
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"无效的 A 股代码: {code}")
    return code


def get_kline(
    code: str, period: str = "daily", days: int = 60, adjust: str = "qfq"
) -> pd.DataFrame:
    """获取历史 K 线。

    Args:
        code: 股票代码（6 位）
        period: daily / weekly / monthly
        days: 近 N 个交易日
        adjust: qfq 前复权 / hfq 后复权 / "" 不复权
    """
    code = normalize_code(code)
    cached = cache.get_kline_cache(code, period, adjust)
    if cached is not None and len(cached) >= days:
        return cached.tail(days).reset_index(drop=True)

    end = datetime.now().strftime("%Y%m%d")
    # 多取一些天数以保证有足够交易日（周末/节假日）
    start = (datetime.now() - timedelta(days=int(days * 1.6) + 30)).strftime("%Y%m%d")

    try:
        df = _retry(
            ak.stock_zh_a_hist,
            symbol=code, period=period, start_date=start, end_date=end, adjust=adjust,
        )
    except Exception:
        # 网络失败：有缓存就降级用缓存（即使天数不足），否则向上抛
        if cached is not None and not cached.empty:
            return cached.tail(days).reset_index(drop=True)
        raise

    # 统一列名为英文，便于下游处理
    rename = {
        "日期": "date",
        "股票代码": "code",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_change",
        "涨跌额": "change",
        "换手率": "turnover",
    }
    df = df.rename(columns=rename)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    cache.set_kline_cache(code, period, adjust, df)
    return df.tail(days).reset_index(drop=True)


def get_quote(code: str) -> dict:
    """获取实时行情快照。

    优先用实时接口；不可用时降级为最近交易日 K 线的收盘价。
    """
    code = normalize_code(code)

    cached = cache.get_quote_cache(code)
    if cached is not None:
        return cached

    # 尝试实时行情接口
    try:
        df = _retry(ak.stock_zh_a_spot_em)
        row = df[df["代码"] == code]
        if not row.empty:
            r = row.iloc[0]
            data = {
                "code": code,
                "name": str(r.get("名称", "")),
                "price": float(r.get("最新价", 0)) if pd.notna(r.get("最新价")) else None,
                "pct_change": float(r.get("涨跌幅", 0)) if pd.notna(r.get("涨跌幅")) else None,
                "change": float(r.get("涨跌额", 0)) if pd.notna(r.get("涨跌额")) else None,
                "volume": float(r.get("成交量", 0)) if pd.notna(r.get("成交量")) else None,
                "amount": float(r.get("成交额", 0)) if pd.notna(r.get("成交额")) else None,
                "high": float(r.get("最高", 0)) if pd.notna(r.get("最高")) else None,
                "low": float(r.get("最低", 0)) if pd.notna(r.get("最低")) else None,
                "open": float(r.get("开盘", 0)) if pd.notna(r.get("开盘")) else None,
                "source": "realtime",
            }
            cache.set_quote_cache(code, data)
            return data
    except Exception:
        pass  # 降级

    # 降级：取最近一个交易日 K 线
    df = get_kline(code, period="daily", days=1)
    if df.empty:
        raise RuntimeError(f"无法获取 {code} 的行情数据")
    r = df.iloc[-1]
    data = {
        "code": code,
        "name": "",
        "price": float(r["close"]),
        "pct_change": float(r.get("pct_change", 0)) if pd.notna(r.get("pct_change")) else None,
        "change": float(r.get("change", 0)) if pd.notna(r.get("change")) else None,
        "volume": float(r.get("volume", 0)) if pd.notna(r.get("volume")) else None,
        "amount": float(r.get("amount", 0)) if pd.notna(r.get("amount")) else None,
        "high": float(r.get("high", 0)) if pd.notna(r.get("high")) else None,
        "low": float(r.get("low", 0)) if pd.notna(r.get("low")) else None,
        "open": float(r.get("open", 0)) if pd.notna(r.get("open")) else None,
        "date": str(pd.Timestamp(r["date"]).date()),
        "source": "kline_fallback",
    }
    cache.set_quote_cache(code, data)
    return data
