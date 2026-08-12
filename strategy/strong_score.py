"""强势股量化打分（对齐 notes/knowledge/principles/strong-stock.md）。

满分约 10；≥7 视为强者候选。破 MA20 / 放量长阴一票否决。
"""

from __future__ import annotations

from typing import Any

import pandas as pd


def score_strong_from_kline(
    kdf: pd.DataFrame | None,
    *,
    idx_ret20: float | None = None,
    day_pct: float | None = None,
    hot_boost: bool = False,
) -> dict[str, Any]:
    """基于日 K 打分。返回 score / veto / parts / detail。"""
    out: dict[str, Any] = {
        "score": 0,
        "veto": [],
        "parts": {},
        "detail": {},
        "is_strong": False,
        "label": "非强者",
    }
    if kdf is None or len(kdf) < 60:
        out["veto"].append("K线不足60日")
        out["label"] = "否决"
        return out

    df = kdf.copy()
    for col in ("open", "high", "low", "close", "volume"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    c = df["close"]
    v = df["volume"] if "volume" in df.columns else df.get("vol")
    if v is None:
        out["veto"].append("无成交量")
        out["label"] = "否决"
        return out
    v = pd.to_numeric(v, errors="coerce")

    ma5 = c.rolling(5).mean()
    ma20 = c.rolling(20).mean()
    ma60 = c.rolling(60).mean()
    last = float(c.iloc[-1])
    m5, m20, m60 = float(ma5.iloc[-1]), float(ma20.iloc[-1]), float(ma60.iloc[-1])
    m20_prev = float(ma20.iloc[-5])
    high20 = float(c.iloc[-20:].max())
    pullback = (high20 - last) / high20 * 100 if high20 else 999.0
    ret20 = float(c.iloc[-1] / c.iloc[-21] - 1) if len(c) >= 21 else None

    if last < m20:
        out["veto"].append("破MA20")
        out["detail"] = {
            "last": last,
            "ma20": m20,
            "pullback_pct": round(pullback, 2),
            "ret20_pct": round(ret20 * 100, 2) if ret20 is not None else None,
        }
        out["label"] = "否决"
        return out

    # 近 5 日放量长阴
    for i in range(-5, 0):
        if abs(i - 1) >= len(c):
            continue
        day_ret = float(c.iloc[i] / c.iloc[i - 1] - 1)
        vol_ma5 = float(v.iloc[max(0, len(v) + i - 5) : len(v) + i].mean() or 1)
        if day_ret < -0.05 and float(v.iloc[i]) > 2 * max(vol_ma5, 1):
            out["veto"].append(f"近5日放量长阴({day_ret * 100:.1f}%)")
            out["detail"] = {
                "last": last,
                "ma20": m20,
                "pullback_pct": round(pullback, 2),
                "ret20_pct": round(ret20 * 100, 2) if ret20 is not None else None,
            }
            out["label"] = "否决"
            return out

    s = 0
    if last >= m20 and m20 > m20_prev:
        s += 1
        out["parts"]["ma20_up"] = 1
    if m5 > m20 > m60:
        s += 1
        out["parts"]["multi_ma"] = 1
    if pullback <= 10:
        s += 1
        out["parts"]["pullback_ok"] = 1

    if ret20 is not None and idx_ret20 is not None and idx_ret20 != 0:
        rs = ret20 / idx_ret20 if idx_ret20 > 0 else (2.0 if ret20 > 0 else 0.0)
        out["detail"]["rs_vs_index"] = round(rs, 2)
        if rs > 1.3 or (idx_ret20 <= 0 and ret20 > 0):
            s += 1
            out["parts"]["beat_index"] = 1
    if ret20 is not None and ret20 > 0.15:
        s += 1
        out["parts"]["strong_ret20"] = 1

    up_mask = c.diff() > 0
    last10 = slice(-10, None)
    up_vol = v.iloc[last10][up_mask.iloc[last10]].mean()
    dn_vol = v.iloc[last10][~up_mask.iloc[last10]].mean()
    if pd.notna(up_vol) and pd.notna(dn_vol) and dn_vol > 0 and up_vol > dn_vol:
        s += 1
        out["parts"]["up_vol"] = 1
    vol_ma5 = float(v.iloc[-6:-1].mean() or 1)
    for i in range(-1, -6, -1):
        if float(c.iloc[i]) > float(c.iloc[i - 1]):
            if float(v.iloc[i]) >= 1.5 * vol_ma5:
                s += 1
                out["parts"]["breakout_vol"] = 1
            break

    if hot_boost and day_pct is not None and day_pct >= 5:
        s = min(10, s + 1)
        out["parts"]["hot_leader"] = 1
    if day_pct is not None and day_pct >= 9.5:
        s = min(10, s + 1)
        out["parts"]["limit_leader"] = 1

    out["score"] = s
    out["detail"].update({
        "last": round(last, 3),
        "ma5": round(m5, 3),
        "ma20": round(m20, 3),
        "ma60": round(m60, 3),
        "pullback_pct": round(pullback, 2),
        "ret20_pct": round(ret20 * 100, 2) if ret20 is not None else None,
    })
    if s >= 8:
        out["label"] = "明确强者"
        out["is_strong"] = True
    elif s >= 7:
        out["label"] = "偏强"
        out["is_strong"] = True
    elif s >= 5:
        out["label"] = "一般"
    else:
        out["label"] = "非强者"
    return out


def score_code(code: str, *, days: int = 100, day_pct: float | None = None) -> dict[str, Any]:
    """拉 K 线并打分。"""
    from data.source import get_kline, normalize_code, get_quote

    code = normalize_code(code)
    idx_ret20 = None
    try:
        idx = get_kline("000300", period="daily", days=90)
        if idx is not None and len(idx) >= 21:
            ic = idx["close"].astype(float)
            idx_ret20 = float(ic.iloc[-1] / ic.iloc[-21] - 1)
    except Exception:
        idx_ret20 = None

    if day_pct is None:
        try:
            q = get_quote(code)
            day_pct = q.get("pct_change")
            if day_pct is not None:
                day_pct = float(day_pct)
        except Exception:
            day_pct = None

    try:
        kdf = get_kline(code, period="daily", days=days)
    except Exception as e:
        return {
            "code": code,
            "score": 0,
            "veto": [f"kline:{e}"],
            "parts": {},
            "detail": {},
            "is_strong": False,
            "label": "否决",
        }
    sc = score_strong_from_kline(kdf, idx_ret20=idx_ret20, day_pct=day_pct)
    sc["code"] = code
    return sc
