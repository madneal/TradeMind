"""E 层执行计划：把「卖出/减仓/买入」落成数量与挂单方式。

止损纪律（用户原则，2026-07-26）：
- 成本价不是退出锚；止损/技术/纪律卖出可在浮亏中执行
- 卖出限价默认贴近现价（约下浮 0.5%），不再强制 ≥ 成本
- 仍避免建议无计划「市价砍仓」；深套禁止摊薄（P3）
- 若 rules.NO_LOSS_EXIT=True，恢复旧拦截（仅基本面破坏可亏卖）
- 不构成投资建议
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from strategy.rules import (
    HARD_SINGLE_WEIGHT,
    MAX_SINGLE_WEIGHT,
    NO_LOSS_EXIT,
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
    allow_underwater: bool,
) -> tuple[float | None, str, list[str]]:
    """卖出限价。

    allow_underwater=True（默认新纪律）：贴近现价，可低于成本。
    allow_underwater=False（旧 NO_LOSS_EXIT）：浮亏挂成本价等待。
    """
    notes: list[str] = []
    cost = float(cost_price) if cost_price and cost_price > 0 else None
    px = float(price) if price and price > 0 else None
    underwater = px is not None and cost is not None and px < cost

    if not allow_underwater and underwater and cost is not None:
        limit = round(cost, 3)
        notes.append(
            f"旧成本纪律：现价 {px:.3f} < 成本 {cost:.3f}，限价挂成本 {limit}"
        )
        if fundamental_break:
            notes.append("基本面破坏破例减仓，仍先挂成本价条件单")
            return limit, "limit_at_cost_fundamental_break", notes
        return limit, "limit_at_cost_wait_recovery", notes

    if px is not None:
        limit = round(px * 0.995, 3)
        if underwater and cost is not None:
            notes.append(
                f"止损可亏卖：现价 {px:.3f} < 成本 {cost:.3f}，"
                f"限价约 {limit}（贴近现价，不强制 ≥ 成本）"
            )
            return limit, "t1_open_limit_stop_underwater", notes
        if cost is not None:
            notes.append(f"限价约 {limit}（现价附近；成本 {cost:.3f} 仅作参考）")
        else:
            notes.append(f"限价约 {limit}（现价下浮约 0.5%）")
        return limit, "t1_open_limit_near_px", notes

    if cost is not None:
        return round(cost, 3), "limit_at_cost_no_px", ["无现价，暂挂成本价"]
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

    # 新纪律默认允许浮亏卖；仅 NO_LOSS_EXIT 时拦截
    allow_underwater_sell = not NO_LOSS_EXIT or fundamental_break

    notes: list[str] = [
        "信号日 T 收盘确认；卖单默认限价贴近现价（约 -0.5%），避免无计划市价",
        "执行计划为规则默认值，请按整手与交易所规则调整",
        "止损纪律：成本不是退出锚；详见 notes/knowledge/principles/stop-loss.md",
    ]

    # ── 持有 ──
    if action in ("观望", "禁止买入") or (not held and action not in ("买入", "加仓")):
        cost = float(cost_price) if cost_price and cost_price > 0 else None
        hint = "无需挂单（信号不足或持有观望）"
        if held and underwater:
            hint = (
                f"持有观望；若个人止损线已触发，可按 stop-loss 纪律"
                f"在现价附近减仓（现价约 {price}，成本 {cost}）"
            )
            notes.append("无系统卖出信号；是否执行个人结构止损由你对照决策模板")
        if held and pnl_pct is not None and pnl_pct <= -40:
            notes.append("深套：禁止摊薄加仓；补装止损见 stop-loss §6")
        return ExecutionPlan(
            side="持有",
            ratio=0.0,
            shares=0,
            urgency="低",
            price_rule="none",
            price_hint=hint,
            limit_price=None,
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
            notes.append("新建仓默认试探 1 手（100 股）；请按总资金与止损 R 自行缩放")
            notes.append("开仓前应写清：结构止损 S + 资金 R + 错证（decision-template 4b）")
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

    # 旧纪律双保险：浮亏且非基本面破坏 → 不生成卖单
    if underwater and not allow_underwater_sell:
        cost = float(cost_price) if cost_price and cost_price > 0 else None
        return ExecutionPlan(
            side="持有",
            ratio=0.0,
            shares=0,
            urgency="低",
            price_rule="limit_at_cost_wait_only",
            price_hint=(
                f"旧成本纪律：可挂成本价 {cost:.3f} 条件单"
                if cost
                else "旧成本纪律：浮亏不卖"
            ),
            limit_price=cost,
            cost_price=cost,
            batches=[],
            notes=notes + ["NO_LOSS_EXIT 拦截：未生成浮亏现价卖单"],
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
        notes.append("ST 减仓：数量优先；限价贴近现价")
    elif force_reduce and weight_pct >= HARD_SINGLE_WEIGHT:
        reason_tag = "仓位硬上限"
        urgency = "中"
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
            notes.append("财务红灯：提高减仓比例，限价贴近现价")
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

    if underwater:
        notes.append("浮亏卖出：按止损纪律执行，成本仅作参考")

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
        price,
        cost_price,
        fundamental_break=fundamental_break,
        allow_underwater=allow_underwater_sell,
    )
    notes.extend(price_notes)

    cost = float(cost_price) if cost_price and cost_price > 0 else None
    b1 = _round_lot(int(sell_shares * 0.5)) or sell_shares
    b1 = min(b1, sell_shares)
    b2 = sell_shares - b1

    batches = [
        {
            "batch": 1,
            "shares": b1,
            "when": "T+1 开盘附近（止损已触发则优先执行）",
            "how": f"限价约 {limit}（贴近现价）",
        },
    ]
    if b2 > 0:
        batches.append({
            "batch": 2,
            "shares": b2,
            "when": "T+1～T+3",
            "how": f"限价可贴近 {limit}；勿无计划市价",
        })
    price_hint = f"卖 {sell_shares} 股，限价约 {limit}；浮亏亦可执行"
    if underwater:
        price_hint = (
            f"止损/减仓（浮亏）：卖 {sell_shares} 股，限价约 {limit}"
            f"（现价约 {price}，成本 {cost}）"
        )

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
