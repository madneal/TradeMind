"""历史回测：用日 K 验证技术面合成规则（S1–S5），严格避免未来函数。

方法：
1. 仅用截至当日的 K 线调用 _technical_bundle
2. 信号在 T 日收盘产生，默认 T+1 开盘成交（无开盘价则用 T+1 收盘）
3. 全仓多头 / 空仓（0–1），不融券
4. 计入单边手续费（默认万五）

说明：
- 本模块验证的是「技术买卖规则」是否有历史优势，不是证明未来有效
- F0/F1 财务、组合仓位纪律需另做事件/组合回测（见文档）
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from strategy.engine import _technical_bundle


@dataclass
class Trade:
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    ret: float
    bars: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BacktestResult:
    code: str
    name: str
    start: str
    end: str
    bars: int
    trades: int
    win_rate: float
    total_return: float
    buy_hold_return: float
    excess_return: float
    max_drawdown: float
    avg_trade_return: float
    exposure: float  # 持仓天数 / 总天数
    fee_bps: float
    trade_list: list[dict] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _load_ohlcv(code: str, days: int) -> tuple[pd.DataFrame, str]:
    """加载 OHLCV，优先项目 get_kline，失败则新浪。"""
    from data.source import get_kline, get_quote, normalize_code, _to_sina_symbol
    import requests

    code = normalize_code(code)
    name = ""
    try:
        q = get_quote(code)
        name = q.get("name") or ""
    except Exception:
        pass

    df = None
    try:
        # 多取一些做预热
        df = get_kline(code, period="daily", days=max(days + 80, 120))
    except Exception:
        df = None

    if df is None or df.empty:
        sym = _to_sina_symbol(code)
        url = (
            "https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
            f"CN_MarketData.getKLineData?symbol={sym}&scale=240&ma=no&datalen={max(days + 80, 120)}"
        )
        r = requests.get(
            url,
            timeout=20,
            headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"},
        )
        r.raise_for_status()
        raw = r.json()
        if not raw:
            raise RuntimeError(f"无法获取 {code} 历史 K 线")
        df = pd.DataFrame(raw)
        df = df.rename(columns={"day": "date"})
        for c in ("open", "high", "low", "close"):
            df[c] = df[c].astype(float)
        if "volume" in df.columns:
            df["volume"] = df["volume"].astype(float)

    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    # 只保留末尾 days+预热
    if len(df) > days + 60:
        df = df.iloc[-(days + 60) :].reset_index(drop=True)
    return df, name


def backtest_code(
    code: str,
    days: int = 250,
    fee_bps: float = 5.0,
    warmup: int = 60,
) -> BacktestResult:
    """单票回测技术面 S5 规则。

    Args:
        code: 6 位代码
        days: 参与统计的交易日大约数（含预热外的样本）
        fee_bps: 单边手续费（基点），买卖各收一次
        warmup: 预热 bar 数，此期间只算指标不交易
    """
    from data.source import normalize_code

    code = normalize_code(code)
    df, name = _load_ohlcv(code, days=days)
    if len(df) < warmup + 10:
        raise RuntimeError(f"{code} K 线过短：{len(df)} 根")

    fee = fee_bps / 10000.0
    position = 0  # 0 空仓 1 满仓
    cash = 1.0
    shares = 0.0
    entry_i = -1
    entry_px = 0.0
    trades: list[Trade] = []
    equity_rows: list[dict] = []
    peak = 1.0
    max_dd = 0.0
    hold_days = 0

    # 信号在 i 日产生，在 i+1 日执行
    for i in range(warmup, len(df) - 1):
        window = df.iloc[: i + 1]
        _, score, tech = _technical_bundle(window)
        # 执行价：次日 open，缺失则 close
        nxt = df.iloc[i + 1]
        exec_px = float(nxt["open"]) if pd.notna(nxt.get("open")) and float(nxt["open"]) > 0 else float(nxt["close"])
        exec_date = str(pd.Timestamp(nxt["date"]).date())

        # 当日收盘权益（用 i 日收盘 mark-to-market）
        mark = float(df.iloc[i]["close"])
        equity = cash + shares * mark
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0)
        if position == 1:
            hold_days += 1
        equity_rows.append({
            "date": str(pd.Timestamp(df.iloc[i]["date"]).date()),
            "equity": round(equity, 6),
            "position": position,
            "tech": tech,
            "score": score,
            "close": mark,
        })

        if position == 0 and tech == "买入":
            # 全仓买入
            cost = exec_px * (1 + fee)
            shares = cash / cost
            cash = 0.0
            position = 1
            entry_i = i + 1
            entry_px = exec_px
        elif position == 1 and tech == "卖出":
            proceeds = shares * exec_px * (1 - fee)
            ret = proceeds / 1.0 - 1.0  # 相对上次满仓起始权益近似：用 entry 算单笔
            trade_ret = (exec_px * (1 - fee)) / (entry_px * (1 + fee)) - 1.0
            trades.append(
                Trade(
                    entry_date=str(pd.Timestamp(df.iloc[entry_i]["date"]).date()),
                    exit_date=exec_date,
                    entry_price=round(entry_px, 4),
                    exit_price=round(exec_px, 4),
                    ret=round(trade_ret, 6),
                    bars=i + 1 - entry_i,
                )
            )
            cash = proceeds
            shares = 0.0
            position = 0
            entry_i = -1

    # 期末强平 mark
    last = df.iloc[-1]
    last_px = float(last["close"])
    if position == 1 and shares > 0:
        cash = shares * last_px * (1 - fee)
        trade_ret = (last_px * (1 - fee)) / (entry_px * (1 + fee)) - 1.0
        trades.append(
            Trade(
                entry_date=str(pd.Timestamp(df.iloc[entry_i]["date"]).date()),
                exit_date=str(pd.Timestamp(last["date"]).date()),
                entry_price=round(entry_px, 4),
                exit_price=round(last_px, 4),
                ret=round(trade_ret, 6),
                bars=len(df) - 1 - entry_i,
            )
        )
        shares = 0.0
        position = 0

    final_equity = cash
    # buy & hold：warmup 结束后次日买入持有到期末
    bh_entry = float(df.iloc[warmup]["open"] or df.iloc[warmup]["close"])
    if bh_entry <= 0:
        bh_entry = float(df.iloc[warmup]["close"])
    bh_exit = last_px
    bh_ret = (bh_exit * (1 - fee)) / (bh_entry * (1 + fee)) - 1.0

    rets = [t.ret for t in trades]
    wins = sum(1 for r in rets if r > 0)
    n_trades = len(trades)
    active_bars = max(len(df) - warmup - 1, 1)

    notes = [
        "信号：T 日收盘算 S1–S5；成交：T+1 开盘（无则收盘）",
        "仓位：空仓或满仓多头，无杠杆、无做空",
        f"手续费：单边 {fee_bps} bp",
        "本结果仅验证技术规则历史表现，不构成投资建议",
    ]

    return BacktestResult(
        code=code,
        name=name,
        start=str(pd.Timestamp(df.iloc[warmup]["date"]).date()),
        end=str(pd.Timestamp(last["date"]).date()),
        bars=active_bars,
        trades=n_trades,
        win_rate=round(wins / n_trades, 4) if n_trades else 0.0,
        total_return=round(final_equity - 1.0, 6),
        buy_hold_return=round(bh_ret, 6),
        excess_return=round((final_equity - 1.0) - bh_ret, 6),
        max_drawdown=round(max_dd, 6),
        avg_trade_return=round(float(np.mean(rets)), 6) if rets else 0.0,
        exposure=round(hold_days / active_bars, 4),
        fee_bps=fee_bps,
        trade_list=[t.to_dict() for t in trades[-20:]],  # 最近 20 笔
        equity_curve=equity_rows[-30:],  # 最近 30 日
        notes=notes,
    )


def backtest_portfolio_codes(
    codes: list[str],
    days: int = 250,
    fee_bps: float = 5.0,
) -> dict[str, Any]:
    """对多只代码分别回测，汇总排名（等权单票，非组合再平衡）。"""
    results = []
    errors = []
    for code in codes:
        try:
            r = backtest_code(code, days=days, fee_bps=fee_bps)
            results.append(r.to_dict())
        except Exception as e:
            errors.append({"code": code, "error": f"{type(e).__name__}: {e}"})

    results.sort(key=lambda x: x.get("excess_return") or -999, reverse=True)
    return {
        "count": len(results),
        "days": days,
        "fee_bps": fee_bps,
        "results": results,
        "errors": errors,
        "summary": {
            "avg_total_return": round(float(np.mean([r["total_return"] for r in results])), 6) if results else 0,
            "avg_buy_hold": round(float(np.mean([r["buy_hold_return"] for r in results])), 6) if results else 0,
            "avg_excess": round(float(np.mean([r["excess_return"] for r in results])), 6) if results else 0,
            "beat_buy_hold": sum(1 for r in results if r["excess_return"] > 0),
        },
        "disclaimer": "分票回测，非真实组合再平衡；规则信号不构成投资建议。",
    }
