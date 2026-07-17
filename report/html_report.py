"""生成持仓分析 HTML 报告（单文件，无外部依赖）。"""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path
from typing import Any


def _e(s: Any) -> str:
    return html.escape("" if s is None else str(s))


def _fmt_money(v: Any, digits: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{x:,.{digits}f}"


def _fmt_wan(v: Any, digits: int = 2, signed: bool = False) -> str:
    """默认展示：以「万」为单位。"""
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    wan = x / 10000.0
    if signed:
        return f"{wan:+,.{digits}f} 万"
    return f"{wan:,.{digits}f} 万"


def _money_toggle(
    v: Any,
    *,
    css: str = "",
    signed: bool = False,
    wan_digits: int = 2,
    yuan_digits: int = 2,
) -> str:
    """可点击切换 万/元 的金额节点（默认万）。"""
    try:
        x = float(v)
        raw = f"{x:.{yuan_digits}f}"
    except (TypeError, ValueError):
        return f'<span class="{_e(css)}">—</span>' if css else "—"
    wan_txt = _fmt_wan(x, digits=wan_digits, signed=signed)
    if signed:
        yuan_txt = f"{x:+,.{yuan_digits}f}"
    else:
        yuan_txt = f"{x:,.{yuan_digits}f}"
    cls = f"money-toggle {_e(css)}".strip()
    return (
        f'<button type="button" class="{cls}" data-raw="{_e(raw)}" data-unit="wan" '
        f'data-signed="{"1" if signed else "0"}" data-wan-digits="{wan_digits}" '
        f'data-yuan-digits="{yuan_digits}" title="点击切换：万 / 元">'
        f'<span class="money-text">{_e(wan_txt)}</span>'
        f"</button>"
    )


def _fmt_pct(v: Any, digits: int = 2) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return "—"
    return f"{x:+.{digits}f}%"


def _cls_pnl(v: Any) -> str:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return ""
    if x > 0:
        return "up"
    if x < 0:
        return "down"
    return "flat"


def _action_cls(action: str) -> str:
    if action in ("买入", "加仓"):
        return "act-buy"
    if action in ("卖出", "减仓", "禁止买入"):
        return "act-sell"
    return "act-hold"


def build_portfolio_html(
    overview: dict,
    pnl: dict,
    risk: dict,
    signals: dict | None = None,
    *,
    title: str = "TradeMind 持仓分析",
    generated_at: datetime | None = None,
) -> str:
    """组装完整 HTML 字符串。"""
    now = generated_at or datetime.now()
    positions = overview.get("positions") or []
    pnl_rows = pnl.get("positions") or []
    industries = risk.get("industry_distribution") or []
    warnings = risk.get("warnings") or []

    # 合并 overview + pnl 便于一张表
    pnl_map = {p.get("code"): p for p in pnl_rows}
    rows_merged = []
    for p in positions:
        code = p.get("code")
        q = pnl_map.get(code, {})
        row = {**p}
        row["cost_value"] = q.get("cost_value")
        row["pnl"] = q.get("pnl")
        row["pnl_pct"] = q.get("pnl_pct")
        # day_pnl 优先用 overview 已算好的；否则用涨跌额×股数兜底
        if row.get("day_pnl") is None:
            ch = row.get("change")
            sh = row.get("shares")
            if ch is not None and sh is not None:
                try:
                    row["day_pnl"] = round(float(ch) * float(sh), 2)
                except (TypeError, ValueError):
                    pass
        rows_merged.append(row)

    # 按权重降序
    rows_merged.sort(key=lambda r: float(r.get("weight_pct") or 0), reverse=True)
    # 拖累：按 pnl 升序
    drags = sorted(
        [r for r in rows_merged if r.get("pnl") is not None],
        key=lambda r: float(r.get("pnl") or 0),
    )[:8]
    # 今日涨跌
    movers = sorted(
        [r for r in rows_merged if r.get("pct_change") is not None],
        key=lambda r: float(r.get("pct_change") or 0),
    )

    sig_list: list[dict] = []
    sig_summary = ""
    if signals:
        data = signals.get("data") if isinstance(signals, dict) and "data" in signals else signals
        if isinstance(data, dict):
            if isinstance(data.get("decisions"), list):
                sig_list = data["decisions"]
                summary = data.get("summary")
                if isinstance(summary, dict):
                    sig_summary = " · ".join(f"{k}={v}" for k, v in summary.items())
                elif summary:
                    sig_summary = str(summary)
                gold = data.get("gold_theme_weight")
                if gold is not None:
                    sig_summary = (sig_summary + f" · 黄金主题 {gold}%").strip(" ·")
            elif data.get("code"):
                sig_list = [data]
        elif isinstance(data, list):
            sig_list = data
    if not sig_list and isinstance(signals, list):
        sig_list = signals

    total_mv = overview.get("total_market_value") or pnl.get("total_market_value")
    total_cost = pnl.get("total_cost")
    total_pnl = pnl.get("total_pnl")
    total_pnl_pct = pnl.get("total_pnl_pct")
    hhi = risk.get("hhi")
    pos_count = overview.get("count") or len(positions)

    # 今日涨 / 平 / 跌 只数
    n_up = n_flat = n_down = 0
    for p in positions:
        try:
            ch = p.get("pct_change")
            if ch is None:
                n_flat += 1
                continue
            x = float(ch)
            if x > 0:
                n_up += 1
            elif x < 0:
                n_down += 1
            else:
                n_flat += 1
        except (TypeError, ValueError):
            n_flat += 1

    # 行业条
    ind_bars = []
    max_ind = max((float(i.get("weight_pct") or 0) for i in industries), default=1) or 1
    for ind in industries[:12]:
        w = float(ind.get("weight_pct") or 0)
        pct_bar = 100 * w / max_ind
        ind_bars.append(
            f"""<div class="bar-row">
              <span class="bar-label">{_e(ind.get("industry"))}</span>
              <div class="bar-track"><div class="bar-fill" style="width:{pct_bar:.1f}%"></div></div>
              <span class="bar-val">{w:.1f}% · {_fmt_money(ind.get("market_value"))}</span>
            </div>"""
        )

    def _dv(v: Any) -> str:
        """data-v 数值属性，供前端排序。"""
        try:
            if v is None or v == "":
                return ""
            return f"{float(v)}"
        except (TypeError, ValueError):
            return ""

    pos_trs = []
    for r in rows_merged:
        pos_trs.append(
            f"""<tr>
              <td data-v="{_e(r.get("name"))}">{_e(r.get("name"))}</td>
              <td class="num" data-v="{_dv(r.get("shares"))}">{_e(r.get("shares"))}</td>
              <td class="num" data-v="{_dv(r.get("cost_price"))}">{_fmt_money(r.get("cost_price"), 3)}</td>
              <td class="num" data-v="{_dv(r.get("price"))}">{_fmt_money(r.get("price"), 3)}</td>
              <td class="num {_cls_pnl(r.get("pct_change"))}" data-v="{_dv(r.get("pct_change"))}">{_fmt_pct(r.get("pct_change"))}</td>
              <td class="num {_cls_pnl(r.get("day_pnl"))}" data-v="{_dv(r.get("day_pnl"))}">{_fmt_money(r.get("day_pnl"))}</td>
              <td class="num" data-v="{_dv(r.get("market_value"))}">{_fmt_money(r.get("market_value"))}</td>
              <td class="num" data-v="{_dv(r.get("weight_pct"))}">{float(r.get("weight_pct") or 0):.2f}%</td>
              <td class="num {_cls_pnl(r.get("pnl"))}" data-v="{_dv(r.get("pnl"))}">{_fmt_money(r.get("pnl"))}</td>
              <td class="num {_cls_pnl(r.get("pnl_pct"))}" data-v="{_dv(r.get("pnl_pct"))}">{_fmt_pct(r.get("pnl_pct"))}</td>
            </tr>"""
        )

    def _disp_name(row: dict) -> str:
        """页面只展示名称，无代码时用代码兜底。"""
        return str(row.get("name") or row.get("code") or "—")

    drag_trs = []
    for r in drags:
        drag_trs.append(
            f"""<tr>
              <td>{_e(_disp_name(r))}</td>
              <td class="num {_cls_pnl(r.get("pnl"))}">{_fmt_money(r.get("pnl"))}</td>
              <td class="num {_cls_pnl(r.get("pnl_pct"))}">{_fmt_pct(r.get("pnl_pct"))}</td>
              <td class="num {_cls_pnl(r.get("pct_change"))}">{_fmt_pct(r.get("pct_change"))}</td>
            </tr>"""
        )

    mover_down = "".join(
        f"<li>{_e(_disp_name(r))} "
        f"<span class='{_cls_pnl(r.get('pct_change'))}'>{_fmt_pct(r.get('pct_change'))}</span></li>"
        for r in movers[:5]
    )
    mover_up = "".join(
        f"<li>{_e(_disp_name(r))} "
        f"<span class='{_cls_pnl(r.get('pct_change'))}'>{_fmt_pct(r.get('pct_change'))}</span></li>"
        for r in reversed(movers[-5:])
    )

    sig_trs = []
    priority = []
    for d in sig_list:
        if not isinstance(d, dict):
            continue
        action = d.get("action") or "—"
        ex = d.get("execution") or {}
        if not isinstance(ex, dict):
            ex = {}
        shares = ex.get("shares")
        price_hint = ex.get("price_hint") or ex.get("limit_price") or "—"
        urgency = ex.get("urgency") or d.get("urgency") or "—"
        reasons = d.get("reasons") or []
        reason_s = "；".join(str(x) for x in reasons[:2]) if reasons else "—"
        sig_trs.append(
            f"""<tr>
              <td>{_e(_disp_name(d))}</td>
              <td class="num">{_fmt_money(d.get("price"), 3)}</td>
              <td><span class="badge {_action_cls(str(action))}">{_e(action)}</span></td>
              <td class="num">{_e(shares if shares not in (None, 0) else "—")}</td>
              <td>{_e(urgency)}</td>
              <td class="hint">{_e(price_hint)}</td>
              <td class="muted">{_e(reason_s)}</td>
            </tr>"""
        )
        if str(action) in ("卖出", "减仓", "买入", "加仓") and shares:
            priority.append(
                f"<li><strong>{_e(_disp_name(d))}</strong> "
                f"<span class='badge {_action_cls(str(action))}'>{_e(action)}</span> "
                f"{_e(shares)} 股 · {_e(price_hint)}</li>"
            )

    warn_html = "".join(f"<li>{_e(w)}</li>" for w in warnings) or "<li class='muted'>无额外告警</li>"
    priority_html = "".join(priority) or "<li class='muted'>无高优先级执行项（多为观望）</li>"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>{_e(title)} · {now.strftime("%Y-%m-%d %H:%M")}</title>
<style>
  :root {{
    --bg: #0f1419;
    --card: #1a2332;
    --border: #2d3a4d;
    --text: #e7ecf3;
    --muted: #8b9bb4;
    --up: #f6465d;
    --down: #0ecb81;
    --accent: #3b82f6;
    --warn: #f59e0b;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px 16px 48px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB",
      "Microsoft YaHei", sans-serif;
    background: var(--bg); color: var(--text); line-height: 1.5;
  }}
  .wrap {{ max-width: 1100px; margin: 0 auto; }}
  h1 {{ font-size: 1.5rem; margin: 0; font-weight: 650; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 12px; color: #c5d0e0; font-weight: 600; }}
  .sub {{ color: var(--muted); font-size: 0.875rem; margin-bottom: 20px; }}
  /* 标题行：左侧标题，右侧操作按钮 */
  .page-header {{
    display: flex; align-items: center; justify-content: space-between;
    gap: 16px; flex-wrap: wrap; margin-bottom: 4px;
  }}
  .page-header h1 {{ flex: 1 1 auto; min-width: 0; }}
  .page-actions {{
    display: flex; align-items: center; gap: 8px; flex-wrap: wrap;
    margin-left: auto; flex-shrink: 0;
  }}
  .page-actions a {{
    display: inline-block; padding: 6px 12px; font-size: 0.8rem; font-weight: 600;
    color: #93c5fd; text-decoration: none;
    background: var(--card); border: 1px solid var(--border); border-radius: 8px;
    transition: border-color .15s, background .15s, color .15s;
  }}
  .page-actions a:hover {{
    border-color: var(--accent); color: #bfdbfe; background: #1e2a3d;
  }}
  .page-actions a.primary {{
    background: rgba(59,130,246,0.18); border-color: rgba(59,130,246,0.45); color: #93c5fd;
  }}
  .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); margin-bottom: 20px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
  }}
  .card .label {{ color: var(--muted); font-size: 0.75rem; letter-spacing: 0.02em; }}
  .card .value {{ font-size: 1.25rem; font-weight: 650; margin-top: 6px; font-variant-numeric: tabular-nums; }}
  /* 合并指标：两行堆叠，主次分明 */
  .metric-stack {{ margin-top: 8px; display: flex; flex-direction: column; gap: 6px; }}
  .metric-line {{
    display: flex; align-items: baseline; justify-content: space-between; gap: 10px;
  }}
  .metric-k {{ font-size: 0.72rem; color: var(--muted); flex-shrink: 0; }}
  .metric-v {{
    font-size: 1.15rem; font-weight: 650; font-variant-numeric: tabular-nums;
    text-align: right; line-height: 1.2;
  }}
  .metric-v.sm {{ font-size: 0.95rem; font-weight: 600; color: #c5d0e0; }}
  .metric-split {{
    margin-top: 8px; display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 12px;
  }}
  .metric-split .amt {{
    font-size: 1.2rem; font-weight: 700; font-variant-numeric: tabular-nums;
  }}
  .metric-split .pct {{
    font-size: 1rem; font-weight: 650; font-variant-numeric: tabular-nums;
    padding: 2px 8px; border-radius: 6px; background: rgba(139,155,180,0.12);
  }}
  .metric-split .pct.up {{ background: rgba(246,70,93,0.12); }}
  .metric-split .pct.down {{ background: rgba(14,203,129,0.12); }}
  /* 金额：默认「万」，点击切换精确「元」；涨跌色需盖过默认色 */
  button.money-toggle {{
    appearance: none; border: none; background: transparent; padding: 0; margin: 0;
    cursor: pointer; color: inherit; font: inherit; text-align: inherit;
    border-bottom: 1px dashed rgba(139,155,180,0.45);
  }}
  button.money-toggle.up {{ color: var(--up) !important; }}
  button.money-toggle.down {{ color: var(--down) !important; }}
  button.money-toggle.flat {{ color: var(--muted) !important; }}
  button.money-toggle:hover {{
    border-bottom-color: var(--accent); filter: brightness(1.12);
  }}
  button.money-toggle:focus-visible {{
    outline: 2px solid var(--accent); outline-offset: 2px; border-radius: 4px;
  }}
  .metric-split .amt.up {{ color: var(--up); }}
  .metric-split .amt.down {{ color: var(--down); }}
  .metric-split .amt.flat {{ color: var(--muted); }}
  .metric-v.up {{ color: var(--up); }}
  .metric-v.down {{ color: var(--down); }}
  .metric-v.flat {{ color: var(--muted); }}
  .card .label .hint-unit {{
    margin-left: 6px; font-size: 0.68rem; color: var(--muted); font-weight: 500;
  }}
  /* 涨平跌 chips */
  .count-chips {{
    margin-top: 8px; display: flex; flex-wrap: wrap; gap: 6px; align-items: center;
  }}
  .chip {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 9px; border-radius: 999px; font-size: 0.78rem; font-weight: 650;
    font-variant-numeric: tabular-nums; border: 1px solid transparent;
  }}
  .chip .n {{ font-size: 0.95rem; }}
  .chip-up {{ color: var(--up); background: rgba(246,70,93,0.12); border-color: rgba(246,70,93,0.25); }}
  .chip-flat {{ color: var(--muted); background: rgba(139,155,180,0.12); border-color: rgba(139,155,180,0.25); }}
  .chip-down {{ color: var(--down); background: rgba(14,203,129,0.12); border-color: rgba(14,203,129,0.25); }}
  .chip-total {{ color: #c5d0e0; background: rgba(59,130,246,0.1); border-color: rgba(59,130,246,0.25); }}
  .section {{ margin-bottom: 22px; }}
  table {{ width: 100%; border-collapse: separate; border-spacing: 0; font-size: 0.85rem; }}
  th, td {{ padding: 8px 10px; text-align: left; }}
  td {{ border-bottom: 1px solid var(--border); }}
  tbody tr:last-child td {{ border-bottom: none; }}
  th {{
    color: var(--muted); font-weight: 500; font-size: 0.75rem;
    background: var(--card); border-bottom: 1px solid var(--border);
  }}
  tr:hover td {{ background: rgba(59,130,246,0.06); }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.8rem; }}
  .up {{ color: var(--up); }}
  .down {{ color: var(--down); }}
  .flat {{ color: var(--muted); }}
  .muted {{ color: var(--muted); }}
  .hint {{ font-size: 0.8rem; max-width: 220px; }}
  .badge {{
    display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 0.75rem; font-weight: 600;
  }}
  .act-buy {{ background: rgba(14,203,129,0.15); color: var(--down); }}
  .act-sell {{ background: rgba(246,70,93,0.15); color: var(--up); }}
  .act-hold {{ background: rgba(139,155,180,0.15); color: var(--muted); }}
  .bar-row {{ display: grid; grid-template-columns: 88px 1fr 140px; gap: 8px; align-items: center; margin: 6px 0; font-size: 0.8rem; }}
  .bar-label {{ color: var(--muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .bar-track {{ height: 8px; background: #243044; border-radius: 4px; overflow: hidden; }}
  .bar-fill {{ height: 100%; background: linear-gradient(90deg, var(--accent), #60a5fa); border-radius: 4px; }}
  .bar-val {{ text-align: right; color: var(--muted); font-variant-numeric: tabular-nums; }}
  .two {{ display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }}
  @media (max-width: 720px) {{ .two {{ grid-template-columns: 1fr; }} .bar-row {{ grid-template-columns: 70px 1fr; }} .bar-val {{ display: none; }} }}
  ul.clean {{ margin: 0; padding-left: 18px; }}
  ul.clean li {{ margin: 4px 0; }}
  .foot {{ margin-top: 28px; color: var(--muted); font-size: 0.75rem; border-top: 1px solid var(--border); padding-top: 12px; }}
  .scroll {{
    overflow-x: auto; border-radius: 12px; border: 1px solid var(--border);
    background: var(--card); -webkit-overflow-scrolling: touch;
  }}
  .warn-box {{ border-left: 3px solid var(--warn); padding-left: 12px; }}
  /* 表头点击排序 */
  th.sortable {{
    cursor: pointer; user-select: none; white-space: nowrap;
  }}
  th.sortable:hover {{ color: #e7ecf3; }}
  th.sortable .th-arrow {{
    color: var(--accent); margin-left: 3px; font-size: 0.7rem; opacity: 0.95;
  }}
  th.sortable.sorted {{ color: #93c5fd; }}
  #holdings-table thead th {{
    position: sticky; top: 0; z-index: 2;
    background: var(--card);
    box-shadow: 0 1px 0 var(--border);
    border-bottom: none;
  }}
</style>
</head>
<body>
<div class="wrap">
  <div class="page-header">
    <h1>{_e(title)}</h1>
    <nav class="page-actions" aria-label="报告操作">
      <a href="/">最新</a>
      <a class="primary" href="/refresh" title="快速刷新行情（不含策略）">重新生成</a>
      <a href="/refresh?full=1" title="含固定策略信号，较慢">完整生成</a>
      <a href="/history">历史</a>
    </nav>
  </div>
  <p class="sub">生成时间 {now.strftime("%Y-%m-%d %H:%M:%S")} · 数据来自 holdings.toml + 实时行情 · 不构成投资建议</p>

  <div class="grid">
    <div class="card">
      <div class="label">资产概况 <span class="hint-unit">默认万 · 点击金额切换</span></div>
      <div class="metric-stack">
        <div class="metric-line">
          <span class="metric-k">总市值</span>
          {_money_toggle(total_mv, css=f"metric-v {_cls_pnl(total_pnl)}")}
        </div>
        <div class="metric-line">
          <span class="metric-k">总成本</span>
          {_money_toggle(total_cost, css="metric-v sm")}
        </div>
      </div>
    </div>
    <div class="card">
      <div class="label">浮盈亏 <span class="hint-unit">默认万 · 点击金额切换</span></div>
      <div class="metric-stack">
        <div class="metric-line">
          <span class="metric-k">金额</span>
          {_money_toggle(total_pnl, css=f"metric-v {_cls_pnl(total_pnl)}", signed=True)}
        </div>
        <div class="metric-line">
          <span class="metric-k">比率</span>
          <span class="metric-v {_cls_pnl(total_pnl_pct)}">{_fmt_pct(total_pnl_pct)}</span>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="label">持仓只数</div>
      <div class="count-chips">
        <span class="chip chip-total">共 <span class="n">{_e(pos_count)}</span></span>
        <span class="chip chip-up">涨 <span class="n">{n_up}</span></span>
        <span class="chip chip-flat">平 <span class="n">{n_flat}</span></span>
        <span class="chip chip-down">跌 <span class="n">{n_down}</span></span>
      </div>
    </div>
    <div class="card">
      <div class="label">行业集中度 HHI</div>
      <div class="value">{_e(hhi)}</div>
    </div>
  </div>

  <div class="section" id="holdings-section">
    <h2>持仓明细 <span class="muted" style="font-size:0.8rem;font-weight:500">（点击表头排序）</span></h2>
    <div class="scroll">
      <table id="holdings-table">
        <thead>
          <tr>
            <th class="sortable" data-col="0" data-type="str">名称</th>
            <th class="num sortable" data-col="1" data-type="num">股数</th>
            <th class="num sortable" data-col="2" data-type="num">成本</th>
            <th class="num sortable" data-col="3" data-type="num">现价</th>
            <th class="num sortable" data-col="4" data-type="num">今日%</th>
            <th class="num sortable" data-col="5" data-type="num">今日盈亏</th>
            <th class="num sortable" data-col="6" data-type="num">市值</th>
            <th class="num sortable sorted" data-col="7" data-type="num">权重<span class="th-arrow">↓</span></th>
            <th class="num sortable" data-col="8" data-type="num">浮盈亏</th>
            <th class="num sortable" data-col="9" data-type="num">盈亏%</th>
          </tr>
        </thead>
        <tbody>
          {"".join(pos_trs)}
        </tbody>
      </table>
    </div>
  </div>

  <div class="section card warn-box">
    <h2>风险提示</h2>
    <ul class="clean">{warn_html}</ul>
  </div>

  <div class="section two">
    <div class="card">
      <h2>今日跌幅靠前</h2>
      <ul class="clean">{mover_down}</ul>
    </div>
    <div class="card">
      <h2>今日涨幅靠前</h2>
      <ul class="clean">{mover_up}</ul>
    </div>
  </div>

  <div class="section card">
    <h2>行业分布</h2>
    {"".join(ind_bars) or "<p class='muted'>无行业数据</p>"}
  </div>

  <div class="section">
    <h2>浮亏拖累 Top</h2>
    <div class="scroll">
      <table>
        <thead>
          <tr><th>名称</th><th class="num">浮盈亏</th><th class="num">盈亏%</th><th class="num">今日%</th></tr>
        </thead>
        <tbody>{"".join(drag_trs)}</tbody>
      </table>
    </div>
  </div>

  <div class="section card">
    <h2>策略优先处理</h2>
    <ul class="clean">{priority_html}</ul>
    <p class="muted" style="margin:8px 0 0;font-size:0.8rem">卖出/减仓在浮亏时默认挂成本限价，勿市价砍仓（P5）。</p>
  </div>

  <div class="section">
    <h2>固定策略信号 {_e(sig_summary)}</h2>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>名称</th><th class="num">现价</th><th>动作</th>
            <th class="num">建议股数</th><th>紧急</th><th>价格提示</th><th>理由摘要</th>
          </tr>
        </thead>
        <tbody>
          {"".join(sig_trs) if sig_trs else "<tr><td colspan='7' class='muted'>未包含策略信号（生成时未跑 signals）</td></tr>"}
        </tbody>
      </table>
    </div>
  </div>

  <div class="foot">
    TradeMind 本地报告 · 行情可能延迟或缺失 · 固定规则信号仅供参考，请结合自身风险承受力决策。
  </div>
</div>
<script>
(function () {{
  /* —— 汇总金额：默认「万」，点击切换「元」精确值 —— */
  function fmtYuan(n, signed, digits) {{
    var s = n.toLocaleString("zh-CN", {{
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }});
    if (signed && n > 0) s = "+" + s;
    return s;
  }}
  function fmtWan(n, signed, digits) {{
    var w = n / 10000;
    var s = w.toLocaleString("zh-CN", {{
      minimumFractionDigits: digits,
      maximumFractionDigits: digits
    }});
    if (signed && n > 0) s = "+" + s;
    else if (signed && n === 0) s = (0).toLocaleString("zh-CN", {{
      minimumFractionDigits: digits, maximumFractionDigits: digits
    }});
    return s + " 万";
  }}
  function syncMoneyBtn(btn) {{
    var raw = parseFloat(btn.getAttribute("data-raw"));
    if (isNaN(raw)) return;
    var unit = btn.getAttribute("data-unit") || "wan";
    var signed = btn.getAttribute("data-signed") === "1";
    var wd = parseInt(btn.getAttribute("data-wan-digits") || "2", 10);
    var yd = parseInt(btn.getAttribute("data-yuan-digits") || "2", 10);
    var text = unit === "yuan" ? fmtYuan(raw, signed, yd) : fmtWan(raw, signed, wd);
    var span = btn.querySelector(".money-text");
    if (span) span.textContent = text;
    else btn.textContent = text;
    btn.title = unit === "yuan" ? "点击切换为「万」" : "点击切换为精确「元」";
  }}
  document.querySelectorAll("button.money-toggle").forEach(function (btn) {{
    syncMoneyBtn(btn);
    btn.addEventListener("click", function () {{
      var u = btn.getAttribute("data-unit") || "wan";
      btn.setAttribute("data-unit", u === "wan" ? "yuan" : "wan");
      syncMoneyBtn(btn);
    }});
  }});

  var table = document.getElementById("holdings-table");
  if (!table) return;
  var tbody = table.tBodies[0];
  /* 默认按权重降序；列：0名称 1股数 2成本 3现价 4今日% 5今日盈亏 6市值 7权重 8浮盈亏 9盈亏% */
  var state = {{ col: 7, type: "num", dir: "desc" }};

  function cellValue(tr, col, type) {{
    var td = tr.cells[col];
    if (!td) return type === "num" ? NaN : "";
    var raw = td.getAttribute("data-v");
    if (raw === null || raw === "") raw = (td.textContent || "").trim();
    if (type === "num") {{
      var n = parseFloat(String(raw).replace(/,/g, "").replace(/%/g, ""));
      return isNaN(n) ? Number.NEGATIVE_INFINITY : n;
    }}
    return String(raw);
  }}

  function sortBy(col, type, dir) {{
    state = {{ col: col, type: type, dir: dir }};
    var rows = Array.prototype.slice.call(tbody.rows);
    var mult = dir === "asc" ? 1 : -1;
    rows.sort(function (a, b) {{
      var va = cellValue(a, col, type);
      var vb = cellValue(b, col, type);
      if (type === "num") {{
        if (va < vb) return -1 * mult;
        if (va > vb) return 1 * mult;
        return 0;
      }}
      return String(va).localeCompare(String(vb), "zh") * mult;
    }});
    rows.forEach(function (r) {{ tbody.appendChild(r); }});
    syncHeader();
  }}

  function syncHeader() {{
    var arrow = state.dir === "asc" ? "↑" : "↓";
    Array.prototype.forEach.call(table.querySelectorAll("th.sortable"), function (th) {{
      var c = parseInt(th.getAttribute("data-col"), 10);
      th.classList.toggle("sorted", c === state.col);
      var old = th.querySelector(".th-arrow");
      if (old) old.remove();
      if (c === state.col) {{
        var s = document.createElement("span");
        s.className = "th-arrow";
        s.textContent = arrow;
        th.appendChild(s);
      }}
    }});
  }}

  table.querySelector("thead").addEventListener("click", function (e) {{
    var th = e.target.closest("th.sortable");
    if (!th) return;
    var col = parseInt(th.getAttribute("data-col"), 10);
    var type = th.getAttribute("data-type") || "str";
    var dir = state.col === col
      ? (state.dir === "asc" ? "desc" : "asc")
      : (type === "num" ? "desc" : "asc");
    sortBy(col, type, dir);
  }});

  syncHeader();
}})();
</script>
</body>
</html>
"""


def collect_report_data(*, include_signals: bool = True, days: int = 90) -> dict:
    """拉取 overview / pnl / risk / signals。

    性能：持仓行情只批量请求 **1 次**，overview/pnl/risk 复用同一份 quotes，
    避免原先三次独立 _load_and_quote。
    """
    import time

    import tools  # noqa: F401
    from portfolio import load_positions
    from data.source import get_quotes
    from tools.portfolio import (
        portfolio_overview_from,
        portfolio_pnl_from,
        portfolio_risk_from,
    )

    t0 = time.time()
    positions = load_positions()
    codes = [p.code for p in positions]
    quotes = get_quotes(codes) if codes else []
    t_quote = time.time() - t0

    out: dict[str, Any] = {
        "overview": portfolio_overview_from(positions, quotes),
        "pnl": portfolio_pnl_from(positions, quotes),
        "risk": portfolio_risk_from(positions, quotes),
        "signals": None,
        "_timing": {"quote_s": round(t_quote, 3)},
    }
    if include_signals:
        from strategy.engine import evaluate_portfolio

        t1 = time.time()
        # 传入已拉好的 quotes，避免策略层再打一遍行情
        out["signals"] = {
            "data": evaluate_portfolio(days=days, quotes=quotes, positions=positions)
        }
        out["_timing"]["signals_s"] = round(time.time() - t1, 3)
    out["_timing"]["total_s"] = round(time.time() - t0, 3)
    return out


def write_portfolio_report(
    path: Path | str | None = None,
    *,
    include_signals: bool = True,
    days: int = 90,
    open_browser: bool = False,
) -> Path:
    """生成报告文件，返回路径。"""
    data = collect_report_data(include_signals=include_signals, days=days)
    now = datetime.now()
    html_str = build_portfolio_html(
        data["overview"],
        data["pnl"],
        data["risk"],
        data.get("signals"),
        generated_at=now,
    )
    reports_dir = Path(__file__).resolve().parent.parent / "notes" / "reports"
    if path is None:
        out_dir = reports_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"portfolio_{now.strftime('%Y%m%d_%H%M%S')}.html"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(html_str, encoding="utf-8")

    # 同步最新副本，供本地服务固定 URL 使用
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        latest = reports_dir / "portfolio_latest.html"
        if path.resolve() != latest.resolve():
            latest.write_text(html_str, encoding="utf-8")
    except OSError:
        pass

    if open_browser:
        import webbrowser

        webbrowser.open(path.resolve().as_uri())

    return path.resolve()
