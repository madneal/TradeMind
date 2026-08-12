"""强势扫描：同花顺热点池 → 强势分 → F0/F1 过滤。"""

from __future__ import annotations

from typing import Any


def scan_strong_market(
    *,
    universe_n: int = 40,
    min_score: int = 7,
    top_n: int = 15,
) -> dict[str, Any]:
    from data.research_market import ths_hot_reason
    from strategy.strong_score import score_strong_from_kline
    from strategy.fundamentals import evaluate_fundamentals, is_etf_or_fund
    from data.source import get_kline, get_quote

    hot = ths_hot_reason(top_n=universe_n + 20)
    if hot.get("error"):
        return {"error": hot["error"], "preferred": [], "rejected": []}

    stocks = hot.get("stocks") or []
    # index ret
    idx_ret20 = None
    try:
        idx = get_kline("000300", period="daily", days=90)
        if idx is not None and len(idx) >= 21:
            ic = idx["close"].astype(float)
            idx_ret20 = float(ic.iloc[-1] / ic.iloc[-21] - 1)
    except Exception:
        pass

    scored = []
    for s in stocks[:universe_n]:
        code = s.get("code")
        if not code:
            continue
        try:
            kdf = get_kline(code, period="daily", days=100)
        except Exception:
            kdf = None
        sc = score_strong_from_kline(
            kdf,
            idx_ret20=idx_ret20,
            day_pct=s.get("pct"),
            hot_boost=True,
        )
        scored.append({
            "code": code,
            "name": s.get("name"),
            "pct": s.get("pct"),
            "reason": s.get("reason"),
            **sc,
        })

    survivors = [r for r in scored if not r.get("veto") and r.get("score", 0) >= min_score]
    survivors.sort(key=lambda x: (-x.get("score", 0), -(x.get("pct") or 0)))

    preferred = []
    yellow = []
    rejected = []
    for r in survivors[: top_n + 8]:
        code = r["code"]
        if is_etf_or_fund(code):
            continue
        try:
            name = r.get("name") or get_quote(code).get("name") or ""
        except Exception:
            name = r.get("name") or ""
        try:
            fund = evaluate_fundamentals(code, name)
            fd = fund.to_dict()
        except Exception as e:
            fd = {"level": "unknown", "reasons": [str(e)], "forbid_buy": False}
        level = fd.get("level")
        item = {
            "code": code,
            "name": name,
            "score": r.get("score"),
            "label": r.get("label"),
            "pct": r.get("pct"),
            "reason": (r.get("reason") or "")[:80],
            "detail": r.get("detail"),
            "fund_level": level,
            "fund_reasons": (fd.get("reasons") or [])[:3],
        }
        if level == "red" or fd.get("forbid_buy"):
            item["discipline"] = "红灯剔除"
            rejected.append(item)
        elif level == "yellow":
            item["discipline"] = "黄灯观察"
            yellow.append(item)
        else:
            item["discipline"] = "F1通过/未知"
            preferred.append(item)

    return {
        "hot_date": hot.get("trade_date"),
        "themes": (hot.get("themes") or [])[:12],
        "universe": len(scored),
        "survivors": len(survivors),
        "preferred": preferred[:top_n],
        "watch_yellow": yellow[:10],
        "rejected_fund": rejected[:10],
        "disclaimer": "扫描结果不构成投资建议；开仓须走 buy 管道并写退出条件。",
    }
