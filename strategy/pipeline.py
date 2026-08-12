"""研究→决策管道：买入评估 / 多空辩论（底稿先行 + 规则收尾）。

借鉴 Vibe-Research：事实底稿不经 LLM 臆造；TradeMind 独有 decide + 强势 + 知识库要点。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _kb_snippets() -> dict[str, Any]:
    """读取知识库摘要（路径缺失则 missing）。"""
    root = Path(__file__).resolve().parent.parent / "notes" / "knowledge"
    out: dict[str, Any] = {"paths": {}, "excerpts": {}, "missing": []}
    files = {
        "avoid": root / "principles" / "avoid-checklist.md",
        "strong": root / "principles" / "strong-stock.md",
        "stop": root / "principles" / "stop-loss.md",
        "failures_index": root / "failures" / "INDEX.md",
    }
    for k, p in files.items():
        out["paths"][k] = str(p)
        if not p.exists():
            out["missing"].append(k)
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        # 截取要点
        if k == "avoid":
            lines = [ln for ln in text.splitlines() if ln.startswith("| A") or ln.startswith("| B")]
            out["excerpts"][k] = "\n".join(lines[:12])
        elif k == "failures_index":
            out["excerpts"][k] = "\n".join(text.splitlines()[:40])
        else:
            out["excerpts"][k] = text[:1500]
    return out


def run_buy_pipeline(code: str, *, days: int = 90) -> dict[str, Any]:
    """新开仓/加仓评估管道：dossier → strong → F1 → decide → kb → reflect 框架。"""
    from data.source import normalize_code, get_quote
    from tools.research import build_stock_dossier
    from strategy.strong_score import score_code
    from tools.strategy import decide_code
    from tools.reflect import reflect_analysis
    from portfolio import load_positions, load_cash

    code = normalize_code(code)
    dossier = build_stock_dossier(code, days=days)
    strong = score_code(code, days=max(days, 100))
    decision = decide_code(code, days=days)

    # 持仓与主题成本占比
    positions = load_positions()
    cash = load_cash() or 0.0
    held = any(p.code == code for p in positions)
    cost_pct = None
    total_assets = None
    try:
        from data.source import get_quotes
        from tools.portfolio import portfolio_overview_from

        quotes = get_quotes([p.code for p in positions]) if positions else []
        ov = portfolio_overview_from(positions, quotes, cash=cash if cash else None)
        total_assets = ov.get("total_assets") or ov.get("total_market_value")
        for p in positions:
            if p.code == code and total_assets:
                cost_pct = round(p.cost_price * p.shares / float(total_assets) * 100, 2)
    except Exception:
        pass

    fund = (dossier.get("fundamentals") or {})
    fund_level = fund.get("level")
    forbid = bool(fund.get("forbid_buy")) or fund_level == "red"

    # 管道结论标签（非投资建议）
    gates = {
        "strong_ok": bool(strong.get("is_strong")) and not strong.get("veto"),
        "fund_ok": fund_level in ("pass", "yellow", "unknown", "skip") and not forbid,
        "fund_yellow": fund_level == "yellow",
        "theme_cost_ok": cost_pct is None or cost_pct <= 5.0 or not held,
        "rule_action": decision.get("action"),
    }
    if forbid or fund_level == "red":
        pipeline_tag = "不宜买入（财务/合规红灯）"
    elif strong.get("veto"):
        pipeline_tag = "不宜按强者买入（结构否决）"
    elif not gates["strong_ok"]:
        pipeline_tag = "观察列表（强势分不足）"
    elif decision.get("action") in ("卖出", "减仓", "禁止买入"):
        pipeline_tag = f"规则偏向：{decision.get('action')}"
    elif decision.get("action") in ("买入", "加仓"):
        if gates["fund_yellow"]:
            pipeline_tag = "规则偏多但 F1 黄灯：仅极小试错且须写模板"
        else:
            pipeline_tag = "可考虑试错/计划内加仓（仍须 A1 退出+止损）"
    else:
        pipeline_tag = "持有观望 / 等待更优买点"

    kb = _kb_snippets()
    reflect = reflect_analysis(
        text=(
            f"代码{code} 强势{strong.get('score')} 财务{fund_level} "
            f"规则{decision.get('action')} 标签{pipeline_tag}"
        ),
        title=f"buy-pipeline-{code}",
    )

    try:
        q = get_quote(code)
        name = q.get("name") or dossier.get("name") or ""
    except Exception:
        name = dossier.get("name") or ""

    return {
        "code": code,
        "name": name,
        "pipeline_tag": pipeline_tag,
        "gates": gates,
        "strong": strong,
        "dossier": dossier,
        "decision": decision,
        "position": {
            "held": held,
            "cost_pct_of_assets": cost_pct,
            "total_assets": total_assets,
        },
        "knowledge": {
            "missing": kb.get("missing"),
            "avoid_excerpt": (kb.get("excerpts") or {}).get("avoid", "")[:800],
            "failures_index_head": (kb.get("excerpts") or {}).get("failures_index", "")[:600],
            "reminders": [
                "A1 无退出条件不买主题票",
                "A2 主题单票成本 ≤ 总资产 2%–5%",
                "A6 须写结构止损+资金 R+错证",
                "B4 禁止空头摊平",
                "强势分≥7 且无否决才可按强者策略",
            ],
        },
        "reflect": reflect,
        "disclaimer": "管道结果不构成投资建议；规则信号仅供纪律参考。",
    }


def run_debate(code: str, *, days: int = 90) -> dict[str, Any]:
    """多空辩论（规则化一版，不依赖多 LLM）：同一底稿 → 多方/空方要点 → 主持 → decide。"""
    from data.source import normalize_code, get_quote
    from tools.research import build_stock_dossier
    from strategy.strong_score import score_code
    from tools.strategy import decide_code

    code = normalize_code(code)
    dossier = build_stock_dossier(code, days=days)
    strong = score_code(code, days=max(days, 100))
    decision = decide_code(code, days=days)

    fund = dossier.get("fundamentals") or {}
    st = dossier.get("structure") or {}
    quote = dossier.get("quote") or {}
    metrics = fund.get("metrics") or {}

    bull: list[str] = []
    bear: list[str] = []

    # 结构
    if st.get("above_ma20"):
        bull.append(f"收盘在 MA20 上方（结构未破）")
    else:
        bear.append("收盘跌破或未站上 MA20（结构偏弱）")
    if st.get("ret20_pct") is not None:
        r20 = st["ret20_pct"]
        if r20 > 10:
            bull.append(f"近20日涨幅 {r20}% 相对强势")
        elif r20 < -5:
            bear.append(f"近20日涨幅 {r20}% 偏弱")
        else:
            bull.append(f"近20日涨幅 {r20}% 中性")

    if strong.get("is_strong"):
        bull.append(f"强势分 {strong.get('score')}（{strong.get('label')}）")
    if strong.get("veto"):
        bear.append("强势否决：" + "；".join(strong["veto"]))

    # 财务
    level = fund.get("level")
    for reason in fund.get("reasons") or []:
        if "红灯" in reason or "ST" in reason or "禁止" in reason:
            bear.append(reason)
        elif "通过" in reason or "黄灯" not in reason:
            if "通过" in reason:
                bull.append(reason)
            else:
                bear.append(reason) if "黄" in reason or "红" in reason else bull.append(reason)
        else:
            bear.append(reason)

    if level == "pass":
        bull.append("F1 质量层：pass")
    elif level == "yellow":
        bear.append("F1 黄灯：不宜常规加仓")
    elif level == "red":
        bear.append("F1/F0 红灯：禁止买入/加仓")

    ry = metrics.get("revenue_yoy")
    ny = metrics.get("netprofit_yoy")
    if isinstance(ry, (int, float)):
        (bull if ry > 0 else bear).append(f"营收同比 {ry:.1f}%")
    if isinstance(ny, (int, float)):
        (bull if ny > 0 else bear).append(f"净利同比 {ny:.1f}%")

    # 公告
    anns = dossier.get("announcements") or []
    if anns:
        bull.append(f"近期公告 {len(anns)} 条（详见底稿，需人工扫风险标题）")
    if dossier.get("missing"):
        bear.append("数据缺口：" + ", ".join(dossier["missing"][:6]))

    # 主持
    consensus = []
    if quote.get("price"):
        consensus.append(f"现价约 {quote.get('price')}，今日 {quote.get('pct_change')}%")
    if metrics.get("report_name"):
        consensus.append(f"财务报告期：{metrics.get('report_name')}")

    divergences = []
    if bull and bear:
        divergences.append("结构/主题弹性 vs 财务与否决项是否冲突")
    if strong.get("is_strong") and level in ("red", "yellow"):
        divergences.append("强势结构与财务质量不同步（假强风险）")
    if not st.get("above_ma20") and decision.get("action") in ("买入", "加仓"):
        divergences.append("规则动作与 MA20 结构可能不一致，需复核 decide 理由")

    verify = [
        "核对最新完整财报：净利、经营现金流、应收、毛利（F1）",
        "确认是否 ST/立案/减持等公告风险",
        "强势分与板块内相对强度是否仍成立（MA20、量价）",
        "若开仓：写清退出条件与止损（A1/A6），主题成本≤5%（A2）",
        f"规则动作已给出：{decision.get('action')} — 不得用叙事覆盖红灯",
    ]

    try:
        name = get_quote(code).get("name") or dossier.get("name") or ""
    except Exception:
        name = dossier.get("name") or ""

    return {
        "code": code,
        "name": name,
        "dossier_summary": {
            "quote": quote,
            "structure": st,
            "fund_level": level,
            "strong_score": strong.get("score"),
            "strong_label": strong.get("label"),
            "missing": dossier.get("missing"),
        },
        "bull_points": bull[:12],
        "bear_points": bear[:12],
        "moderator": {
            "consensus": consensus,
            "divergences": divergences,
            "verify_checklist": verify,
            "note": "主持不裁决买卖；终点是验证清单。",
        },
        "rule_decision": {
            "action": decision.get("action"),
            "confidence": decision.get("confidence"),
            "reasons": (decision.get("reasons") or [])[:6],
            "execution": decision.get("execution"),
        },
        "disclaimer": "辩论与规则信号均不构成投资建议。",
    }


def pipeline_to_markdown(kind: str, data: dict[str, Any]) -> str:
    """管道结果转 Markdown。"""
    lines: list[str] = []
    if kind == "buy":
        lines.append(f"# 买入管道 · {data.get('code')} {data.get('name')}")
        lines.append("")
        lines.append(f"**时机标签：** {data.get('pipeline_tag')}")
        lines.append("")
        g = data.get("gates") or {}
        lines.append("## 闸门")
        lines.append(f"- 强势: {g.get('strong_ok')} · 财务可交易: {g.get('fund_ok')} · 黄灯: {g.get('fund_yellow')}")
        lines.append(f"- 规则动作: {g.get('rule_action')} · 主题成本闸: {g.get('theme_cost_ok')}")
        st = data.get("strong") or {}
        lines.append("")
        lines.append("## 强势")
        lines.append(f"- 分 {st.get('score')} · {st.get('label')} · 否决 {st.get('veto')}")
        lines.append(f"- 明细 {st.get('detail')}")
        fund = (data.get("dossier") or {}).get("fundamentals") or {}
        lines.append("")
        lines.append("## 财务 F0/F1")
        lines.append(f"- level={fund.get('level')} forbid_buy={fund.get('forbid_buy')}")
        for r in fund.get("reasons") or []:
            lines.append(f"- {r}")
        d = data.get("decision") or {}
        lines.append("")
        lines.append("## 规则 decide")
        lines.append(f"- **{d.get('action')}** 置信度 {d.get('confidence')}")
        for r in (d.get("reasons") or [])[:8]:
            lines.append(f"- {r}")
        kb = data.get("knowledge") or {}
        lines.append("")
        lines.append("## 知识库提醒")
        for r in kb.get("reminders") or []:
            lines.append(f"- {r}")
        lines.append("")
        lines.append("## 反思清单")
        for c in (data.get("reflect") or {}).get("checklist") or []:
            lines.append(f"- {c}")
    else:
        lines.append(f"# 多空辩论 · {data.get('code')} {data.get('name')}")
        lines.append("")
        lines.append("## 底稿摘要")
        lines.append(str(data.get("dossier_summary")))
        lines.append("")
        lines.append("## 多方")
        for p in data.get("bull_points") or []:
            lines.append(f"- {p}")
        lines.append("")
        lines.append("## 空方")
        for p in data.get("bear_points") or []:
            lines.append(f"- {p}")
        mod = data.get("moderator") or {}
        lines.append("")
        lines.append("## 主持")
        lines.append("### 共识")
        for p in mod.get("consensus") or []:
            lines.append(f"- {p}")
        lines.append("### 分歧")
        for p in mod.get("divergences") or []:
            lines.append(f"- {p}")
        lines.append("### 验证清单")
        for p in mod.get("verify_checklist") or []:
            lines.append(f"- {p}")
        rd = data.get("rule_decision") or {}
        lines.append("")
        lines.append("## 规则收尾（TradeMind）")
        lines.append(f"- **动作 {rd.get('action')}** · 置信度 {rd.get('confidence')}")
        for r in rd.get("reasons") or []:
            lines.append(f"- {r}")
    lines.append("")
    lines.append(f"*{data.get('disclaimer', '')}*")
    lines.append("")
    return "\n".join(lines)
