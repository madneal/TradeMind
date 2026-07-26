"""A股数据源封装。

数据源选型：
- 历史K线：首选东财 stock_zh_a_hist（无 V8）；备选新浪 stock_zh_a_daily
  （新浪依赖 py_mini_racer，进程内串行，避免 macOS 并发 SIGTRAP）
- 实时行情：新浪 hq.sinajs.cn，失败降级到腾讯 qt.gtimg.cn，再降级到最近K线收盘价

统一处理 A 股代码归一化、缓存、重试。
"""

import re
import threading
import time
from datetime import datetime, timedelta

import akshare as ak
import pandas as pd
import requests

from data import cache

# 新浪日线依赖 py_mini_racer (V8)。多线程同时创建 Isolate 会在 macOS 上
# 触发 partition_alloc SIGTRAP，拖死整个进程。串行化新浪 K 线请求。
_sina_kline_lock = threading.Lock()


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
    """6 位代码转新浪/腾讯市场前缀。

    规则（常见 A 股 / 场内基金）：
    - 沪市股票：60/68/90 → sh
    - 深市股票：00/30/20 → sz
    - 北交所：43/83/87/92 → bj
    - 沪市 ETF/基金：51/56/58/50/52/11 等 → sh
    - 深市 ETF/基金：15/16/17/18/12 等 → sz  （此前缺 15 导致黄金股/恒生科技等取价失败）
    """
    code = normalize_code(code)
    if code.startswith(("60", "68", "90", "51", "56", "58", "50", "52", "11")):
        return f"sh{code}"
    if code.startswith(("00", "30", "20", "15", "16", "17", "18", "12")):
        return f"sz{code}"
    if code.startswith(("43", "83", "87", "92")):
        return f"bj{code}"
    # 兜底：5/6/9 开头偏沪，其余偏深
    if code[0] in ("5", "6", "9"):
        return f"sh{code}"
    return f"sz{code}"


def _kline_from_eastmoney(
    code: str, period: str, start: str, end: str, adjust: str
) -> pd.DataFrame | None:
    """东方财富历史 K 线（无 MiniRacer）。失败返回 None。"""
    try:
        df = _retry(
            ak.stock_zh_a_hist,
            symbol=code,
            period=period,
            start_date=start,
            end_date=end,
            adjust=adjust,
        )
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
        return df.rename(columns=rename)
    except Exception:
        return None


def _kline_from_sina(
    code: str, start: str, end: str, adjust: str
) -> pd.DataFrame | None:
    """新浪日线（内部 MiniRacer/V8）。必须串行调用。失败返回 None。"""
    try:
        sina_sym = _to_sina_symbol(code)
        with _sina_kline_lock:
            return _retry(
                ak.stock_zh_a_daily,
                symbol=sina_sym,
                start_date=start,
                end_date=end,
                adjust=adjust,
            )
    except Exception:
        return None


def get_kline(
    code: str, period: str = "daily", days: int = 60, adjust: str = "qfq"
) -> pd.DataFrame:
    """获取历史 K 线（OHLCV）。

    数据源策略（避免 macOS 上 py_mini_racer/V8 崩溃）：
    - 首选东方财富 stock_zh_a_hist（无 V8，可并行）
    - 备选新浪 stock_zh_a_daily（需 MiniRacer，进程内串行）

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
    start = (datetime.now() - timedelta(days=int(days * 1.6) + 30)).strftime("%Y%m%d")

    # 首选：东财（无 MiniRacer）
    df = _kline_from_eastmoney(code, period, start, end, adjust)

    # 备选：新浪日线（串行 MiniRacer）
    if df is None and period == "daily":
        df = _kline_from_sina(code, start, end, adjust)

    if df is None:
        if cached is not None and not cached.empty:
            return cached.tail(days).reset_index(drop=True)
        raise RuntimeError(f"无法获取 {code} 的历史K线（东财/新浪均不可达）")

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
        return _parse_sina_line(code, line)
    except Exception:
        return None


def _parse_sina_line(code: str, line: str) -> dict | None:
    """解析新浪单条行情字符串。"""
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


def get_quotes(codes: list[str]) -> list[dict]:
    """批量获取实时行情（单次请求新浪，逗号分隔多代码）。

    对个别失败的代码会降级到腾讯或 K 线，保证每只都有结果。
    """
    codes = [normalize_code(c) for c in codes]
    if not codes:
        return []

    results: dict[str, dict] = {}

    # 先查缓存
    for code in codes:
        cached = cache.get_quote_cache(code)
        if cached is not None:
            results[code] = cached

    missing = [c for c in codes if c not in results]
    if not missing:
        return [results[c] for c in codes]

    # 批量请求新浪（逗号分隔，一次搞定）
    sina_symbols = ",".join(_to_sina_symbol(c) for c in missing)
    try:
        resp = _retry(
            requests.get,
            f"https://hq.sinajs.cn/list={sina_symbols}",
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=15,
        )
        resp.encoding = "gbk"
        for line in resp.text.strip().split("\n"):
            line = line.strip()
            if not line or '=""' in line:
                continue
            # 从 var hq_str_sh600519="..." 中提取代码
            m2 = re.match(r"var hq_str_(\w+)=", line)
            if m2:
                raw_sym = m2.group(1).lower()
                code = re.sub(r"^(sh|sz|bj)", "", raw_sym)
                parsed = _parse_sina_line(code, line)
                if parsed and parsed.get("price") and parsed["price"] > 0:
                    results[code] = parsed
                    cache.set_quote_cache(code, parsed)
    except Exception:
        pass  # 降级到逐个请求

    # 对仍然缺失的逐个降级
    for code in missing:
        if code in results:
            continue
        for fetcher in (_fetch_sina_quote, _fetch_tencent_quote):
            data = fetcher(code)
            if data and data.get("price") and data["price"] > 0:
                results[code] = data
                cache.set_quote_cache(code, data)
                break
        else:
            # 最终降级：K 线收盘价
            try:
                df = get_kline(code, period="daily", days=1)
                if not df.empty:
                    r = df.iloc[-1]
                    results[code] = {
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
            except Exception:
                results[code] = {"code": code, "name": "", "price": None, "source": "failed"}

    return [results.get(c, {"code": c, "price": None, "source": "missing"}) for c in codes]


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
