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
        rows_merged.append({**p, **{k: q.get(k) for k in ("cost_value", "pnl", "pnl_pct") if k in q or True}})
        rows_merged[-1]["cost_value"] = q.get("cost_value")
        rows_merged[-1]["pnl"] = q.get("pnl")
        rows_merged[-1]["pnl_pct"] = q.get("pnl_pct")

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
    max_w = risk.get("max_single_weight")

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

    pos_trs = []
    for r in rows_merged:
        pos_trs.append(
            f"""<tr>
              <td class="mono">{_e(r.get("code"))}</td>
              <td>{_e(r.get("name"))}</td>
              <td class="num">{_e(r.get("shares"))}</td>
              <td class="num">{_fmt_money(r.get("cost_price"), 3)}</td>
              <td class="num">{_fmt_money(r.get("price"), 3)}</td>
              <td class="num {_cls_pnl(r.get("pct_change"))}">{_fmt_pct(r.get("pct_change"))}</td>
              <td class="num">{_fmt_money(r.get("market_value"))}</td>
              <td class="num">{float(r.get("weight_pct") or 0):.2f}%</td>
              <td class="num {_cls_pnl(r.get("pnl"))}">{_fmt_money(r.get("pnl"))}</td>
              <td class="num {_cls_pnl(r.get("pnl_pct"))}">{_fmt_pct(r.get("pnl_pct"))}</td>
            </tr>"""
        )

    drag_trs = []
    for r in drags:
        drag_trs.append(
            f"""<tr>
              <td class="mono">{_e(r.get("code"))}</td>
              <td>{_e(r.get("name"))}</td>
              <td class="num {_cls_pnl(r.get("pnl"))}">{_fmt_money(r.get("pnl"))}</td>
              <td class="num {_cls_pnl(r.get("pnl_pct"))}">{_fmt_pct(r.get("pnl_pct"))}</td>
              <td class="num {_cls_pnl(r.get("pct_change"))}">{_fmt_pct(r.get("pct_change"))}</td>
            </tr>"""
        )

    mover_down = "".join(
        f"<li><span class='mono'>{_e(r.get('code'))}</span> {_e(r.get('name'))} "
        f"<span class='{_cls_pnl(r.get('pct_change'))}'>{_fmt_pct(r.get('pct_change'))}</span></li>"
        for r in movers[:5]
    )
    mover_up = "".join(
        f"<li><span class='mono'>{_e(r.get('code'))}</span> {_e(r.get('name'))} "
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
              <td class="mono">{_e(d.get("code"))}</td>
              <td>{_e(d.get("name"))}</td>
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
                f"<li><strong>{_e(d.get('code'))} {_e(d.get('name'))}</strong> "
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
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; font-weight: 650; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 12px; color: #c5d0e0; font-weight: 600; }}
  .sub {{ color: var(--muted); font-size: 0.875rem; margin-bottom: 20px; }}
  .grid {{ display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); margin-bottom: 20px; }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
  }}
  .card .label {{ color: var(--muted); font-size: 0.75rem; }}
  .card .value {{ font-size: 1.25rem; font-weight: 650; margin-top: 4px; font-variant-numeric: tabular-nums; }}
  .section {{ margin-bottom: 22px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 0.85rem; }}
  th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--border); text-align: left; }}
  th {{ color: var(--muted); font-weight: 500; font-size: 0.75rem; position: sticky; top: 0; background: var(--card); }}
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
  .scroll {{ overflow-x: auto; border-radius: 12px; border: 1px solid var(--border); background: var(--card); }}
  .warn-box {{ border-left: 3px solid var(--warn); padding-left: 12px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{_e(title)}</h1>
  <p class="sub">生成时间 {now.strftime("%Y-%m-%d %H:%M:%S")} · 数据来自 holdings.toml + 实时行情 · 不构成投资建议</p>

  <div class="grid">
    <div class="card"><div class="label">总市值</div><div class="value">{_fmt_money(total_mv)}</div></div>
    <div class="card"><div class="label">总成本</div><div class="value">{_fmt_money(total_cost)}</div></div>
    <div class="card"><div class="label">浮盈亏</div><div class="value {_cls_pnl(total_pnl)}">{_fmt_money(total_pnl)}</div></div>
    <div class="card"><div class="label">浮盈亏%</div><div class="value {_cls_pnl(total_pnl_pct)}">{_fmt_pct(total_pnl_pct)}</div></div>
    <div class="card"><div class="label">持仓只数</div><div class="value">{_e(overview.get("count") or len(positions))}</div></div>
    <div class="card"><div class="label">HHI / 最大单票</div><div class="value">{_e(hhi)} / {_fmt_money(max_w, 1)}%</div></div>
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
    <h2>持仓明细（按权重）</h2>
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>代码</th><th>名称</th><th class="num">股数</th><th class="num">成本</th>
            <th class="num">现价</th><th class="num">今日%</th><th class="num">市值</th>
            <th class="num">权重</th><th class="num">浮盈亏</th><th class="num">盈亏%</th>
          </tr>
        </thead>
        <tbody>
          {"".join(pos_trs)}
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h2>浮亏拖累 Top</h2>
    <div class="scroll">
      <table>
        <thead>
          <tr><th>代码</th><th>名称</th><th class="num">浮盈亏</th><th class="num">盈亏%</th><th class="num">今日%</th></tr>
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
            <th>代码</th><th>名称</th><th class="num">现价</th><th>动作</th>
            <th class="num">建议股数</th><th>紧急</th><th>价格提示</th><th>理由摘要</th>
          </tr>
        </thead>
        <tbody>
          {"".join(sig_trs) if sig_trs else "<tr><td colspan='8' class='muted'>未包含策略信号（生成时未跑 signals）</td></tr>"}
        </tbody>
      </table>
    </div>
  </div>

  <div class="foot">
    TradeMind 本地报告 · 行情可能延迟或缺失 · 固定规则信号仅供参考，请结合自身风险承受力决策。
  </div>
</div>
</body>
</html>
"""


def collect_report_data(*, include_signals: bool = True, days: int = 90) -> dict:
    """拉取 overview / pnl / risk / signals。"""
    import tools  # noqa: F401
    from tools.portfolio import get_portfolio, analyze_pnl, analyze_portfolio_risk

    out: dict[str, Any] = {
        "overview": get_portfolio(),
        "pnl": analyze_pnl(),
        "risk": analyze_portfolio_risk(),
        "signals": None,
    }
    if include_signals:
        from strategy.engine import evaluate_portfolio

        out["signals"] = {"data": evaluate_portfolio(days=days)}
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
    if path is None:
        out_dir = Path(__file__).resolve().parent.parent / "notes" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"portfolio_{now.strftime('%Y%m%d_%H%M%S')}.html"
    else:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

    path.write_text(html_str, encoding="utf-8")

    if open_browser:
        import webbrowser

        webbrowser.open(path.resolve().as_uri())

    return path.resolve()
