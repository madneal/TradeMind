"""A股数据源封装。

数据源选型（基于实测连通性）：
- 历史K线：新浪 (stock_zh_a_daily)，东方财富 push2his 端点在部分网络不可达
- 实时行情：新浪 hq.sinajs.cn，失败降级到腾讯 qt.gtimg.cn，再降级到最近K线收盘价

统一处理 A 股代码归一化、缓存、重试。
"""

import re
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import requests

from data import cache


def _retry(fn, *args, retries: int = 3, delay: float = 1.5, **kwargs):
    """请求偶发断连，做简单重试。"""
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
    code = re.sub(r"[\s.\-]", "", code.strip().lower())
    code = re.sub(r"^(sh|sz|bj)", "", code)
    code = re.sub(r"(sh|sz|bj)$", "", code)
    code = code.zfill(6)
    if not code.isdigit() or len(code) != 6:
        raise ValueError(f"无效的 A 股代码: {code}")
    return code


def _to_sina_symbol(code: str) -> str:
    """6 位代码转新浪格式：6 开头沪市 sh，0/3 开头深市 sz，8/4 北交所 bj。"""
    code = normalize_code(code)
    if code.startswith(("60", "68", "90")):
        return f"sh{code}"
    elif code.startswith(("00", "30", "20")):
        return f"sz{code}"
    elif code.startswith(("43", "83", "87", "92")):
        return f"bj{code}"
    # 默认按沪市处理
    return f"sh{code}"


def get_kline(
    code: str, period: str = "daily", days: int = 60, adjust: str = "qfq"
) -> pd.DataFrame:
    """获取历史 K 线（OHLCV）。

    使用新浪源 stock_zh_a_daily。

    Args:
        code: 股票代码（6 位）
        period: daily / weekly / monthly（新浪源仅日线直接支持，非日线回退到东财）
        days: 近 N 个交易日
        adjust: qfq 前复权 / hfq 后复权 / "" 不复权
    """
    code = normalize_code(code)
    cached = cache.get_kline_cache(code, period, adjust)
    if cached is not None and len(cached) >= days:
        return cached.tail(days).reset_index(drop=True)

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=int(days * 1.6) + 30)).strftime("%Y%m%d")

    df = None
    # 首选：新浪源
    if period == "daily":
        try:
            sina_sym = _to_sina_symbol(code)
            df = _retry(
                ak.stock_zh_a_daily,
                symbol=sina_sym, start_date=start, end_date=end, adjust=adjust,
            )
        except Exception:
            df = None

    # 备选：东方财富源
    if df is None:
        try:
            df = _retry(
                ak.stock_zh_a_hist,
                symbol=code, period=period, start_date=start, end_date=end, adjust=adjust,
            )
            # 东财列名是中文，统一成英文
            rename = {
                "日期": "date", "股票代码": "code", "开盘": "open", "收盘": "close",
                "最高": "high", "最低": "low", "成交量": "volume", "成交额": "amount",
                "振幅": "amplitude", "涨跌幅": "pct_change", "涨跌额": "change", "换手率": "turnover",
            }
            df = df.rename(columns=rename)
        except Exception:
            if cached is not None and not cached.empty:
                return cached.tail(days).reset_index(drop=True)
            raise RuntimeError(f"无法获取 {code} 的历史K线（新浪/东财均不可达）")

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    cache.set_kline_cache(code, period, adjust, df)
    return df.tail(days).reset_index(drop=True)


def _fetch_sina_quote(code: str) -> dict | None:
    """从新浪 hq.sinajs.cn 取实时行情。返回 dict 或 None。"""
    sina_sym = _to_sina_symbol(code)
    try:
        resp = _retry(
            requests.get,
            f"https://hq.sinajs.cn/list={sina_sym}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
        resp.encoding = "gbk"
        line = resp.text.strip()
        # 格式: var hq_str_sh600519="名称,昨收,今开,当前价,最高,最低,...";
        m = re.search(r'"(.+)"', line)
        if not m:
            return None
        fields = m.group(1).split(",")
        if len(fields) < 10:
            return None
        name = fields[0]
        prev_close = float(fields[2])
        open_p = float(fields[1])
        price = float(fields[3])
        high = float(fields[4])
        low = float(fields[5])
        volume = float(fields[8])
        amount = float(fields[9])
        pct_change = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
        change = round(price - prev_close, 2)
        return {
            "code": code, "name": name, "price": price, "open": open_p,
            "high": high, "low": low, "prev_close": prev_close,
            "volume": volume, "amount": amount,
            "pct_change": pct_change, "change": change,
            "source": "sina",
        }
    except Exception:
        return None


def _fetch_tencent_quote(code: str) -> dict | None:
    """从腾讯 qt.gtimg.cn 取实时行情。返回 dict 或 None。"""
    sina_sym = _to_sina_symbol(code)
    try:
        resp = _retry(
            requests.get,
            f"https://qt.gtimg.cn/q={sina_sym}",
            timeout=10,
        )
        resp.encoding = "gbk"
        line = resp.text.strip()
        # 格式: v_sh600519="1~名称~代码~当前价~昨收~今开~成交量~...";
        m = re.search(r'"(.+)"', line)
        if not m:
            return None
        fields = m.group(1).split("~")
        if len(fields) < 10:
            return None
        name = fields[1]
        price = float(fields[3])
        prev_close = float(fields[4])
        open_p = float(fields[5])
        volume = float(fields[6]) if fields[6] else 0
        amount = float(fields[37]) if len(fields) > 37 and fields[37] else 0
        high = float(fields[33]) if len(fields) > 33 and fields[33] else price
        low = float(fields[34]) if len(fields) > 34 and fields[34] else price
        pct_change = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
        change = round(price - prev_close, 2)
        return {
            "code": code, "name": name, "price": price, "open": open_p,
            "high": high, "low": low, "prev_close": prev_close,
            "volume": volume, "amount": amount,
            "pct_change": pct_change, "change": change,
            "source": "tencent",
        }
    except Exception:
        return None


def get_quote(code: str) -> dict:
    """获取实时行情快照。

    优先级：新浪 → 腾讯 → 最近K线收盘价降级。
    """
    code = normalize_code(code)

    cached = cache.get_quote_cache(code)
    if cached is not None:
        return cached

    # 依次尝试新浪、腾讯
    for fetcher in (_fetch_sina_quote, _fetch_tencent_quote):
        data = fetcher(code)
        if data is not None and data.get("price") and data["price"] > 0:
            cache.set_quote_cache(code, data)
            return data

    # 降级：取最近交易日 K 线收盘价
    try:
        df = get_kline(code, period="daily", days=1)
        if not df.empty:
            r = df.iloc[-1]
            data = {
                "code": code, "name": "", "price": float(r["close"]),
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
    except Exception:
        pass

    raise RuntimeError(f"无法获取 {code} 的行情数据（所有数据源均不可达）")
