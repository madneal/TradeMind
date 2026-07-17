"""策略引擎：对单票 / 全持仓输出固定规则下的买卖决策。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd
import pandas_ta as ta

from strategy.rules import (
    BOLL_TOUCH_RATIO,
    DEEP_LOSS_PCT,
    GOLD_THEME_CODES,
    GOLD_THEME_NAME_KEYWORDS,
    HARD_SINGLE_WEIGHT,
    MAX_SINGLE_WEIGHT,
    MAX_THEME_WEIGHT,
    NO_LOSS_EXIT,
    RSI_OVERBOUGHT,
    RSI_OVERSOLD,
    ST_DAY_DROP,
    ST_MAX_WEIGHT,
    STRATEGY_CATALOG,
    TECH_BUY_SCORE,
    TECH_SELL_SCORE,
)

Action = Literal["买入", "卖出", "观望", "减仓", "加仓", "禁止买入"]


@dataclass
class RuleSignal:
    strategy_id: str
    name: str
    action: Action
    score: int  # +1 买, -1 卖, 0 中性
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Decision:
    code: str
    name: str
    price: float | None
    action: Action
    confidence: str  # 高 / 中 / 低
    tech_score: int
    reasons: list[str] = field(default_factory=list)
    rule_signals: list[dict] = field(default_factory=list)
    execution: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _vote(action: Action) -> int:
    if action in ("买入", "加仓"):
        return 1
    if action in ("卖出", "减仓", "禁止买入"):
        return -1
    return 0


def _is_st(name: str, code: str = "") -> bool:
    """名称含 ST/*ST 即视为 ST（不按科创板代码误判）。"""
    n = (name or "").replace(" ", "")
    return "ST" in n.upper() or n.startswith("*ST")


def _is_gold_theme(code: str, name: str, industry: str = "") -> bool:
    if code in GOLD_THEME_CODES:
        return True
    text = f"{name}{industry}"
    return any(k in text for k in GOLD_THEME_NAME_KEYWORDS)


def _ma_signal(close: pd.Series) -> RuleSignal:
    if len(close) < 20:
        return RuleSignal("S1_MA_TREND", "均线趋势", "观望", 0, "K 线不足 20 日，跳过均线")
    ma5 = float(close.rolling(5).mean().iloc[-1])
    ma10 = float(close.rolling(10).mean().iloc[-1])
    ma20 = float(close.rolling(20).mean().iloc[-1])
    px = float(close.iloc[-1])
    if ma5 > ma10 > ma20 and px > ma20:
        return RuleSignal(
            "S1_MA_TREND", "均线趋势", "买入", 1,
            f"多头排列 MA5={ma5:.3f}>MA10={ma10:.3f}>MA20={ma20:.3f}，价{px:.3f}>MA20",
        )
    if ma5 < ma10 < ma20 and px < ma20:
        return RuleSignal(
            "S1_MA_TREND", "均线趋势", "卖出", -1,
            f"空头排列 MA5={ma5:.3f}<MA10={ma10:.3f}<MA20={ma20:.3f}，价{px:.3f}<MA20",
        )
    return RuleSignal(
        "S1_MA_TREND", "均线趋势", "观望", 0,
        f"均线未形成明确排列 MA5={ma5:.3f}/MA10={ma10:.3f}/MA20={ma20:.3f}",
    )


def _macd_signal(close: pd.Series) -> RuleSignal:
    if len(close) < 35:
        return RuleSignal("S2_MACD", "MACD 动能", "观望", 0, "K 线不足，跳过 MACD")
    macd = ta.macd(close, fast=12, slow=26, signal=9)
    if macd is None or macd.empty:
        return RuleSignal("S2_MACD", "MACD 动能", "观望", 0, "MACD 计算失败")
    dif = float(macd.iloc[-1, 0])
    dea = float(macd.iloc[-1, 1])
    hist = float(macd.iloc[-1, 2])
    if dif > dea and hist > 0:
        return RuleSignal(
            "S2_MACD", "MACD 动能", "买入", 1,
            f"多头动能 DIF={dif:.4f}>DEA={dea:.4f}，HIST={hist:.4f}>0",
        )
    if dif < dea and hist < 0:
        return RuleSignal(
            "S2_MACD", "MACD 动能", "卖出", -1,
            f"空头动能 DIF={dif:.4f}<DEA={dea:.4f}，HIST={hist:.4f}<0",
        )
    return RuleSignal(
        "S2_MACD", "MACD 动能", "观望", 0,
        f"动能不明确 DIF={dif:.4f}/DEA={dea:.4f}/HIST={hist:.4f}",
    )


def _rsi_signal(close: pd.Series) -> RuleSignal:
    if len(close) < 20:
        return RuleSignal("S3_RSI", "RSI 超买超卖", "观望", 0, "K 线不足，跳过 RSI")
    rsi_s = ta.rsi(close, length=14)
    if rsi_s is None or rsi_s.empty or pd.isna(rsi_s.iloc[-1]):
        return RuleSignal("S3_RSI", "RSI 超买超卖", "观望", 0, "RSI 计算失败")
    rsi = float(rsi_s.iloc[-1])
    if rsi < RSI_OVERSOLD:
        return RuleSignal(
            "S3_RSI", "RSI 超买超卖", "买入", 1,
            f"RSI14={rsi:.1f}<{RSI_OVERSOLD:.0f} 超卖区",
        )
    if rsi > RSI_OVERBOUGHT:
        return RuleSignal(
            "S3_RSI", "RSI 超买超卖", "卖出", -1,
            f"RSI14={rsi:.1f}>{RSI_OVERBOUGHT:.0f} 超买区",
        )
    return RuleSignal(
        "S3_RSI", "RSI 超买超卖", "观望", 0,
        f"RSI14={rsi:.1f} 中性区",
    )


def _boll_signal(close: pd.Series) -> RuleSignal:
    if len(close) < 25:
        return RuleSignal("S4_BOLL", "布林带位置", "观望", 0, "K 线不足，跳过 BOLL")
    bb = ta.bbands(close, length=20, std=2)
    if bb is None or bb.empty:
        return RuleSignal("S4_BOLL", "布林带位置", "观望", 0, "BOLL 计算失败")
    # pandas-ta: BBL, BBM, BBU
    lower = float(bb.iloc[-1, 0])
    mid = float(bb.iloc[-1, 1])
    upper = float(bb.iloc[-1, 2])
    px = float(close.iloc[-1])
    width = upper - lower
    if width <= 0:
        return RuleSignal("S4_BOLL", "布林带位置", "观望", 0, "布林带宽度为 0")
    dist_low = (px - lower) / width
    dist_up = (upper - px) / width
    if dist_low <= BOLL_TOUCH_RATIO:
        return RuleSignal(
            "S4_BOLL", "布林带位置", "买入", 1,
            f"价格{px:.3f}贴近下轨{lower:.3f}（距下轨比例{dist_low:.2f}）",
        )
    if dist_up <= BOLL_TOUCH_RATIO:
        return RuleSignal(
            "S4_BOLL", "布林带位置", "卖出", -1,
            f"价格{px:.3f}贴近上轨{upper:.3f}（距上轨比例{dist_up:.2f}）",
        )
    return RuleSignal(
        "S4_BOLL", "布林带位置", "观望", 0,
        f"价格{px:.3f}在中轨附近 mid={mid:.3f}",
    )


def _technical_bundle(df: pd.DataFrame) -> tuple[list[RuleSignal], int, Action]:
    close = df["close"]
    signals = [
        _ma_signal(close),
        _macd_signal(close),
        _rsi_signal(close),
        _boll_signal(close),
    ]
    score = sum(s.score for s in signals)
    if score >= TECH_BUY_SCORE:
        action: Action = "买入"
    elif score <= TECH_SELL_SCORE:
        action = "卖出"
    else:
        action = "观望"
    signals.append(
        RuleSignal(
            "S5_COMPOSITE",
            "技术面合成",
            action,
            _vote(action),
            f"S1~S4 净分={score}（买入阈值≥{TECH_BUY_SCORE}，卖出阈值≤{TECH_SELL_SCORE}）→ {action}",
        )
    )
    return signals, score, action


def evaluate_code(
    code: str,
    *,
    held: bool = False,
    shares: int = 0,
    cost_price: float = 0.0,
    weight_pct: float = 0.0,
    pnl_pct: float | None = None,
    pct_change: float | None = None,
    name: str = "",
    industry: str = "",
    gold_theme_weight: float = 0.0,
    days: int = 90,
    quote: dict[str, Any] | None = None,
    kline_df: pd.DataFrame | None = None,
) -> Decision:
    """对单只代码做固定策略评估。

    quote / kline_df 可预先传入，避免组合评估时重复网络请求。
    """
    from data.source import get_kline, get_quote, normalize_code

    code = normalize_code(code)
    if quote is None:
        try:
            quote = get_quote(code)
        except Exception:
            quote = {}
    name = name or (quote.get("name") if quote else "") or ""
    price = quote.get("price") if quote else None
    if pct_change is None and quote:
        pct_change = quote.get("pct_change")

    if kline_df is not None:
        df = kline_df
    else:
        try:
            df = get_kline(code, period="daily", days=days)
        except Exception as e:
            return Decision(
                code=code,
                name=name,
                price=price,
                action="观望",
                confidence="低",
                tech_score=0,
                reasons=[f"无法获取 K 线：{e}"],
                context={"error": str(e)},
            )

    if df is None or df.empty:
        return Decision(
            code=code, name=name, price=price, action="观望",
            confidence="低", tech_score=0, reasons=["K 线为空"],
        )

    if price is None or not price:
        price = float(df["close"].iloc[-1])

    tech_signals, tech_score, tech_action = _technical_bundle(df)
    rule_signals = list(tech_signals)
    reasons: list[str] = [s.reason for s in tech_signals if s.strategy_id == "S5_COMPOSITE"]

    # ── F0 / F1 经营业绩与合规过滤 ──
    from strategy.fundamentals import evaluate_fundamentals

    fund = evaluate_fundamentals(code, name)
    fund_level = fund.level
    if fund.skip:
        rule_signals.append(
            RuleSignal("F0_COMPLIANCE", "合规与警示", "观望", 0, fund.reasons[0] if fund.reasons else "跳过")
        )
        rule_signals.append(
            RuleSignal("F1_QUALITY", "业绩质量过滤", "观望", 0, "ETF/基金跳过业绩质量层")
        )
    else:
        f0_action: Action = "禁止买入" if fund.forbid_buy and fund_level == "red" else "观望"
        # 拆分展示：ST/退市进 F0，质量进 F1
        f0_reasons = [r for r in fund.reasons if r.startswith("F0")]
        f1_reasons = [r for r in fund.reasons if r.startswith("F1") or not r.startswith("F0")]
        if not f0_reasons and not fund.skip:
            f0_reasons = ["F0：未见退市类名称警示"]
        rule_signals.append(
            RuleSignal(
                "F0_COMPLIANCE",
                "合规与警示",
                "禁止买入" if any("ST" in r or "退" in r for r in fund.reasons) else "观望",
                -1 if any("ST" in r or "退" in r for r in fund.reasons) else 0,
                "；".join(f0_reasons),
            )
        )
        f1_act: Action = "禁止买入" if fund.forbid_buy else "观望"
        if fund_level == "pass":
            f1_act = "观望"
        rule_signals.append(
            RuleSignal(
                "F1_QUALITY",
                "业绩质量过滤",
                f1_act,
                -1 if fund.forbid_buy else 0,
                "；".join(f1_reasons) if f1_reasons else "F1：无额外质量问题",
            )
        )
        for r in fund.reasons:
            if r not in reasons:
                reasons.append(r)

    # ── 持仓纪律 ──
    force_reduce = False
    forbid_buy = bool(fund.forbid_buy)
    is_st = _is_st(name, code) or "ST" in (name or "")

    # P2 ST
    if is_st or "ST" in (name or ""):
        st_reasons = []
        if held and weight_pct > ST_MAX_WEIGHT:
            force_reduce = True
            st_reasons.append(f"ST 仓位 {weight_pct:.1f}% > {ST_MAX_WEIGHT}%")
        if pct_change is not None and pct_change <= ST_DAY_DROP:
            force_reduce = True
            st_reasons.append(f"ST 单日跌幅 {pct_change}% ≤ {ST_DAY_DROP}%")
        forbid_buy = True
        action_st: Action = "减仓" if force_reduce else "禁止买入"
        rule_signals.append(
            RuleSignal(
                "P2_ST", "ST 纪律", action_st, -1 if force_reduce else 0,
                "；".join(st_reasons) if st_reasons else "ST/高风险标的：禁止加仓",
            )
        )
        reasons.append(rule_signals[-1].reason)

    # P1 weight
    if held and weight_pct >= HARD_SINGLE_WEIGHT:
        force_reduce = True
        rule_signals.append(
            RuleSignal(
                "P1_WEIGHT", "单票仓位纪律", "减仓", -1,
                f"仓位 {weight_pct:.1f}% ≥ 硬上限 {HARD_SINGLE_WEIGHT}% → 强烈减仓",
            )
        )
        reasons.append(rule_signals[-1].reason)
    elif held and weight_pct >= MAX_SINGLE_WEIGHT:
        force_reduce = True
        rule_signals.append(
            RuleSignal(
                "P1_WEIGHT", "单票仓位纪律", "减仓", -1,
                f"仓位 {weight_pct:.1f}% ≥ {MAX_SINGLE_WEIGHT}% → 建议减仓",
            )
        )
        reasons.append(rule_signals[-1].reason)
    else:
        rule_signals.append(
            RuleSignal(
                "P1_WEIGHT", "单票仓位纪律", "观望", 0,
                f"仓位 {weight_pct:.1f}%（上限 {MAX_SINGLE_WEIGHT}%）",
            )
        )

    # P3 deep loss
    if held and pnl_pct is not None and pnl_pct <= DEEP_LOSS_PCT:
        forbid_buy = True
        rule_signals.append(
            RuleSignal(
                "P3_DEEP_LOSS", "深套纪律", "减仓", -1,
                f"浮亏 {pnl_pct:.1f}% ≤ {DEEP_LOSS_PCT}% → 禁止摊薄，仅允许反弹减仓",
            )
        )
        reasons.append(rule_signals[-1].reason)

    # P4 gold theme
    if _is_gold_theme(code, name, industry) and gold_theme_weight >= MAX_THEME_WEIGHT:
        forbid_buy = True
        rule_signals.append(
            RuleSignal(
                "P4_THEME", "主题集中度（黄金链）", "禁止买入", -1,
                f"黄金相关主题合计 {gold_theme_weight:.1f}% ≥ {MAX_THEME_WEIGHT}% → 停止加仓",
            )
        )
        reasons.append(rule_signals[-1].reason)

    if held and cost_price and price:
        cost_val = cost_price * shares
        mkt_val = float(price) * shares
        if pnl_pct is None and cost_val:
            pnl_pct = (mkt_val - cost_val) / cost_val * 100

    # 是否浮亏（成本纪律用）
    underwater = False
    if held:
        if pnl_pct is not None:
            underwater = pnl_pct < 0
        elif price is not None and cost_price and cost_price > 0:
            underwater = float(price) < float(cost_price)

    # 基本面破坏：允许在浮亏中破例卖出
    fundamental_break = bool(is_st) or fund_level == "red"

    # ── 最终决策 ──
    final: Action
    confidence: str

    if force_reduce:
        final = "减仓"
        confidence = "高"
        reasons.insert(0, "持仓纪律触发强制/优先减仓")
    elif tech_action == "卖出" and held:
        final = "卖出"
        confidence = "中" if abs(tech_score) == 2 else "高"
        reasons.insert(0, "技术面卖出且当前持有")
    elif tech_action == "卖出" and not held:
        final = "观望"
        confidence = "中"
        reasons.insert(0, "技术面偏空且未持有 → 不追空、不新建")
    elif tech_action == "买入" and forbid_buy:
        final = "观望"
        confidence = "中"
        if fund.forbid_buy:
            reasons.insert(0, "技术面偏多但 F0/F1 或持仓纪律禁止买入/加仓")
        else:
            reasons.insert(0, "技术面偏多但纪律禁止买入/加仓")
    elif tech_action == "买入" and held and weight_pct < MAX_SINGLE_WEIGHT:
        final = "加仓"
        confidence = "中" if tech_score == 2 else "高"
        reasons.insert(0, "技术面买入且仓位/财务过滤通过 → 允许小幅加仓")
    elif tech_action == "买入" and not held:
        final = "买入"
        confidence = "中" if tech_score == 2 else "高"
        reasons.insert(0, "技术面买入且合规/质量过滤通过 → 允许建仓")
    else:
        final = "观望"
        confidence = "低" if tech_score == 0 else "中"
        if fund_level == "unknown":
            confidence = "低"
        if held:
            reasons.insert(0, "信号不足或冲突 → 持有观望")
        else:
            reasons.insert(0, "信号不足 → 不操作")

    # ── P5 成本纪律：浮亏不主动了结，除非基本面破坏 ──
    if (
        NO_LOSS_EXIT
        and held
        and underwater
        and final in ("卖出", "减仓")
        and not fundamental_break
    ):
        rule_signals.append(
            RuleSignal(
                "P5_NO_LOSS_EXIT",
                "成本纪律（不亏本了结）",
                "观望",
                0,
                f"浮亏中（pnl={pnl_pct if pnl_pct is not None else '价<成本'}）且基本面未破坏"
                f"（财务={fund_level}，ST={is_st}）→ 不锁定亏损，改为观望；"
                f"可待回本附近或基本面转红再卖",
            )
        )
        reasons.insert(
            0,
            "成本纪律：浮亏且基本面未破坏 → 不主动卖出/减仓锁定亏损",
        )
        final = "观望"
        confidence = "中"
        force_reduce = False
    elif NO_LOSS_EXIT and held and underwater and final in ("卖出", "减仓") and fundamental_break:
        rule_signals.append(
            RuleSignal(
                "P5_NO_LOSS_EXIT",
                "成本纪律（不亏本了结）",
                final,
                -1,
                f"浮亏中，但基本面已破坏（财务={fund_level}，ST={is_st}）→ 允许破例{final}",
            )
        )
        reasons.insert(0, "成本纪律破例：基本面破坏，允许浮亏减仓/卖出")
    elif NO_LOSS_EXIT and held and not underwater:
        rule_signals.append(
            RuleSignal(
                "P5_NO_LOSS_EXIT",
                "成本纪律（不亏本了结）",
                "观望",
                0,
                "当前未浮亏（价≥成本）→ 卖出不受成本纪律阻止",
            )
        )

    rule_signals.append(
        RuleSignal(
            "D1_DECISION", "最终决策合成", final, _vote(final),
            f"最终动作={final}（技术={tech_action}，净分={tech_score}，"
            f"财务={fund_level}，浮亏={underwater}，持仓={held}）",
        )
    )

    from strategy.execution import build_execution

    exec_plan = build_execution(
        action=final,
        held=held,
        shares=shares if held else 0,
        weight_pct=weight_pct,
        price=float(price) if price is not None else None,
        cost_price=float(cost_price) if cost_price else None,
        is_st=is_st,
        force_reduce=force_reduce,
        fund_level=str(fund_level),
        tech_action=tech_action,
        pnl_pct=pnl_pct,
    )
    rule_signals.append(
        RuleSignal(
            "E1_EXECUTION",
            "执行计划",
            final if final in ("买入", "卖出", "减仓", "加仓") else "观望",
            _vote(final),
            exec_plan.price_hint
            + (f"；建议 {exec_plan.side} {exec_plan.shares} 股（{exec_plan.ratio:.0%}）"
               if exec_plan.shares else f"；{exec_plan.side}"),
        )
    )

    return Decision(
        code=code,
        name=name,
        price=float(price) if price is not None else None,
        action=final,
        confidence=confidence,
        tech_score=tech_score,
        reasons=reasons,
        rule_signals=[s.to_dict() for s in rule_signals],
        execution=exec_plan.to_dict(),
        context={
            "held": held,
            "shares": shares,
            "cost_price": cost_price,
            "weight_pct": weight_pct,
            "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
            "pct_change": pct_change,
            "tech_action": tech_action,
            "forbid_buy": forbid_buy,
            "force_reduce": force_reduce,
            "fund_level": fund_level,
            "fundamentals": fund.to_dict(),
            "disclaimer": "规则信号与执行计划仅供参考，不构成投资建议",
        },
    )


def evaluate_portfolio(
    days: int = 90,
    *,
    quotes: list[dict] | None = None,
    positions: list | None = None,
    max_workers: int = 8,
) -> dict:
    """对全部持仓跑固定策略，并汇总买卖清单。

    性能优化：
    - 可复用外部已拉好的 positions / quotes（报告生成路径只请求 1 次行情）
    - 单票 K 线 + 财报评估用线程池并行（默认 8 路），避免串行 N 次网络 RTT
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    from data.industry import get_industry
    from data.source import get_kline, get_quotes
    from portfolio import load_positions

    if positions is None:
        positions = load_positions()
    if not positions:
        return {
            "message": "持仓为空",
            "catalog": STRATEGY_CATALOG,
            "decisions": [],
        }

    codes = [p.code for p in positions]
    if quotes is None:
        quotes = get_quotes(codes)
    qmap = {q["code"]: q for q in quotes}

    # 市值与黄金主题占比
    items = []
    total_mv = 0.0
    for p in positions:
        q = qmap.get(p.code, {})
        price = q.get("price") or 0
        mv = price * p.shares
        total_mv += mv
        name = q.get("name") or ""
        industry = get_industry(p.code, name)
        items.append({
            "pos": p,
            "q": q,
            "price": price,
            "mv": mv,
            "name": name,
            "industry": industry,
        })

    gold_mv = 0.0
    for it in items:
        w = (it["mv"] / total_mv * 100) if total_mv else 0
        it["weight_pct"] = w
        cost = it["pos"].cost_price * it["pos"].shares
        it["pnl_pct"] = ((it["mv"] - cost) / cost * 100) if cost else None
        if it["pos"].cost_price < 0:
            it["pnl_pct"] = None
        if _is_gold_theme(it["pos"].code, it["name"], it["industry"]):
            gold_mv += it["mv"]
    gold_theme_weight = (gold_mv / total_mv * 100) if total_mv else 0

    def _eval_one(it: dict) -> dict:
        p = it["pos"]
        # 每线程独立拉 K 线；财报在 evaluate_fundamentals 内有 SQLite 缓存
        kdf = None
        try:
            kdf = get_kline(p.code, period="daily", days=days)
        except Exception:
            kdf = None
        d = evaluate_code(
            p.code,
            held=True,
            shares=p.shares,
            cost_price=p.cost_price,
            weight_pct=it["weight_pct"],
            pnl_pct=it["pnl_pct"],
            pct_change=it["q"].get("pct_change"),
            name=it["name"],
            industry=it["industry"],
            gold_theme_weight=gold_theme_weight,
            days=days,
            quote=it["q"],
            kline_df=kdf,
        )
        return d.to_dict()

    workers = max(1, min(max_workers, len(items)))
    decisions: list[dict] = []
    if workers == 1 or len(items) == 1:
        decisions = [_eval_one(it) for it in items]
    else:
        # 保持与持仓顺序一致
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_eval_one, it): i for i, it in enumerate(items)}
            ordered: list[dict | None] = [None] * len(items)
            for fut in as_completed(futs):
                idx = futs[fut]
                try:
                    ordered[idx] = fut.result()
                except Exception as e:
                    p = items[idx]["pos"]
                    ordered[idx] = Decision(
                        code=p.code,
                        name=items[idx]["name"],
                        price=items[idx]["price"],
                        action="观望",
                        confidence="低",
                        tech_score=0,
                        reasons=[f"评估异常：{e}"],
                    ).to_dict()
            decisions = [d for d in ordered if d is not None]

    buckets = {"买入": [], "加仓": [], "卖出": [], "减仓": [], "观望": [], "禁止买入": []}
    for d in decisions:
        buckets.setdefault(d["action"], []).append(d["code"])

    return {
        "total_market_value": round(total_mv, 2),
        "gold_theme_weight": round(gold_theme_weight, 2),
        "catalog": STRATEGY_CATALOG,
        "summary": {k: v for k, v in buckets.items() if v},
        "buy_or_add": [d for d in decisions if d["action"] in ("买入", "加仓")],
        "sell_or_reduce": [d for d in decisions if d["action"] in ("卖出", "减仓")],
        "hold_or_watch": [d for d in decisions if d["action"] in ("观望", "禁止买入")],
        "decisions": decisions,
        "disclaimer": "固定规则信号，不构成投资建议；请结合自身风险承受力决策。",
    }
