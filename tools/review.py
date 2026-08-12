"""每日复盘：市场客观面 + 持仓结构 + 纪律提示。

借鉴 Vibe-Research「每日复盘」信息架构；结论层仍交给人/LLM，本模块只组装 JSON/Markdown。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


def collect_daily_review(*, include_fundamentals_scan: bool = False) -> dict[str, Any]:
    """组装复盘数据包（尽量容错，单项失败写入 missing）。"""
    from portfolio import load_cash, load_positions
    from data.source import get_quotes
    from data.research_market import (
        board_fund_flow,
        index_snapshot,
        limit_up_sentiment,
        map_position_themes,
        ths_hot_reason,
    )
    from tools.portfolio import portfolio_overview_from, portfolio_pnl_from

    as_of = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    missing: list[str] = []
    out: dict[str, Any] = {"as_of": as_of, "market": {}, "portfolio": {}, "discipline": {}, "missing": missing}

    # ── 市场 ──
    idx = index_snapshot()
    if idx.get("error"):
        missing.append(f"indices:{idx.get('error')}")
        out["market"]["indices"] = []
    else:
        out["market"]["indices"] = idx.get("indices") or []

    hot = ths_hot_reason(top_n=20)
    if hot.get("error"):
        missing.append(f"hot:{hot.get('error')}")
        out["market"]["hot"] = {}
    else:
        out["market"]["hot"] = {
            "trade_date": hot.get("trade_date"),
            "themes": (hot.get("themes") or [])[:10],
            "top_stocks": (hot.get("stocks") or [])[:12],
        }

    board = board_fund_flow("industry", "today", 10)
    if board.get("error"):
        missing.append(f"board:{board.get('error')}")
        out["market"]["board_fund"] = []
    else:
        out["market"]["board_fund"] = board.get("rows") or []

    sent = limit_up_sentiment()
    if sent.get("error"):
        missing.append(f"sentiment:{sent.get('error')}")
        out["market"]["limit_sentiment"] = {}
    else:
        out["market"]["limit_sentiment"] = {
            "trade_date": sent.get("trade_date"),
            "zt_count": sent.get("zt_count"),
            "zb_count": sent.get("zb_count"),
            "dt_count": sent.get("dt_count"),
            "break_rate_pct": sent.get("break_rate_pct"),
            "max_height": sent.get("max_height"),
            "ladder": sent.get("ladder"),
            "leaders": sent.get("leaders"),
        }

    # ── 持仓 ──
    positions = load_positions()
    cash = load_cash()
    if not positions:
        out["portfolio"] = {"message": "持仓为空"}
        out["discipline"] = {"warnings": ["持仓为空"]}
        return out

    codes = [p.code for p in positions]
    quotes = get_quotes(codes)
    overview = portfolio_overview_from(positions, quotes, cash=cash)
    pnl = portfolio_pnl_from(positions, quotes)

    pos_rows = overview.get("positions") or []
    themes = map_position_themes(pos_rows)
    total_assets = float(overview.get("total_assets") or overview.get("total_market_value") or 0)
    theme_rows = []
    for name, mv in sorted(themes.items(), key=lambda x: -x[1]):
        theme_rows.append({
            "theme": name,
            "market_value": round(mv, 2),
            "weight_pct": round(mv / total_assets * 100, 2) if total_assets else 0,
        })

    out["portfolio"] = {
        "cash": overview.get("cash"),
        "total_assets": overview.get("total_assets"),
        "total_market_value": overview.get("total_market_value"),
        "position_ratio": overview.get("position_ratio"),
        "cash_pct": overview.get("cash_pct"),
        "count": overview.get("count"),
        "total_day_pnl": overview.get("total_day_pnl"),
        "total_day_pnl_pct": overview.get("total_day_pnl_pct"),
        "total_pnl": pnl.get("total_pnl"),
        "total_pnl_pct": pnl.get("total_pnl_pct"),
        "themes": theme_rows,
        "top_weights": sorted(
            [
                {
                    "code": r.get("code"),
                    "name": r.get("name"),
                    "weight_pct": r.get("weight_pct"),
                    "pct_change": r.get("pct_change"),
                    "day_pnl": r.get("day_pnl"),
                }
                for r in pos_rows
            ],
            key=lambda x: float(x.get("weight_pct") or 0),
            reverse=True,
        )[:10],
    }

    # ── 纪律提示（规则级，非 LLM）──
    warnings: list[str] = []
    pr = overview.get("position_ratio")
    if pr is not None and float(pr) >= 90:
        warnings.append(f"总仓位偏满（{pr}%），容错低，新开仓余地小")
    elif pr is not None and float(pr) >= 85:
        warnings.append(f"总仓位偏高（{pr}%），建议保留现金缓冲")

    gold = next((t for t in theme_rows if t["theme"] == "黄金"), None)
    nonferrous = next((t for t in theme_rows if t["theme"] == "有色/锂矿"), None)
    g_w = (gold or {}).get("weight_pct") or 0
    n_w = (nonferrous or {}).get("weight_pct") or 0
    if g_w + n_w >= 50:
        warnings.append(f"黄金+有色合计约 {g_w + n_w:.1f}%，主题暴露偏高（D2）")
    elif g_w >= 40:
        warnings.append(f"黄金主题约 {g_w:.1f}%，单一主题偏集中")

    # 单票成本占资产（主题 5% 粗检：用成本金额）
    if total_assets > 0:
        for p in positions:
            cost_amt = p.cost_price * p.shares
            pct = cost_amt / total_assets * 100
            if pct > 5 and not p.code.startswith(("15", "51", "56", "58", "1")):
                # ETF 放宽；个股提示
                if not (p.code.startswith("5") or p.code.startswith("1")):
                    warnings.append(
                        f"{p.code} 成本约占资产 {pct:.1f}%（>5% 主题上限 A2，请核对）"
                    )

    st_names = []
    for r in pos_rows:
        name = str(r.get("name") or "")
        if "ST" in name.upper() or name.startswith("*"):
            st_names.append(f"{r.get('code')} {name}")
    if st_names:
        warnings.append("持仓含 ST，禁止加仓（F0/P2）：" + "、".join(st_names))

    # 可选：F1 扫描（较慢，默认关）
    fund_flags = []
    if include_fundamentals_scan:
        from strategy.fundamentals import evaluate_fundamentals, is_etf_or_fund

        for p in positions:
            if is_etf_or_fund(p.code):
                continue
            q = next((x for x in quotes if x.get("code") == p.code), {})
            v = evaluate_fundamentals(p.code, q.get("name") or "")
            if v.level == "red":
                fund_flags.append(f"{p.code} F1/F0 红灯")
            elif v.level == "yellow":
                fund_flags.append(f"{p.code} F1 黄灯")
        warnings.extend(fund_flags[:12])

    out["discipline"] = {
        "warnings": warnings or ["未触发自动纪律告警（不代表无风险）"],
        "fundamentals_scanned": include_fundamentals_scan,
    }
    out["missing"] = missing
    return out


def review_to_markdown(data: dict[str, Any]) -> str:
    """复盘 JSON → Markdown 文本。"""
    lines: list[str] = []
    lines.append(f"# A 股每日复盘 · {data.get('as_of', '')}")
    lines.append("")
    lines.append("> 客观数据组装；**不构成投资建议**。买卖请对照 `decide_*` 与知识库。")
    lines.append("")

    m = data.get("market") or {}
    lines.append("## 1. 大盘指数")
    idx = m.get("indices") or []
    if not idx:
        lines.append("- （指数数据缺失）")
    else:
        for i in idx:
            pct = i.get("pct_change")
            pct_s = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "—"
            lines.append(f"- **{i.get('name')}** {i.get('price')}（{pct_s}）")
    lines.append("")

    sent = m.get("limit_sentiment") or {}
    lines.append("## 2. 短线情绪")
    if not sent:
        lines.append("- （情绪数据缺失）")
    else:
        lines.append(
            f"- 日期 {sent.get('trade_date')} · 涨停 {sent.get('zt_count')} · "
            f"炸板 {sent.get('zb_count')} · 跌停 {sent.get('dt_count')} · "
            f"炸板率 {sent.get('break_rate_pct')}% · 最高连板 {sent.get('max_height')}"
        )
        if sent.get("ladder"):
            lines.append(f"- 连板梯队: {sent.get('ladder')}")
        leaders = sent.get("leaders") or []
        if leaders:
            lines.append("- 高度代表: " + "、".join(
                f"{x.get('name')}({x.get('limit_days')}板)" for x in leaders[:5]
            ))
    lines.append("")

    lines.append("## 3. 板块资金（行业今日主力净流入 TOP）")
    for r in (m.get("board_fund") or [])[:10]:
        lines.append(
            f"- {r.get('rank')}. {r.get('name')}: {r.get('main_net_yi')} 亿 "
            f"({r.get('main_pct')}%) 涨跌 {r.get('change_pct')}% 领涨 {r.get('leader')}"
        )
    if not m.get("board_fund"):
        lines.append("- （板块资金缺失）")
    lines.append("")

    hot = m.get("hot") or {}
    lines.append("## 4. 题材热度（同花顺强势归因）")
    lines.append(f"- 样本日: {hot.get('trade_date') or '—'}")
    themes = hot.get("themes") or []
    if themes:
        lines.append("- TOP 题材: " + " · ".join(f"{t['tag']}({t['count']})" for t in themes[:8]))
    tops = hot.get("top_stocks") or []
    if tops:
        lines.append("- 涨幅靠前:")
        for s in tops[:8]:
            lines.append(
                f"  - {s.get('code')} {s.get('name')} {s.get('pct')}% · {s.get('reason')}"
            )
    lines.append("")

    pf = data.get("portfolio") or {}
    lines.append("## 5. 我的持仓")
    if pf.get("message"):
        lines.append(f"- {pf['message']}")
    else:
        lines.append(
            f"- 总资产 {pf.get('total_assets')} · 市值 {pf.get('total_market_value')} · "
            f"现金(含逆回购口径) {pf.get('cash')} · 仓位 {pf.get('position_ratio')}%"
        )
        lines.append(
            f"- 今日盈亏 {pf.get('total_day_pnl')} ({pf.get('total_day_pnl_pct')}%) · "
            f"累计浮盈亏 {pf.get('total_pnl')} ({pf.get('total_pnl_pct')}%) · "
            f"{pf.get('count')} 只"
        )
        lines.append("- 主题暴露:")
        for t in pf.get("themes") or []:
            lines.append(f"  - {t['theme']}: {t['weight_pct']}%（市值 {t['market_value']}）")
        lines.append("- 权重 TOP:")
        for r in pf.get("top_weights") or []:
            lines.append(
                f"  - {r.get('code')} {r.get('name')} {r.get('weight_pct')}% "
                f"今日 {r.get('pct_change')}% 日盈亏 {r.get('day_pnl')}"
            )
    lines.append("")

    disc = data.get("discipline") or {}
    lines.append("## 6. 纪律提示")
    for w in disc.get("warnings") or []:
        lines.append(f"- {w}")
    lines.append("")

    miss = data.get("missing") or []
    if miss:
        lines.append("## 数据缺失")
        for x in miss:
            lines.append(f"- {x}")
        lines.append("")

    lines.append("---")
    lines.append("*TradeMind daily review · 框架借鉴 Vibe-Research，决策纪律为本地规则。*")
    lines.append("")
    return "\n".join(lines)


def write_daily_review(
    path: Path | str | None = None,
    *,
    include_fundamentals_scan: bool = False,
) -> tuple[Path, dict]:
    """生成复盘并写入 notes/market/。返回 (路径, data)。"""
    data = collect_daily_review(include_fundamentals_scan=include_fundamentals_scan)
    md = review_to_markdown(data)
    root = Path(__file__).resolve().parent.parent
    out_dir = root / "notes" / "market"
    out_dir.mkdir(parents=True, exist_ok=True)
    if path is None:
        stamp = datetime.now().strftime("%Y-%m-%d")
        path = out_dir / f"{stamp}-ashare.md"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(md, encoding="utf-8")
    # 同步 latest
    latest = out_dir / "latest-ashare.md"
    if path.resolve() != latest.resolve():
        latest.write_text(md, encoding="utf-8")
    return path.resolve(), data
