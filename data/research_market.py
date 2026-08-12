"""A 股市场/研究数据（客观层，不给买卖结论）。

借鉴 Vibe-Research / a-stock-data：热点归因、板块资金、打板情绪、公告摘要。
失败返回 {error, missing}，禁止调用方臆测填空。
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

import requests

from data.em_http import UA, em_get

THS_UA = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "Chrome/117.0.0.0 Safari/537.36"
    )
}


def _as_of() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _ok(payload: dict, source: str, missing: list[str] | None = None) -> dict:
    out = {
        "as_of": _as_of(),
        "source": source,
        "missing": missing or [],
        **payload,
    }
    return out


def _err(msg: str, source: str = "") -> dict:
    return {
        "as_of": _as_of(),
        "source": source,
        "error": msg,
        "missing": ["data"],
    }


# ── 同花顺当日强势股 + 题材归因 ─────────────────────────────────────────


def ths_hot_reason(trade_date: str | None = None, top_n: int = 30) -> dict:
    """当日强势股 + 题材归因（同花顺公开接口）。trade_date=YYYY-MM-DD。"""
    d = trade_date or date.today().strftime("%Y-%m-%d")
    last_err = None
    rows: list[dict] = []
    used_date = d
    for i in range(0, 6):
        try_d = (date.today() - timedelta(days=i)).strftime("%Y-%m-%d") if trade_date is None else d
        if trade_date is not None and i > 0:
            break
        url = (
            f"http://zx.10jqka.com.cn/event/api/getharden/"
            f"date/{try_d}/orderby/date/orderway/desc/charset/GBK/"
        )
        try:
            r = requests.get(url, headers=THS_UA, timeout=12)
            data = r.json()
            if data.get("errocode", 0) != 0:
                last_err = data.get("errormsg") or "ths error"
                continue
            raw = data.get("data") or []
            if not raw:
                last_err = "empty"
                continue
            used_date = try_d
            for it in raw:
                code = str(it.get("code") or "").zfill(6)
                name = str(it.get("name") or "")
                if not code or "ST" in name.upper() or name.startswith("*"):
                    continue
                try:
                    pct = float(it.get("zhangfu") or 0)
                except (TypeError, ValueError):
                    pct = None
                rows.append({
                    "code": code,
                    "name": name,
                    "pct": pct,
                    "reason": str(it.get("reason") or "")[:120],
                    "turnover": _f(it.get("huanshou")),
                })
            break
        except Exception as e:
            last_err = f"{type(e).__name__}: {e}"
            if trade_date is not None:
                break
            continue

    if not rows:
        return _err(f"同花顺强势股不可用: {last_err}", "ths_hot")

    rows.sort(key=lambda x: (x.get("pct") is not None, x.get("pct") or -999), reverse=True)
    tags: list[str] = []
    for r in rows:
        for t in re.split(r"[+＋,，/、]", r.get("reason") or ""):
            t = t.strip()
            if t:
                tags.append(t)
    themes = [{"tag": k, "count": v} for k, v in Counter(tags).most_common(15)]
    return _ok(
        {
            "trade_date": used_date,
            "count": len(rows),
            "themes": themes,
            "stocks": rows[: max(1, min(top_n, 80))],
        },
        source="ths_hot_reason",
    )


def _f(x) -> float | None:
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


# ── 东财板块资金流向 ───────────────────────────────────────────────────


def board_fund_flow(
    board_type: str = "industry",
    period: str = "today",
    top_n: int = 15,
) -> dict:
    """板块主力净流入排名。board_type: industry|concept；period: today|5d|10d。"""
    fs_map = {"industry": "m:90+t:2", "concept": "m:90+t:3", "region": "m:90+t:1"}
    period_map = {
        "today": ("f62", "f62", "f184", "f3", "f204"),
        "5d": ("f164", "f164", "f165", "f109", "f257"),
        "10d": ("f174", "f174", "f175", "f160", None),
    }
    if board_type not in fs_map:
        return _err(f"board_type 须为 {list(fs_map)}", "eastmoney_board")
    if period not in period_map:
        return _err(f"period 须为 {list(period_map)}", "eastmoney_board")

    fid, f_main, f_pct, f_chg, f_leader = period_map[period]
    fields = ["f12", "f14", f_chg, f_main, f_pct]
    if f_leader:
        fields.append(f_leader)
    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "pn": "1",
        "pz": str(min(200, max(top_n, 50))),
        "po": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": fid,
        "fs": fs_map[board_type],
        "fields": ",".join(dict.fromkeys(fields)),
    }
    try:
        r = em_get(url, params=params, timeout=15)
        items = (r.json().get("data") or {}).get("diff") or []
    except Exception as e:
        return _err(f"板块资金请求失败: {type(e).__name__}: {e}", "eastmoney_board")

    if not items:
        return _err("板块资金为空（非交易时段或限流）", "eastmoney_board")

    rows = []
    for i, it in enumerate(items[:top_n]):
        main = it.get(f_main) or 0
        try:
            main_f = float(main)
        except (TypeError, ValueError):
            main_f = 0.0
        rows.append({
            "rank": i + 1,
            "name": it.get("f14") or "",
            "code": it.get("f12") or "",
            "change_pct": it.get(f_chg),
            "main_net_yi": round(main_f / 1e8, 2),
            "main_pct": it.get(f_pct),
            "leader": it.get(f_leader) if f_leader else "",
        })
    return _ok(
        {"board_type": board_type, "period": period, "rows": rows},
        source="eastmoney_board_fund",
    )


# ── 涨停情绪（东财四池摘要）────────────────────────────────────────────


def limit_up_sentiment(trade_date: str | None = None) -> dict:
    """涨停/炸板/跌停数量与炸板率。trade_date=YYYYMMDD。"""
    d = trade_date or date.today().strftime("%Y%m%d")
    ut = "7eea3edcaed734bea9cbfc24409ed989"

    def _pool(endpoint: str, sort: str) -> list:
        url = f"https://push2ex.eastmoney.com/{endpoint}"
        params = {
            "ut": ut,
            "dpt": "wz.ztzt",
            "Pageindex": 0,
            "pagesize": 10000,
            "sort": sort,
            "date": d,
        }
        try:
            r = em_get(url, params=params, timeout=12)
            return (r.json().get("data") or {}).get("pool") or []
        except Exception:
            return []

    # 若今日空，回退最近交易日（简单：往前最多 5 天）
    zt = zb = dt = []
    used = d
    for i in range(0, 6):
        dd = (date.today() - timedelta(days=i)).strftime("%Y%m%d") if trade_date is None else d
        if trade_date is not None and i > 0:
            break
        zt = _pool("getTopicZTPool", "fbt:asc")
        zb = _pool("getTopicZBPool", "fbt:asc")
        dt = _pool("getTopicDTPool", "fund:asc")
        if zt or zb or dt:
            used = dd
            break

    zt_n, zb_n, dt_n = len(zt), len(zb), len(dt)
    ladder: dict[int, int] = {}
    max_h = 0
    for p in zt:
        days = int(p.get("lbc") or 0)
        ladder[days] = ladder.get(days, 0) + 1
        max_h = max(max_h, days)
    break_rate = round(zb_n / (zt_n + zb_n) * 100, 1) if (zt_n + zb_n) else None
    # 连板代表（最多 8 只）
    leaders = []
    for p in sorted(zt, key=lambda x: int(x.get("lbc") or 0), reverse=True)[:8]:
        leaders.append({
            "code": p.get("c"),
            "name": p.get("n"),
            "limit_days": p.get("lbc"),
            "industry": p.get("hybk") or "",
        })

    if not zt and not zb and not dt:
        return _err("涨停池无数据（非交易日或未更新）", "eastmoney_zt")

    return _ok(
        {
            "trade_date": used,
            "zt_count": zt_n,
            "zb_count": zb_n,
            "dt_count": dt_n,
            "break_rate_pct": break_rate,
            "max_height": max_h,
            "ladder": dict(sorted(ladder.items())),
            "leaders": leaders,
        },
        source="eastmoney_zt_pool",
    )


# ── 个股公告摘要（东财）────────────────────────────────────────────────


def stock_announcements(code: str, page_size: int = 8) -> dict:
    """个股近期公告标题列表（东财 np-anotice）。"""
    code = re.sub(r"\D", "", code or "")[-6:].zfill(6)
    url = "https://np-anotice-stock.eastmoney.com/api/security/ann"
    params = {
        "sr": "-1",
        "page_size": str(page_size),
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "stock_list": code,
        "f_node": "0",
        "s_node": "0",
    }
    try:
        r = em_get(
            url,
            params=params,
            headers={"Referer": "https://data.eastmoney.com/"},
            timeout=15,
        )
        lst = (r.json().get("data") or {}).get("list") or []
    except Exception as e:
        return _err(f"公告请求失败: {type(e).__name__}: {e}", "eastmoney_ann")

    rows = []
    for a in lst[:page_size]:
        rows.append({
            "title": a.get("title") or "",
            "date": (a.get("notice_date") or "")[:10],
            "type": (a.get("columns") or [{}])[0].get("column_name", "")
            if isinstance(a.get("columns"), list) and a.get("columns")
            else "",
        })
    if not rows:
        return _err("无公告或代码无效", "eastmoney_ann")
    return _ok({"code": code, "items": rows}, source="eastmoney_ann")


# ── 指数快照（腾讯）────────────────────────────────────────────────────


def index_snapshot(codes: list[str] | None = None) -> dict:
    """主要指数实时快照。默认上证/深成/创业板/沪深300。"""
    from data.source import get_quotes

    # 用腾讯：sh000001 等 —— get_quotes 可能按个股路由；改直接腾讯
    default = [
        ("sh000001", "上证指数"),
        ("sz399001", "深证成指"),
        ("sz399006", "创业板指"),
        ("sh000300", "沪深300"),
    ]
    if codes:
        # 允许传 000001 等形式
        mapped = []
        for c in codes:
            c = c.lower()
            if c.startswith(("sh", "sz")):
                mapped.append((c, c))
            elif c in ("000001", "000300", "000016"):
                mapped.append((f"sh{c}", c))
            elif c.startswith("399"):
                mapped.append((f"sz{c}", c))
            else:
                mapped.append((f"sh{c}", c))
        pairs = mapped
    else:
        pairs = default

    q = ",".join(p[0] for p in pairs)
    url = f"https://qt.gtimg.cn/q={q}"
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=10)
        text = r.content.decode("gbk", errors="ignore")
    except Exception as e:
        return _err(f"指数行情失败: {type(e).__name__}: {e}", "tencent_index")

    name_map = {p[0]: p[1] for p in pairs}
    rows = []
    for line in text.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 33:
            continue
        try:
            price = float(vals[3]) if vals[3] else None
            pct = float(vals[32]) if vals[32] else None
        except ValueError:
            price, pct = None, None
        rows.append({
            "symbol": key,
            "name": name_map.get(key) or vals[1],
            "price": price,
            "pct_change": pct,
        })
    if not rows:
        return _err("指数解析为空", "tencent_index")
    return _ok({"indices": rows}, source="tencent_index")


# ── 持仓主题映射（复盘用）──────────────────────────────────────────────


def map_position_themes(positions_mv: list[dict[str, Any]]) -> dict[str, float]:
    """按代码粗分主题市值。positions_mv: [{code, market_value}, ...]。"""
    themes: dict[str, float] = {}

    def add(k: str, mv: float) -> None:
        themes[k] = themes.get(k, 0.0) + mv

    for p in positions_mv:
        c = str(p.get("code") or "").zfill(6)
        mv = float(p.get("market_value") or 0)
        if c in ("518880", "159562"):
            add("黄金", mv)
        elif c in ("002716", "601212", "600362", "002738"):
            add("有色/锂矿", mv)
        elif c in ("601166", "601288"):
            add("银行", mv)
        elif c in ("600418", "000559"):
            add("汽车", mv)
        elif c in ("588200", "688270"):
            add("芯片/电子", mv)
        elif c == "561360":
            add("石油", mv)
        elif c == "300274":
            add("电新", mv)
        elif c.startswith(("15", "51", "56", "58")):
            add("其它ETF", mv)
        else:
            add("其它个股", mv)
    return themes
