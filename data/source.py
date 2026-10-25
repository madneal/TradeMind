"""A股数据源封装。

数据源选型：
- 历史K线：首选 mootdx/通达信 TCP（快、不封 IP，对齐 a-stock-data）；
  备选东财 stock_zh_a_hist；再备选腾讯 fqkline（纯 HTTP 前复权）；
  新浪日线 JSON（纯 HTTP 不复权）；最后新浪 stock_zh_a_daily
  （依赖 py_mini_racer/V8，库在部分 macOS 上损坏，仅作兜底）
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

# mootdx 客户端：线程本地，避免多线程共用一个 TCP 连接
_mootdx_local = threading.local()
_mootdx_init_lock = threading.Lock()
_mootdx_available: bool | None = None  # None=未探测, True/False=结果

# mootdx frequency：9=日, 5=周, 6=月（与库内约定一致）
_MOOTDX_FREQ = {
    "daily": 9,
    "week": 5,
    "weekly": 5,
    "month": 6,
    "monthly": 6,
}


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


def _get_mootdx_client():
    """线程本地 Quotes 客户端；首次失败则全局标记不可用。"""
    global _mootdx_available
    if _mootdx_available is False:
        return None
    client = getattr(_mootdx_local, "client", None)
    if client is not None:
        return client
    with _mootdx_init_lock:
        if _mootdx_available is False:
            return None
        try:
            from mootdx.quotes import Quotes

            client = Quotes.factory(market="std")
            # 验活：必须能真实取到一根 K，避免空连接
            probe = client.bars(symbol="000001", frequency=9, offset=1)
            if probe is None or (hasattr(probe, "empty") and probe.empty):
                raise RuntimeError("mootdx probe empty")
            _mootdx_local.client = client
            _mootdx_available = True
            return client
        except Exception:
            _mootdx_available = False
            return None


def _normalize_kline_df(df: pd.DataFrame) -> pd.DataFrame:
    """统一为 date/open/high/low/close/volume[/amount]。"""
    out = df.copy()
    rename: dict[str, str] = {}
    cols_lower = {str(c).lower(): c for c in out.columns}
    for want, aliases in {
        "date": ("date", "datetime", "day", "日期"),
        "open": ("open", "开盘"),
        "high": ("high", "最高"),
        "low": ("low", "最低"),
        "close": ("close", "收盘"),
        "volume": ("volume", "vol", "成交量"),
        "amount": ("amount", "成交额"),
    }.items():
        if want in out.columns:
            continue
        for a in aliases:
            if a in out.columns:
                rename[a] = want
                break
            if a.lower() in cols_lower:
                rename[cols_lower[a.lower()]] = want
                break
    if rename:
        out = out.rename(columns=rename)
    if "date" not in out.columns:
        raise ValueError("K 线缺少 date 列")
    out["date"] = pd.to_datetime(out["date"])
    keep = [c for c in ("date", "open", "high", "low", "close", "volume", "amount") if c in out.columns]
    out = out[keep].sort_values("date").reset_index(drop=True)
    for c in ("open", "high", "low", "close", "volume", "amount"):
        if c in out.columns:
            out[c] = pd.to_numeric(out[c], errors="coerce")
    return out


def _kline_from_mootdx(code: str, period: str, days: int) -> pd.DataFrame | None:
    """通达信 TCP 日/周/月 K 线。失败返回 None。

    注意：mootdx 返回的是不复权行情；短中期技术指标可用。
    需要精确前复权时，若本源失败会落到东财 qfq。
    """
    freq = _MOOTDX_FREQ.get(period)
    if freq is None:
        return None
    client = _get_mootdx_client()
    if client is None:
        return None
    # 多取一些，过滤后仍够 days；通达信 offset 上限约 800
    offset = min(max(int(days) + 30, 30), 800)
    try:
        raw = client.bars(symbol=code, frequency=freq, offset=offset)
        if raw is None or (hasattr(raw, "empty") and raw.empty):
            return None
        if not isinstance(raw, pd.DataFrame):
            raw = pd.DataFrame(raw)
        return _normalize_kline_df(raw)
    except Exception:
        return None


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


# 腾讯 fqkline 周期映射
_TENCENT_PERIOD = {"daily": "day", "week": "week", "weekly": "week", "month": "month", "monthly": "month"}


def _kline_from_tencent_http(
    code: str, period: str, days: int, adjust: str
) -> pd.DataFrame | None:
    """腾讯前复权日线（纯 HTTP JSON，不依赖 MiniRacer）。

    web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=sh600519,day,,,320,qfq
    返回 data.sh600519.qfqday = [[date, open, close, high, low, volume], ...]
    注意字段顺序：close 在 high/low 之前。
    失败返回 None。
    """
    tperiod = _TENCENT_PERIOD.get(period)
    if tperiod is None:
        return None
    sym = _to_sina_symbol(code)
    # 多取 1.6 倍自然日覆盖节假日，再按交易日截断
    count = min(int(days * 1.8) + 30, 640)
    fq = {"qfq": "qfq", "hfq": "hfq"}.get(adjust, "")
    param = f"{sym},{tperiod},,,{count},{fq}".rstrip(",")
    url = f"https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={param}"
    try:
        resp = _retry(requests.get, url, timeout=10)
        data = resp.json()
        node = data.get("data", {}).get(sym, {})
        rows = node.get(f"{fq}day" if fq else "day")
        if not rows:
            return None
        # 兼容少数返回里每行末尾多带一个 dict 附注的情况
        records = []
        for r in rows:
            if len(r) < 6:
                continue
            records.append(
                {
                    "date": r[0],
                    "open": float(r[1]),
                    "close": float(r[2]),
                    "high": float(r[3]),
                    "low": float(r[4]),
                    "volume": float(r[5]),
                }
            )
        if not records:
            return None
        return pd.DataFrame(records)
    except Exception:
        return None


def _kline_from_sina_http(code: str, days: int) -> pd.DataFrame | None:
    """新浪日线 JSON（纯 HTTP，不复权，不依赖 MiniRacer）。仅日线。失败返回 None。

    quotes.sina.cn/cn/api/jsonp_v2.php/.../CN_MarketDataService.getKLineData
    返回 var _=([{day,open,high,low,close,volume}, ...])
    """
    sym = _to_sina_symbol(code)
    count = min(int(days * 1.8) + 30, 1023)
    url = (
        "https://quotes.sina.cn/cn/api/jsonp_v2.php/var%20_=/CN_MarketDataService.getKLineData"
        f"?symbol={sym}&scale=240&ma=no&datalen={count}"
    )
    try:
        resp = _retry(
            requests.get,
            url,
            headers={"Referer": "https://finance.sina.com.cn"},
            timeout=10,
        )
        m = re.search(r"\((\[.*\])\)", resp.text, flags=re.S)
        if not m:
            return None
        import json as _json

        rows = _json.loads(m.group(1))
        records = [
            {
                "date": r["day"],
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]),
            }
            for r in rows
            if all(k in r for k in ("day", "open", "high", "low", "close", "volume"))
        ]
        if not records:
            return None
        return pd.DataFrame(records)
    except Exception:
        return None


def get_kline(
    code: str, period: str = "daily", days: int = 60, adjust: str = "qfq"
) -> pd.DataFrame:
    """获取历史 K 线（OHLCV）。

    数据源策略（速度优先，对齐 a-stock-data）：
    1. 本地 SQLite 缓存
    2. mootdx / 通达信 TCP（首选，快且不封 IP，可并行）
    3. 东财 stock_zh_a_hist（前复权更完整时作补充）
    4. 新浪 stock_zh_a_daily（MiniRacer，进程内串行）

    Args:
        code: 股票代码（6 位）
        period: daily / weekly / monthly
        days: 近 N 个交易日
        adjust: qfq 前复权 / hfq 后复权 / "" 不复权
            （mootdx 路径为不复权；东财/新浪尊重该参数）
    """
    code = normalize_code(code)
    cached = cache.get_kline_cache(code, period, adjust)
    if cached is not None and len(cached) >= days:
        return cached.tail(days).reset_index(drop=True)

    end = datetime.now().strftime("%Y%m%d")
    start = (datetime.now() - timedelta(days=int(days * 1.6) + 30)).strftime("%Y%m%d")

    df: pd.DataFrame | None = None

    # 1) mootdx 通达信（日/周/月）
    df = _kline_from_mootdx(code, period, days)

    # 2) 东财（无 MiniRacer；可取前复权）
    if df is None or len(df) < min(days, 5):
        em = _kline_from_eastmoney(code, period, start, end, adjust)
        if em is not None and not em.empty:
            df = em

    # 3) 腾讯 fqkline（纯 HTTP，前/后复权，无 MiniRacer 依赖）
    if df is None or len(df) < min(days, 5):
        tx = _kline_from_tencent_http(code, period, days, adjust)
        if tx is not None and not tx.empty:
            df = tx

    # 4) 新浪日线 JSON（纯 HTTP，不复权，无 MiniRacer 依赖）
    if (df is None or len(df) < min(days, 5)) and period == "daily":
        sh = _kline_from_sina_http(code, days)
        if sh is not None and not sh.empty:
            df = sh

    # 5) 新浪日线（串行 MiniRacer；库损坏时为死路径，留作兜底）
    if (df is None or len(df) < min(days, 5)) and period == "daily":
        sina = _kline_from_sina(code, start, end, adjust)
        if sina is not None and not sina.empty:
            df = sina

    if df is None or (hasattr(df, "empty") and df.empty):
        if cached is not None and not cached.empty:
            return cached.tail(days).reset_index(drop=True)
        raise RuntimeError(
            f"无法获取 {code} 的历史K线（mootdx/东财/新浪均不可达）"
        )

    df = df.copy()
    if "date" not in df.columns:
        df = _normalize_kline_df(df)
    else:
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
