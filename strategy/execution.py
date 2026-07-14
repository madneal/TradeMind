"""E 层执行计划：把「卖出/减仓/买入」落成数量与挂单方式。

原则：
- 方向由 D1 决定；本层只回答「卖/买多少、怎么挂」
- 默认 T+1 开盘执行（与回测一致），可分批
- 不构成投资建议
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from strategy.rules import (
    HARD_SINGLE_WEIGHT,
    MAX_SINGLE_WEIGHT,
    ST_MAX_WEIGHT,
)

Urgency = Literal["高", "中", "低"]
Side = Literal["卖出", "买入", "持有"]


@dataclass
class ExecutionPlan:
    side: Side
    ratio: float  # 相对当前持仓（卖）或建议加仓占现有持仓比例（买）
    shares: int  # 建议股数（A 股按 100 股取整；不足 100 则按实际）
    urgency: Urgency
    price_rule: str
    price_hint: str
    limit_price: float | None  # 参考限价（基于最新价推算，非保证成交）
    batches: list[dict] = field(default_factory=list)
    target_weight_pct: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _round_lot(shares: int, lot: int = 100) -> int:
    if shares <= 0:
        return 0
    if shares < lot:
        return shares  # 不足 1 手全部出/进（科创板等可不足 100）
    return (shares // lot) * lot


def _limit_from_last(price: float | None, side: Side, slip: float = 0.005) -> float | None:
    if price is None or price <= 0:
        return None
    if side == "卖出":
        return round(price * (1 - slip), 3)  # 略低于现价提高成交概率
    if side == "买入":
        return round(price * (1 + slip), 3)
    return None


def build_execution(
    *,
    action: str,
    held: bool,
    shares: int,
    weight_pct: float,
    price: float | None,
    is_st: bool,
    force_reduce: bool,
    fund_level: str,
    tech_action: str,
    pnl_pct: float | None,
) -> ExecutionPlan:
    """根据最终动作与上下文生成执行计划。"""

    notes: list[str] = [
        "信号日 T 收盘确认；默认 T+1 开盘附近执行",
        "3 个交易日未成交则改为贴近市价了结计划量",
        "执行计划为规则默认值，请按整手与交易所规则调整",
    ]

    # ── 持有 ──
    if action in ("观望", "禁止买入") or not held and action not in ("买入",):
        if action == "观望" and held and pnl_pct is not None and pnl_pct <= -40:
            notes.append("深套：不强制卖出；若反弹可自行减 20%～40%，禁止摊薄加仓")
        return ExecutionPlan(
            side="持有",
            ratio=0.0,
            shares=0,
            urgency="低",
            price_rule="none",
            price_hint="无需挂单",
            limit_price=None,
            batches=[],
            notes=notes,
        )

    # ── 买入 / 加仓 ──
    if action in ("买入", "加仓"):
        # 加仓：现有仓位的 15%；新建：无法知总资金，给「参考 1 手或按承受力」
        if held and shares > 0:
            ratio = 0.15
            add_shares = _round_lot(max(int(shares * ratio), 100))
            # 不超过再把仓位抬到 30%
            notes.append(f"加仓约现有持仓的 {ratio:.0%}，且总仓位仍应 < {MAX_SINGLE_WEIGHT:.0f}%")
        else:
            ratio = 0.0
            add_shares = 100  # 默认试探 1 手
            notes.append("新建仓默认试探 1 手（100 股）；请按总资金 5% 以内自行缩放")
        limit = _limit_from_last(price, "买入")
        batches = [
            {
                "batch": 1,
                "shares": add_shares,
                "when": "T+1 开盘后 15 分钟内",
                "how": f"限价约 {limit}（现价上浮约 0.5%）或跟买一",
            }
        ]
        return ExecutionPlan(
            side="买入",
            ratio=ratio,
            shares=add_shares,
            urgency="中",
            price_rule="t1_open_limit_above",
            price_hint=f"T+1 开盘限价买入，参考价 {limit}",
            limit_price=limit,
            batches=batches,
            notes=notes,
        )

    # ── 卖出 / 减仓 ──
    if not held or shares <= 0:
        return ExecutionPlan(
            side="持有",
            ratio=0.0,
            shares=0,
            urgency="低",
            price_rule="none",
            price_hint="未持有，无需卖出",
            limit_price=None,
            notes=notes,
        )

    ratio = 0.35
    urgency: Urgency = "中"
    target_w: float | None = None
    reason_tag = "技术卖出"

    if force_reduce and is_st:
        reason_tag = "ST纪律减仓"
        urgency = "高"
        if weight_pct > ST_MAX_WEIGHT:
            # 减到 ST 上限仓位
            target_w = ST_MAX_WEIGHT
            ratio = max(0.5, min(1.0, 1.0 - ST_MAX_WEIGHT / max(weight_pct, 0.01)))
        else:
            ratio = 0.5
        notes.append(f"ST：优先降风险，目标仓位 ≤ {ST_MAX_WEIGHT:.0f}% 或清仓")
    elif force_reduce and weight_pct >= HARD_SINGLE_WEIGHT:
        reason_tag = "仓位硬上限"
        urgency = "高"
        target_w = MAX_SINGLE_WEIGHT
        ratio = max(0.4, min(1.0, 1.0 - MAX_SINGLE_WEIGHT / max(weight_pct, 0.01)))
        notes.append(f"单票过重：减到约 {MAX_SINGLE_WEIGHT:.0f}% 以下")
    elif force_reduce and weight_pct >= MAX_SINGLE_WEIGHT:
        reason_tag = "仓位超限"
        urgency = "高"
        target_w = MAX_SINGLE_WEIGHT
        ratio = max(0.3, min(0.8, 1.0 - MAX_SINGLE_WEIGHT / max(weight_pct, 0.01)))
    elif action == "卖出":
        if fund_level == "red":
            reason_tag = "技术卖出+财务红灯"
            ratio = 0.70
            urgency = "高"
            notes.append("财务红灯：宜加大卖出比例，禁止补仓")
        elif fund_level == "yellow":
            reason_tag = "技术卖出+财务黄灯"
            ratio = 0.45
            urgency = "中"
            notes.append("财务黄灯：先减一半左右，勿摊薄")
        else:
            reason_tag = "技术卖出"
            ratio = 0.35
            urgency = "中"
            notes.append("财务尚可：分批减仓，不必一次清空")
    elif action == "减仓":
        ratio = 0.40
        urgency = "中"
        reason_tag = "纪律减仓"

    sell_shares = _round_lot(int(shares * ratio))
    if sell_shares <= 0 and shares > 0:
        sell_shares = min(shares, 100) if shares >= 100 else shares
    if sell_shares > shares:
        sell_shares = shares

    # 若目标是降到某权重，再校准股数
    if target_w is not None and weight_pct > target_w and price and price > 0:
        # weight 与股数近似线性
        keep_ratio = target_w / weight_pct
        sell_shares = _round_lot(int(shares * (1 - keep_ratio)))
        sell_shares = min(max(sell_shares, 0), shares)
        ratio = round(sell_shares / shares, 4) if shares else 0

    limit = _limit_from_last(price, "卖出")
    # 分批
    if urgency == "高" or ratio >= 0.6:
        b1 = _round_lot(int(sell_shares * 0.6)) or sell_shares
        b1 = min(b1, sell_shares)
        b2 = sell_shares - b1
        batches = [
            {
                "batch": 1,
                "shares": b1,
                "when": "T+1 开盘～开盘后 30 分钟",
                "how": f"限价约 {limit} 或更低以求成交（紧急）",
            },
        ]
        if b2 > 0:
            batches.append({
                "batch": 2,
                "shares": b2,
                "when": "T+1～T+2 若反弹或未成交",
                "how": "贴近市价或略低于现价清掉剩余计划量",
            })
        price_rule = "t1_open_aggressive"
        price_hint = f"优先成交：T+1 开盘限价约 {limit}（现价下浮约 0.5%）；3 日未成则市价"
    else:
        b1 = _round_lot(int(sell_shares * 0.5)) or sell_shares
        b1 = min(b1, sell_shares)
        b2 = sell_shares - b1
        batches = [
            {
                "batch": 1,
                "shares": b1,
                "when": "T+1 开盘附近",
                "how": f"限价约 {limit}",
            },
        ]
        if b2 > 0:
            batches.append({
                "batch": 2,
                "shares": b2,
                "when": "T+1～T+3 反弹时",
                "how": "挂在近 5 日均价附近；到期未成则降价成交",
            })
        price_rule = "t1_open_limit_batch"
        price_hint = f"分批：先 {b1} 股@约 {limit}；其余等弱反弹，3 日规则失效则清计划量"

    notes.insert(0, f"触发：{reason_tag}；卖出比例约 {ratio:.0%}（{sell_shares}/{shares} 股）")

    return ExecutionPlan(
        side="卖出",
        ratio=round(ratio, 4),
        shares=sell_shares,
        urgency=urgency,
        price_rule=price_rule,
        price_hint=price_hint,
        limit_price=limit,
        batches=batches,
        target_weight_pct=target_w,
        notes=notes,
    )
