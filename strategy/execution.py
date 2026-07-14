"""E 层执行计划：把「卖出/减仓/买入」落成数量与挂单方式。

成本原则（用户）：
- 默认不亏本了结：卖出限价 ≥ 成本价
- 基本面破坏（ST/财务红灯）允许「破例减仓」，但仍优先挂成本价，禁止建议现价/市价砍仓
- 不构成投资建议
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

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
    ratio: float
    shares: int
    urgency: Urgency
    price_rule: str
    price_hint: str
    limit_price: float | None
    cost_price: float | None = None
    batches: list[dict] = field(default_factory=list)
    target_weight_pct: float | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _round_lot(shares: int, lot: int = 100) -> int:
    if shares <= 0:
        return 0
    if shares < lot:
        return shares
    return (shares // lot) * lot


def _sell_limit_price(
    price: float | None,
    cost_price: float | None,
    *,
    fundamental_break: bool,
) -> tuple[float | None, str, list[str]]:
    """卖出限价：永不建议低于成本的「砍仓价」。

    Returns:
        (limit, price_rule, notes)
    """
    notes: list[str] = []
    if cost_price is not None and cost_price > 0:
        cost = float(cost_price)
        px = float(price) if price and price > 0 else None
        underwater = px is not None and px < cost

        if underwater:
            # 核心：浮亏时挂成本价，不跟现价下浮
            limit = round(cost, 3)
            notes.append(
                f"成本纪律：现价 {px:.3f} < 成本 {cost:.3f}，"
                f"限价挂 **成本价 {limit}**，禁止现价/市价锁亏"
            )
            if fundamental_break:
                notes.append(
                    "虽基本面破坏允许减仓，仍先挂成本价；"
                    "若长期无法成交，由你自行决定是否下调，系统不给出现价砍仓建议"
                )
                return limit, "limit_at_cost_fundamental_break", notes
            return limit, "limit_at_cost_wait_recovery", notes

        # 已回本或浮盈：限价不低于成本，可略低于现价但仍 ≥ 成本
        if px is not None:
            aggressive = round(px * 0.995, 3)
            limit = max(cost, aggressive)
            notes.append(f"已不亏：限价 {limit}（不低于成本 {cost:.3f}）")
            return limit, "t1_open_limit_ge_cost", notes

        return round(cost, 3), "limit_at_cost", notes

    # 无成本信息时退回现价策略（少见）
    if price and price > 0:
        return round(float(price) * 0.995, 3), "t1_open_limit_no_cost", [
            "无成本价字段，限价按现价略下浮；建议补全成本后再执行"
        ]
    return None, "none", ["无法给出限价"]


def build_execution(
    *,
    action: str,
    held: bool,
    shares: int,
    weight_pct: float,
    price: float | None,
    cost_price: float | None = None,
    is_st: bool,
    force_reduce: bool,
    fund_level: str,
    tech_action: str,
    pnl_pct: float | None,
) -> ExecutionPlan:
    """根据最终动作与上下文生成执行计划。"""

    fundamental_break = bool(is_st) or fund_level == "red"
    underwater = False
    if pnl_pct is not None:
        underwater = pnl_pct < 0
    elif price is not None and cost_price and cost_price > 0:
        underwater = float(price) < float(cost_price)

    notes: list[str] = [
        "信号日 T 收盘确认；卖单默认挂成本价或以上，不建议现价锁亏",
        "执行计划为规则默认值，请按整手与交易所规则调整",
    ]

    # ── 持有 ──
    if action in ("观望", "禁止买入") or (not held and action not in ("买入", "加仓")):
        cost = float(cost_price) if cost_price and cost_price > 0 else None
        hint = "无需挂单（浮亏持有或信号不足）"
        if held and underwater and cost is not None:
            hint = (
                f"持有观望；若要坚持减仓原则，只挂 **成本价 {cost:.3f} 附近** 条件单，"
                f"现价约 {price}，不现价砍仓"
            )
            notes.append("成本纪律：浮亏中不主动锁亏；回本附近再卖，或等基本面破坏再破例")
        if held and pnl_pct is not None and pnl_pct <= -40:
            notes.append("深套：禁止摊薄加仓；不强制市价砍仓")
        return ExecutionPlan(
            side="持有",
            ratio=0.0,
            shares=0,
            urgency="低",
            price_rule="none",
            price_hint=hint,
            limit_price=cost if (held and underwater and cost) else None,
            cost_price=cost,
            batches=[],
            notes=notes,
        )

    # ── 买入 / 加仓 ──
    if action in ("买入", "加仓"):
        if held and shares > 0:
            ratio = 0.15
            add_shares = _round_lot(max(int(shares * ratio), 100))
            notes.append(f"加仓约现有持仓的 {ratio:.0%}，且总仓位仍应 < {MAX_SINGLE_WEIGHT:.0f}%")
        else:
            ratio = 0.0
            add_shares = 100
            notes.append("新建仓默认试探 1 手（100 股）；请按总资金 5% 以内自行缩放")
        limit = round(float(price) * 1.005, 3) if price and price > 0 else None
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
            cost_price=float(cost_price) if cost_price else None,
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

    # 浮亏且非基本面破坏：D1 应已改为观望；双保险
    if underwater and not fundamental_break:
        cost = float(cost_price) if cost_price and cost_price > 0 else None
        return ExecutionPlan(
            side="持有",
            ratio=0.0,
            shares=0,
            urgency="低",
            price_rule="limit_at_cost_wait_only",
            price_hint=(
                f"浮亏不卖：可挂成本价 {cost:.3f} 条件单，现价勿砍"
                if cost else "浮亏不卖：等回本或基本面破坏"
            ),
            limit_price=cost,
            cost_price=cost,
            batches=[],
            notes=notes + ["成本纪律拦截：未达基本面破坏，不生成亏损市价/现价卖单"],
        )

    ratio = 0.35
    urgency: Urgency = "中"
    target_w: float | None = None
    reason_tag = "技术卖出"

    if force_reduce and is_st:
        reason_tag = "ST纪律减仓"
        urgency = "高"
        if weight_pct > ST_MAX_WEIGHT:
            target_w = ST_MAX_WEIGHT
            ratio = max(0.5, min(1.0, 1.0 - ST_MAX_WEIGHT / max(weight_pct, 0.01)))
        else:
            ratio = 0.5
        notes.append(f"ST 破例减仓：数量可执行，价格仍优先成本价")
    elif force_reduce and weight_pct >= HARD_SINGLE_WEIGHT:
        reason_tag = "仓位硬上限"
        urgency = "中"  # 不因仓位用市价锁亏
        target_w = MAX_SINGLE_WEIGHT
        ratio = max(0.4, min(1.0, 1.0 - MAX_SINGLE_WEIGHT / max(weight_pct, 0.01)))
    elif force_reduce and weight_pct >= MAX_SINGLE_WEIGHT:
        reason_tag = "仓位超限"
        urgency = "中"
        target_w = MAX_SINGLE_WEIGHT
        ratio = max(0.3, min(0.8, 1.0 - MAX_SINGLE_WEIGHT / max(weight_pct, 0.01)))
    elif action == "卖出":
        if fund_level == "red":
            reason_tag = "技术卖出+财务红灯"
            ratio = 0.70
            urgency = "高"
            notes.append("财务红灯破例：可减仓，限价仍按成本价")
        elif fund_level == "yellow":
            reason_tag = "技术卖出+财务黄灯"
            ratio = 0.45
            urgency = "中"
        else:
            reason_tag = "技术卖出"
            ratio = 0.35
            urgency = "中"
    elif action == "减仓":
        ratio = 0.40
        urgency = "中"
        reason_tag = "纪律减仓"

    sell_shares = _round_lot(int(shares * ratio))
    if sell_shares <= 0 and shares > 0:
        sell_shares = min(shares, 100) if shares >= 100 else shares
    if sell_shares > shares:
        sell_shares = shares

    if target_w is not None and weight_pct > target_w and price and price > 0:
        keep_ratio = target_w / weight_pct
        sell_shares = _round_lot(int(shares * (1 - keep_ratio)))
        sell_shares = min(max(sell_shares, 0), shares)
        ratio = round(sell_shares / shares, 4) if shares else 0

    limit, price_rule, price_notes = _sell_limit_price(
        price, cost_price, fundamental_break=fundamental_break
    )
    notes.extend(price_notes)

    cost = float(cost_price) if cost_price and cost_price > 0 else None
    b1 = _round_lot(int(sell_shares * 0.5)) or sell_shares
    b1 = min(b1, sell_shares)
    b2 = sell_shares - b1

    if underwater and cost is not None:
        # 浮亏破例：两批都挂成本价，绝不写「市价/现价下浮」
        batches = [
            {
                "batch": 1,
                "shares": b1,
                "when": "随时（条件单）",
                "how": f"限价 **成本价 {cost:.3f}**，不跟现价",
            },
        ]
        if b2 > 0:
            batches.append({
                "batch": 2,
                "shares": b2,
                "when": "第 1 批成交后或继续挂着",
                "how": f"继续限价 **≥ {cost:.3f}**；系统不建议降到现价锁亏",
            })
        price_hint = (
            f"浮亏破例减仓：卖 {sell_shares} 股，限价挂成本 **{cost:.3f}**"
            f"（现价约 {price}，勿市价砍）"
        )
        price_rule = "limit_at_cost_only"
    else:
        batches = [
            {
                "batch": 1,
                "shares": b1,
                "when": "T+1 开盘附近",
                "how": f"限价约 {limit}（≥成本）",
            },
        ]
        if b2 > 0:
            batches.append({
                "batch": 2,
                "shares": b2,
                "when": "T+1～T+3",
                "how": f"限价仍 ≥ 成本；可贴近 {limit}",
            })
        price_hint = f"卖 {sell_shares} 股，限价约 {limit}（不低于成本）；勿现价锁亏"

    notes.insert(0, f"触发：{reason_tag}；卖出比例约 {ratio:.0%}（{sell_shares}/{shares} 股）")

    return ExecutionPlan(
        side="卖出",
        ratio=round(ratio, 4),
        shares=sell_shares,
        urgency=urgency,
        price_rule=price_rule,
        price_hint=price_hint,
        limit_price=limit,
        cost_price=cost,
        batches=batches,
        target_weight_pct=target_w,
        notes=notes,
    )
