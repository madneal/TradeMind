"""生成持仓分析 HTML 报告（单文件，无外部依赖）。"""

from __future__ import annotations

import html
import json
import math
import re
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


_REPORT_NAME_RE = re.compile(r"^portfolio_(\d{8})_(\d{6})\.html$")
_DATA_RAW_RE = re.compile(r'data-raw="([+-]?\d+(?:\.\d+)?)"')
_PCT_RE = re.compile(r"([+-]?\d+(?:\.\d+)?)%")
# 两次快照间隔超过该天数时，连线改虚线，避免把空档看成逐日走势。
_CUM_GAP_DASH_DAYS = 5


def _reports_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "notes" / "reports"


def _extract_cumulative_point(html_text: str) -> tuple[float, float | None] | None:
    """从报告正文取出「累计收益」金额（元）和紧随的百分比。"""
    idx = html_text.find("累计收益")
    if idx < 0:
        return None
    window = html_text[idx : idx + 800]
    raw = _DATA_RAW_RE.search(window)
    if not raw:
        return None
    pct_m = _PCT_RE.search(window)
    pct = float(pct_m.group(1)) if pct_m else None
    return float(raw.group(1)), pct


def load_cumulative_pnl_series(reports_dir: Path | None = None) -> list[dict]:
    """每个自然日取最后一份带「累计收益」的报告。

    返回按日期升序的 `{date, pnl, pct, source}`。pnl 为元。
    """
    reports_dir = reports_dir or _reports_dir()
    if not reports_dir.is_dir():
        return []
    by_day: dict[str, dict] = {}
    for path in sorted(reports_dir.glob("portfolio_*.html")):
        matched = _REPORT_NAME_RE.match(path.name)
        if not matched:
            continue
        day = matched.group(1)
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        extracted = _extract_cumulative_point(text)
        if extracted is None:
            continue
        pnl, pct = extracted
        iso = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
        by_day[iso] = {
            "date": iso,
            "pnl": pnl,
            "pct": pct,
            "source": path.name,
        }
    return [by_day[key] for key in sorted(by_day)]


def load_daily_pnl_series(reports_dir: Path | None = None) -> list[dict]:
    """每个交易日取 15:00 后最后一份报告的「今日盈亏」。"""
    reports_dir = reports_dir or _reports_dir()
    if not reports_dir.is_dir():
        return []
    by_day: dict[str, dict] = {}
    for path in sorted(reports_dir.glob("portfolio_*.html")):
        matched = _REPORT_NAME_RE.match(path.name)
        if not matched or matched.group(2) < "150000":
            continue
        day = matched.group(1)
        iso = f"{day[:4]}-{day[4:6]}-{day[6:8]}"
        if _ymd(iso).weekday() >= 5:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        idx = text.find('class="summary-label">今日盈亏')
        if idx < 0:
            continue
        window = text[idx : idx + 800]
        raw = _DATA_RAW_RE.search(window)
        if raw is None:
            continue
        pct_match = _PCT_RE.search(window)
        by_day[iso] = {
            "date": iso,
            "pnl": float(raw.group(1)),
            "pct": float(pct_match.group(1)) if pct_match else None,
            "source": path.name,
        }
    return [by_day[key] for key in sorted(by_day)]


def _series_with_point(
    series: list[dict], day: str, pnl: float | None, pct: float | None = None
) -> list[dict]:
    """用本次生成的累计收益覆盖当天快照，保证图和页头数字一致。"""
    if pnl is None:
        return series
    kept = [row for row in series if row.get("date") != day]
    kept.append({"date": day, "pnl": float(pnl), "pct": pct, "source": "current"})
    kept.sort(key=lambda row: row["date"])
    return kept


def _nice_step(span: float, target: int = 4) -> float:
    if span <= 0:
        return 1.0
    raw = span / max(target, 1)
    mag = 10 ** math.floor(math.log10(raw))
    for factor in (1, 2, 2.5, 5, 10):
        step = factor * mag
        if step >= raw * 0.75:
            return step
    return 10 * mag


def _axis_ticks(lo: float, hi: float) -> list[float]:
    step = _nice_step(hi - lo)
    start = math.floor(lo / step) * step
    ticks: list[float] = []
    value = start
    # 浮点步进可能多走一格，用次数上限卡住。
    for _ in range(12):
        if value > hi + step * 0.01:
            break
        if value >= lo - step * 0.01:
            ticks.append(value)
        value += step
    if lo < 0 < hi and not any(abs(tick) <= step * 0.05 for tick in ticks):
        ticks.append(0.0)
        ticks.sort()
    return ticks


def _fmt_axis_wan(value: float) -> str:
    wan = value / 10000.0
    if abs(wan) < 0.05:
        return "0"
    if abs(wan - round(wan)) < 0.05:
        return f"{wan:+.0f}万"
    return f"{wan:+.1f}万"


def _ymd(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%d")


def _show_xlabel(index: int, count: int, max_i: int, min_i: int) -> bool:
    if count <= 8 or index in (0, count - 1, max_i, min_i):
        return True
    step = max(1, round((count - 1) / 5))
    return index % step == 0


def _chart_aria(series: list[dict], max_i: int, min_i: int, label: str = "累计收益") -> str:
    high = series[max_i]
    low = series[min_i]
    if max_i == min_i:
        return f"{label}，仅 {high['date']} {_fmt_wan(high['pnl'], signed=True)}"
    return (
        f"{label}折线，最高 {high['date']} {_fmt_wan(high['pnl'], signed=True)}，"
        f"最低 {low['date']} {_fmt_wan(low['pnl'], signed=True)}"
    )


def _pill_text(series: list[dict], index: int, max_i: int, min_i: int) -> str:
    amount = _fmt_wan(series[index]["pnl"], signed=True)
    if max_i == min_i:
        return f"最高/最低 {amount}"
    tag = "最高" if index == max_i else "最低"
    return f"{tag} {amount}"


def _fmt_pct_plain(value: float | None) -> str:
    if value is None:
        return ""
    return f" ({value:+.2f}%)"


def _cumulative_chart_svg(series: list[dict], label: str = "累计收益") -> str:
    """折线用 SVG，刻度和最高/最低标签用 HTML，字号不随图宽缩放。"""
    n = len(series)
    values = [float(row["pnl"]) for row in series]
    data_lo = min(values)
    data_hi = max(values)
    span = data_hi - data_lo
    pad = span * 0.28 if span else max(abs(data_lo) * 0.2, 1000.0)
    view_lo = data_lo - pad
    view_hi = data_hi + pad
    if view_hi <= view_lo:
        view_hi = view_lo + 1.0
    max_i = max(range(n), key=lambda i: values[i])
    min_i = min(range(n), key=lambda i: values[i])

    def x_pct(index: int) -> float:
        if n == 1:
            return 50.0
        return 100.0 * index / (n - 1)

    def y_pct(value: float) -> float:
        return (view_hi - value) / (view_hi - view_lo) * 100.0

    def sx(index: int) -> float:
        return x_pct(index) * 10.0

    def sy(value: float) -> float:
        return y_pct(value) * 10.0

    y_zero = sy(0.0)
    zero_visible = 0.0 <= y_zero <= 1000.0
    svg_parts = [
        '<svg viewBox="0 0 1000 1000" preserveAspectRatio="none" aria-hidden="true">'
    ]
    for tick in _axis_ticks(view_lo, view_hi):
        y = sy(tick)
        if y < -1 or y > 1001:
            continue
        is_zero = abs(tick) < 1
        stroke = "#8b9bb4" if is_zero else "#2d3a4d"
        dash = ' stroke-dasharray="8 8"' if is_zero else ""
        svg_parts.append(
            f'<line x1="0" y1="{y:.1f}" x2="1000" y2="{y:.1f}" '
            f'stroke="{stroke}" stroke-width="1" vector-effect="non-scaling-stroke"{dash}/>'
        )
    for i in range(n - 1):
        gap_days = (_ymd(series[i + 1]["date"]) - _ymd(series[i]["date"])).days
        dashed = gap_days > _CUM_GAP_DASH_DAYS
        x0, y0 = sx(i), sy(values[i])
        x1, y1 = sx(i + 1), sy(values[i + 1])
        if zero_visible and not dashed:
            svg_parts.append(
                f'<polygon points="{x0:.1f},{y0:.1f} {x1:.1f},{y1:.1f} '
                f'{x1:.1f},{y_zero:.1f} {x0:.1f},{y_zero:.1f}" fill="rgba(96,165,250,0.16)"/>'
            )
        dash = ' stroke-dasharray="7 6"' if dashed else ""
        svg_parts.append(
            f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" '
            f'stroke="#60a5fa" stroke-width="2.25" vector-effect="non-scaling-stroke" '
            f'stroke-linecap="round"{dash}/>'
        )
    svg_parts.append("</svg>")

    y_labels: list[str] = []
    for tick in _axis_ticks(view_lo, view_hi):
        yp = y_pct(tick)
        if yp < -2 or yp > 102:
            continue
        y_labels.append(
            f'<span style="top:{min(max(yp, 1), 99):.2f}%">{_e(_fmt_axis_wan(tick))}</span>'
        )

    dots: list[str] = []
    xlabels: list[str] = []
    for i, row in enumerate(series):
        xp, yp = x_pct(i), y_pct(values[i])
        amount = _fmt_wan(row["pnl"], signed=True)
        if i == max_i and i == min_i:
            kind = "flat"
        elif i == max_i:
            kind = "up"
        elif i == min_i:
            kind = "down"
        else:
            kind = ""
        dot_cls = "cum-dot" + (f" {kind}" if kind else "")
        dots.append(
            f'<span class="{dot_cls}" style="left:{xp:.2f}%;top:{yp:.2f}%" '
            f'title="{_e(row["date"] + " " + amount)}"></span>'
        )
        if not _show_xlabel(i, n, max_i, min_i):
            continue
        edge = " start" if i == 0 else " end" if i == n - 1 else ""
        xlabels.append(
            f'<span class="cum-xlabel{edge}{(" " + kind) if kind else ""}" '
            f'style="left:{xp:.2f}%">{_e(row["date"][5:])}</span>'
        )

    def pill(index: int, below: bool) -> str:
        xp = x_pct(index)
        kind = "flat" if max_i == min_i else "up" if index == max_i else "down"
        if xp < 18:
            tx = "0"
        elif xp > 82:
            tx = "-100%"
        else:
            tx = "-50%"
        ty = "12px" if below else "calc(-100% - 12px)"
        return (
            f'<span class="cum-pill {kind}" '
            f'style="left:{xp:.2f}%;top:{y_pct(values[index]):.2f}%;'
            f'transform:translate({tx},{ty})">{_e(_pill_text(series, index, max_i, min_i))}</span>'
        )

    pills = [pill(max_i, False)]
    if min_i != max_i:
        pills.append(pill(min_i, True))

    return (
        f'<div class="cum-plot" role="img" aria-label="{_e(_chart_aria(series, max_i, min_i, label))}">'
        f'<div class="cum-y">{"".join(y_labels)}</div>'
        f'<div class="cum-area">{"".join(svg_parts)}{"".join(dots)}{"".join(pills)}{"".join(xlabels)}</div>'
        f"</div>"
    )


def _cumulative_chart_section(series: list[dict], *, daily: bool = False) -> str:
    if not series:
        return '<div class="section card"><h2>单日盈亏曲线</h2><p class="muted">暂无收盘后的报告数据。</p></div>' if daily else ""
    values = [float(row["pnl"]) for row in series]
    max_i = max(range(len(series)), key=lambda i: values[i])
    min_i = min(range(len(series)), key=lambda i: values[i])
    high = series[max_i]
    low = series[min_i]
    has_gap = any(
        (_ymd(series[i + 1]["date"]) - _ymd(series[i]["date"])).days > _CUM_GAP_DASH_DAYS
        for i in range(len(series) - 1)
    )
    gap_note = " 虚线表示两次报告间隔超过 5 天，中间没有逐日数据。" if has_gap else ""
    if max_i == min_i:
        extreme_html = (
            f'<span><span class="k">最高/最低</span>{_e(high["date"])} '
            f'{_e(_fmt_wan(high["pnl"], signed=True))}{_e(_fmt_pct_plain(high.get("pct")))}</span>'
        )
    else:
        extreme_html = (
            f'<span class="up"><span class="k">最高</span>{_e(high["date"])} '
            f'{_e(_fmt_wan(high["pnl"], signed=True))}{_e(_fmt_pct_plain(high.get("pct")))}</span>'
            f'<span class="down"><span class="k">最低</span>{_e(low["date"])} '
            f'{_e(_fmt_wan(low["pnl"], signed=True))}{_e(_fmt_pct_plain(low.get("pct")))}</span>'
        )
    svg = _cumulative_chart_svg(series, "单日盈亏" if daily else "累计收益")
    chart_id = "daily-pnl-chart" if daily else "cumulative-chart"
    chart_title = "单日盈亏曲线" if daily else "累计收益曲线"
    chart_note = (
        "口径与上方「今日盈亏」相同。每个交易日取 15:00 后最后一份报告；没有收盘后报告的日期不补值。"
        if daily else "口径与上方「累计收益」相同（总资产 − 入金成本）。每个日期取当日最后一份报告。"
    )
    return f"""
  <style>
    #{chart_id}.card {{ min-height: 0; }}
    .cum-chart {{ margin-top: 2px; }}
    .cum-plot {{
      display: grid; grid-template-columns: 46px minmax(0, 1fr);
      column-gap: 6px; align-items: start;
    }}
    .cum-y {{ position: relative; height: 260px; }}
    .cum-y span {{
      position: absolute; right: 0; transform: translateY(-50%);
      color: var(--muted); font-size: 11px; line-height: 1;
      font-variant-numeric: tabular-nums; white-space: nowrap;
    }}
    .cum-area {{ position: relative; height: 260px; margin: 0 0 22px; }}
    .cum-area svg {{ position: absolute; inset: 0; width: 100%; height: 100%; display: block; }}
    .cum-dot {{
      position: absolute; width: 8px; height: 8px; box-sizing: border-box;
      border-radius: 50%; background: #0f1419; border: 2px solid #60a5fa;
      transform: translate(-50%, -50%);
    }}
    .cum-dot.up, .cum-dot.down, .cum-dot.flat {{ width: 11px; height: 11px; border: none; }}
    .cum-dot.up {{ background: #f6465d; box-shadow: 0 0 0 4px rgba(246,70,93,0.28); }}
    .cum-dot.down {{ background: #0ecb81; box-shadow: 0 0 0 4px rgba(14,203,129,0.28); }}
    .cum-dot.flat {{ background: #93c5fd; box-shadow: 0 0 0 4px rgba(147,197,253,0.28); }}
    .cum-pill {{
      position: absolute; z-index: 1; white-space: nowrap; pointer-events: none;
      padding: 2px 8px; border-radius: 6px; font-size: 12px; font-weight: 650; line-height: 1.35;
      background: #141c28; border: 1px solid currentColor;
      font-variant-numeric: tabular-nums;
    }}
    .cum-pill.up {{ color: var(--up); }}
    .cum-pill.down {{ color: var(--down); }}
    .cum-pill.flat {{ color: #93c5fd; }}
    .cum-xlabel {{
      position: absolute; top: calc(100% + 6px); font-size: 11px; line-height: 1;
      color: var(--muted); transform: translateX(-50%); white-space: nowrap;
    }}
    .cum-xlabel.start {{ transform: none; }}
    .cum-xlabel.end {{ transform: translateX(-100%); }}
    .cum-xlabel.up {{ color: var(--up); font-weight: 650; }}
    .cum-xlabel.down {{ color: var(--down); font-weight: 650; }}
    .cum-xlabel.flat {{ color: #93c5fd; font-weight: 650; }}
    .cum-extremes {{
      display: flex; flex-wrap: wrap; gap: 8px 18px; margin-top: 4px;
      font-size: 0.88rem; font-variant-numeric: tabular-nums;
    }}
    .cum-extremes .k {{ color: var(--muted); font-size: 0.75rem; margin-right: 6px; }}
    .cum-note {{ margin: 8px 0 0; font-size: 0.75rem; line-height: 1.45; }}
  </style>
  <div class="section card" id="{chart_id}">
    <h2>{chart_title}</h2>
    <div class="cum-chart">{svg}</div>
    <div class="cum-extremes">{extreme_html}</div>
    <p class="muted cum-note">{chart_note}{gap_note}</p>
  </div>
"""


def build_portfolio_html(
    overview: dict,
    pnl: dict,
    risk: dict,
    signals: dict | None = None,
    *,
    title: str = "TradeMind 持仓分析",
    generated_at: datetime | None = None,
    market: dict | None = None,
    discipline: dict | None = None,
    total_deposits: float | None = None,
) -> str:
    """组装完整 HTML 字符串。"""
    now = generated_at or datetime.now()
    positions = overview.get("positions") or []
    pnl_rows = pnl.get("positions") or []
    industries = risk.get("industry_distribution") or []
    warnings = list(risk.get("warnings") or [])
    # 纪律提示并入风险区
    for w in (discipline or {}).get("warnings") or []:
        if w and w not in warnings:
            warnings.append(w)

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
    total_pnl = pnl.get("total_pnl")
    total_pnl_pct = pnl.get("total_pnl_pct")
    pos_count = overview.get("count") or len(positions)
    # 现金 / 总资产 / 仓位占比（市值÷总资产）
    cash = overview.get("cash")
    if cash is None:
        cash = risk.get("cash")
    total_assets = overview.get("total_assets")
    if total_assets is None:
        total_assets = risk.get("total_assets")
    if total_assets is None and total_mv is not None:
        try:
            cash_f = float(cash) if cash is not None else 0.0
            total_assets = float(total_mv) + cash_f
        except (TypeError, ValueError):
            total_assets = total_mv
    cumulative_pnl = None
    cumulative_pnl_pct = None
    if total_assets is not None and total_deposits is not None:
        try:
            deposits_f = float(total_deposits)
            cumulative_pnl = float(total_assets) - deposits_f
            cumulative_pnl_pct = (
                cumulative_pnl / deposits_f * 100 if deposits_f else None
            )
        except (TypeError, ValueError):
            cumulative_pnl = None
            cumulative_pnl_pct = None
    position_ratio = overview.get("position_ratio")
    if position_ratio is None and total_assets and total_mv is not None:
        try:
            ta = float(total_assets)
            position_ratio = round(float(total_mv) / ta * 100, 2) if ta else None
        except (TypeError, ValueError):
            position_ratio = None
    cash_pct = overview.get("cash_pct")
    if cash_pct is None and cash is not None and total_assets:
        try:
            ta = float(total_assets)
            cash_pct = round(float(cash) / ta * 100, 2) if ta else None
        except (TypeError, ValueError):
            cash_pct = None

    # 今日盈亏合计（优先 overview 字段；否则从明细汇总）
    total_day_pnl = overview.get("total_day_pnl")
    total_day_pnl_pct = overview.get("total_day_pnl_pct")
    if total_day_pnl is None:
        s = 0.0
        known = True
        for r in rows_merged:
            dp = r.get("day_pnl")
            if dp is None:
                known = False
                break
            try:
                s += float(dp)
            except (TypeError, ValueError):
                known = False
                break
        if known and rows_merged:
            total_day_pnl = round(s, 2)
            try:
                mv_f = float(total_mv or 0)
                prev_mv = mv_f - total_day_pnl
                if prev_mv:
                    total_day_pnl_pct = round(total_day_pnl / prev_mv * 100, 2)
            except (TypeError, ValueError):
                total_day_pnl_pct = None

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

    def _disp_name(row: dict) -> str:
        """页面只展示名称，无代码时用代码兜底。"""
        return str(row.get("name") or row.get("code") or "—")

    def _xueqiu_symbol(code: Any) -> str:
        """6 位 A 股/场内基金代码转雪球市场代码。"""
        code_s = str(code or "").strip()
        if len(code_s) != 6 or not code_s.isdigit():
            return ""
        if code_s.startswith(("60", "68", "90", "51", "56", "58", "50", "52", "11")):
            return f"SH{code_s}"
        if code_s.startswith(("00", "30", "20", "15", "16", "17", "18", "12")):
            return f"SZ{code_s}"
        if code_s.startswith(("43", "83", "87", "92")):
            return f"BJ{code_s}"
        return f"SH{code_s}" if code_s[0] in ("5", "6", "9") else f"SZ{code_s}"

    def _stock_link(row: dict) -> str:
        """生成雪球详情页链接；代码无效时退化为纯文本。"""
        name = _disp_name(row)
        symbol = _xueqiu_symbol(row.get("code"))
        if not symbol:
            return _e(name)
        url = f"https://xueqiu.com/S/{symbol}"
        return (
            f'<a class="stock-link" href="{_e(url)}" target="_blank" '
            f'rel="noopener noreferrer" title="在雪球查看 {_e(name)}（{_e(symbol)}）">'
            f'<span>{_e(name)}</span><span class="stock-link-arrow" aria-hidden="true">↗</span></a>'
        )

    pos_trs = []
    for r in rows_merged:
        pos_trs.append(
            f"""<tr>
              <td data-v="{_e(r.get("name"))}">{_stock_link(r)}</td>
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

    drag_trs = []
    for r in drags:
        drag_trs.append(
            f"""<tr>
              <td>{_stock_link(r)}</td>
              <td class="num {_cls_pnl(r.get("pnl"))}">{_fmt_money(r.get("pnl"))}</td>
              <td class="num {_cls_pnl(r.get("pnl_pct"))}">{_fmt_pct(r.get("pnl_pct"))}</td>
              <td class="num {_cls_pnl(r.get("pct_change"))}">{_fmt_pct(r.get("pct_change"))}</td>
            </tr>"""
        )

    mover_down = "".join(
        f"<li>{_stock_link(r)} "
        f"<span class='{_cls_pnl(r.get('pct_change'))}'>{_fmt_pct(r.get('pct_change'))}</span></li>"
        for r in movers[:5]
    )
    mover_up = "".join(
        f"<li>{_stock_link(r)} "
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
              <td>{_stock_link(d)}</td>
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
                f"<li><strong>{_stock_link(d)}</strong> "
                f"<span class='badge {_action_cls(str(action))}'>{_e(action)}</span> "
                f"{_e(shares)} 股 · {_e(price_hint)}</li>"
            )

    warning_names = {
        str(r.get("code") or "").strip(): _disp_name(r)
        for r in rows_merged
        if r.get("code") and _disp_name(r) != str(r.get("code"))
    }

    def _warning_display(warning: Any) -> str:
        """风险提示只展示证券名称；规则计算仍使用证券代码。"""
        text = str(warning)
        for code, name in warning_names.items():
            text = text.replace(f"{code} {name}", name).replace(code, name)
        return text

    warn_html = (
        "".join(f"<li>{_e(_warning_display(w))}</li>" for w in warnings)
        or "<li class='muted'>无额外告警</li>"
    )
    priority_html = "".join(priority) or "<li class='muted'>无高优先级执行项（多为观望）</li>"

    # 市场层（可选）
    mkt = market or {}
    market_time = mkt.get("_as_of")
    idx_lines = []
    for i in (mkt.get("indices") or [])[:6]:
        pct = i.get("pct_change")
        pct_s = _fmt_pct(pct) if pct is not None else "—"
        idx_lines.append(
            f"<li>{_e(i.get('name'))} "
            f"<span class='{_cls_pnl(pct)}'>{_e(pct_s)}</span></li>"
        )
    sent = mkt.get("limit_sentiment") or {}
    sent_html = "—"
    if sent:
        sent_html = (
            f"涨停 {sent.get('zt_count')} · 炸板 {sent.get('zb_count')} · "
            f"跌停 {sent.get('dt_count')} · 炸板率 {sent.get('break_rate_pct')}% · "
            f"最高 {sent.get('max_height')} 连板"
        )
    board_lines = []
    for r in (mkt.get("board_fund") or [])[:8]:
        board_lines.append(
            f"<li>{_e(r.get('name'))} "
            f"{r.get('main_net_yi')}亿 "
            f"<span class='muted'>{_e(r.get('leader'))}</span></li>"
        )
    hot = mkt.get("hot") or {}
    theme_bits = " · ".join(
        f"{t.get('tag')}({t.get('count')})" for t in (hot.get("themes") or [])[:8]
    ) or "—"
    market_section = ""
    if mkt:
        market_section = f"""
  <div class="section two">
    <div class="card">
      <h2>市场 · 指数</h2>
      <p class="muted">市场数据时间：{_e(market_time or '未知')}</p>
      <ul class="clean">{"".join(idx_lines) or "<li class='muted'>无指数数据</li>"}</ul>
      <p class="muted" style="margin:10px 0 0;font-size:0.8rem">情绪：{_e(sent_html)}</p>
    </div>
    <div class="card">
      <h2>市场 · 板块资金 / 题材</h2>
      <ul class="clean">{"".join(board_lines) or "<li class='muted'>无板块数据</li>"}</ul>
      <p class="muted" style="margin:10px 0 0;font-size:0.8rem">热点：{_e(theme_bits)}</p>
    </div>
  </div>
"""

    chart_section = _cumulative_chart_section(
        _series_with_point(
            load_cumulative_pnl_series(),
            now.strftime("%Y-%m-%d"),
            cumulative_pnl,
            cumulative_pnl_pct,
        )
    )
    daily_series = load_daily_pnl_series()
    if now.weekday() < 5 and now.strftime("%H%M%S") >= "150000":
        daily_series = _series_with_point(
            daily_series, now.strftime("%Y-%m-%d"), total_day_pnl, total_day_pnl_pct
        )
    daily_chart_section = _cumulative_chart_section(daily_series, daily=True)

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
  .wrap {{ max-width: 1360px; margin: 0 auto; }}
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
  /* 顶部 KPI：四个合并信息组，桌面端保持单行 */
  .grid {{
    display: grid; gap: 10px; margin-bottom: 20px;
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }}
  @media (max-width: 960px) {{
    .grid {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }}
  }}
  @media (max-width: 520px) {{
    .grid {{ grid-template-columns: 1fr; }}
  }}
  .card {{
    background: var(--card); border: 1px solid var(--border); border-radius: 12px;
    padding: 15px 17px; min-height: 112px; min-width: 0;
    display: flex; flex-direction: column;
  }}
  .grid > .card {{
    position: relative; overflow: hidden; min-height: 112px; padding: 13px 16px;
    background: #192332;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.018);
  }}
  .grid > .card::before {{
    content: ""; position: absolute; inset: 0 18px auto; height: 1px;
    background: linear-gradient(90deg, transparent, rgba(96,165,250,0.42), transparent);
  }}
  .summary-label {{
    color: #91a1b8; font-size: 0.7rem; font-weight: 620;
    letter-spacing: 0.045em; line-height: 1.2;
  }}
  .summary-head {{
    color: #aab7c9; font-size: 0.72rem; font-weight: 650;
    letter-spacing: 0.055em; margin-bottom: 10px;
  }}
  .summary-pair {{
    display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));
    align-items: start; min-width: 0;
  }}
  .summary-item {{ min-width: 0; padding-right: 16px; }}
  .summary-item + .summary-item {{
    padding-left: 16px; padding-right: 0;
    border-left: 1px solid rgba(139,155,180,0.16);
  }}
  .summary-line {{
    display: flex; align-items: baseline; gap: 9px; min-width: 0; margin-top: 7px;
    font-variant-numeric: tabular-nums;
  }}
  .summary-value {{
    color: #dfe7f2; font-size: 1.16rem; font-weight: 680; line-height: 1.2;
    letter-spacing: -0.018em; white-space: nowrap;
  }}
  .summary-pct {{
    color: var(--muted); font-size: 0.75rem; font-weight: 600; white-space: nowrap;
  }}
  .summary-meta {{
    margin-top: auto; padding-top: 7px; color: var(--muted); font-size: 0.7rem;
    line-height: 1.3; font-variant-numeric: tabular-nums;
  }}
  .summary-value.up, .summary-pct.up {{ color: var(--up); }}
  .summary-value.down, .summary-pct.down {{ color: var(--down); }}
  .summary-value.flat, .summary-pct.flat {{ color: var(--muted); }}
  .summary-meta .sep {{ margin: 0 0.3em; opacity: 0.55; }}
  @media (max-width: 380px) {{
    .summary-item {{ padding-right: 10px; }}
    .summary-item + .summary-item {{ padding-left: 10px; }}
    .summary-value {{ font-size: 1.06rem; }}
  }}
  /* 合并指标（其它区块仍可能用到） */
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
    cursor: pointer; color: inherit; font-family: inherit;
    text-align: inherit; white-space: nowrap;
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
  .kpi-sub .up {{ color: var(--up); }}
  .kpi-sub .down {{ color: var(--down); }}
  .kpi-sub .flat {{ color: var(--muted); }}
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
  .stock-link {{
    display: inline-flex; align-items: center; gap: 4px;
    color: inherit; text-decoration: none; font-weight: 550;
    transition: color .15s ease;
  }}
  .stock-link-arrow {{
    color: var(--muted); font-size: 0.68rem; line-height: 1;
    opacity: 0.55; transform: translateY(-1px);
    transition: opacity .15s ease, transform .15s ease;
  }}
  .stock-link:hover {{ color: #93c5fd; }}
  .stock-link:hover .stock-link-arrow {{ opacity: 1; transform: translate(1px, -2px); }}
  .stock-link:focus-visible {{
    outline: 2px solid var(--accent); outline-offset: 3px; border-radius: 3px;
  }}
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
  <p id="refresh-status" class="sub" role="status" aria-live="polite" hidden></p>
  <p class="sub">生成时间 {now.strftime("%Y-%m-%d %H:%M:%S")} · 数据来自 holdings.toml + 实时行情 · 不构成投资建议</p>

  <div class="grid" aria-label="账户概览">
    <div class="card">
      <div class="summary-head">资产与本金</div>
      <div class="summary-pair">
        <div class="summary-item">
          <div class="summary-label">总资产</div>
          <div class="summary-line">{_money_toggle(total_assets if total_assets is not None else total_mv, css="summary-value")}</div>
        </div>
        <div class="summary-item">
          <div class="summary-label">入金成本</div>
          <div class="summary-line">{_money_toggle(total_deposits, css="summary-value")}</div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="summary-head">资金分布</div>
      <div class="summary-pair">
        <div class="summary-item">
          <div class="summary-label">股票市值</div>
          <div class="summary-line"><span class="summary-value">{_fmt_wan(total_mv)}</span></div>
        </div>
        <div class="summary-item">
          <div class="summary-label">现金</div>
          <div class="summary-line"><span class="summary-value">{_fmt_wan(cash) if cash is not None else "—"}</span></div>
        </div>
      </div>
      <div class="summary-meta">当前仓位 {f"{float(position_ratio):.1f}%" if position_ratio is not None else "—"}</div>
    </div>
    <div class="card">
      <div class="summary-head">收益</div>
      <div class="summary-pair">
        <div class="summary-item">
          <div class="summary-label">今日盈亏</div>
          <div class="summary-line">
            {_money_toggle(total_day_pnl, css=f"summary-value {_cls_pnl(total_day_pnl)}", signed=True)}
            <span class="summary-pct {_cls_pnl(total_day_pnl_pct)}">{_fmt_pct(total_day_pnl_pct)}</span>
          </div>
        </div>
        <div class="summary-item">
          <div class="summary-label">累计收益</div>
          <div class="summary-line">
            {_money_toggle(cumulative_pnl, css=f"summary-value {_cls_pnl(cumulative_pnl)}", signed=True)}
            <span class="summary-pct {_cls_pnl(cumulative_pnl_pct)}">{_fmt_pct(cumulative_pnl_pct)}</span>
          </div>
        </div>
      </div>
    </div>
    <div class="card">
      <div class="summary-head">持仓</div>
      <div class="summary-pair">
        <div class="summary-item">
          <div class="summary-label">浮盈亏</div>
          <div class="summary-line">
            {_money_toggle(total_pnl, css=f"summary-value {_cls_pnl(total_pnl)}", signed=True)}
            <span class="summary-pct {_cls_pnl(total_pnl_pct)}">{_fmt_pct(total_pnl_pct)}</span>
          </div>
        </div>
        <div class="summary-item">
          <div class="summary-label">持仓数量</div>
          <div class="summary-line"><span class="summary-value">{_e(pos_count)} 只</span></div>
        </div>
      </div>
      <div class="summary-meta"><span class="up">涨 {n_up}</span><span class="sep">·</span><span class="flat">平 {n_flat}</span><span class="sep">·</span><span class="down">跌 {n_down}</span></div>
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
            <th class="num sortable sorted" data-col="7" data-type="num" title="市值÷总资产（含现金）">仓位%<span class="th-arrow">↓</span></th>
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

  {market_section}

  <div class="section card warn-box">
    <h2>风险 / 纪律提示</h2>
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
    <h2>行业分布 <span class="muted" style="font-size:0.8rem;font-weight:500">（占位% = 市值÷总资产，含现金）</span></h2>
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

  {chart_section}

  {daily_chart_section}

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
<script>
(function () {{
  var status = document.getElementById("refresh-status");
  var busy = false;
  function show(message) {{ status.hidden = false; status.textContent = message; }}
  function poll() {{
    fetch("/health", {{ cache: "no-store" }})
      .then(function (r) {{ return r.json(); }})
      .then(function (state) {{
        if (state.running) {{
          show("正在后台生成，当前报告仍可查看…");
          setTimeout(poll, 1000);
        }} else if (state.last_error) {{
          busy = false;
          show("生成失败：" + state.last_error);
        }} else {{
          show("生成完成，正在更新报告…");
          location.reload();
        }}
      }})
      .catch(function () {{ setTimeout(poll, 2000); }});
  }}
  document.querySelectorAll('a[href="/refresh"], a[href="/refresh?full=1"]').forEach(function (link) {{
    link.addEventListener("click", function (event) {{
      event.preventDefault();
      if (busy) return;
      busy = true;
      show("正在启动后台生成…");
      var full = link.getAttribute("href").indexOf("full=1") !== -1;
      fetch("/refresh?full=" + (full ? "1" : "0"), {{ cache: "no-store" }})
        .then(function (r) {{ if (!r.ok) throw new Error("HTTP " + r.status); }})
        .then(function () {{ poll(); }})
        .catch(function (error) {{ busy = false; show("启动失败：" + error.message); }});
    }});
  }});
  fetch("/health", {{ cache: "no-store" }})
    .then(function (r) {{ return r.json(); }})
    .then(function (state) {{ if (state.running) {{ busy = true; poll(); }} }});
}})();
</script>
</body>
</html>
"""


def collect_report_data(
    *,
    include_signals: bool = True,
    include_market: bool = True,
    days: int = 90,
) -> dict:
    """拉取 overview / pnl / risk / signals / market。

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

    from portfolio import load_cash, load_total_deposits

    t0 = time.time()
    positions = load_positions()
    cash = load_cash()
    total_deposits = load_total_deposits()
    codes = [p.code for p in positions]
    quotes = get_quotes(codes) if codes else []
    t_quote = time.time() - t0

    out: dict[str, Any] = {
        "overview": portfolio_overview_from(positions, quotes, cash=cash),
        "pnl": portfolio_pnl_from(positions, quotes),
        "risk": portfolio_risk_from(positions, quotes, cash=cash),
        "signals": None,
        "market": None,
        "discipline": None,
        "total_deposits": total_deposits,
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
    if include_market:
        t2 = time.time()
        try:
            from tools.review import collect_daily_review

            rev = collect_daily_review(
                include_fundamentals_scan=False, positions=positions, quotes=quotes, cash=cash
            )
            out["market"] = rev.get("market")
            if isinstance(out["market"], dict):
                out["market"]["_as_of"] = rev.get("as_of")
            out["discipline"] = rev.get("discipline")
            try:
                cache_file = _reports_dir() / "market_latest.json"
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(
                    json.dumps({"market": out["market"]}, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as e:
                print(f"[report] market cache write failed: {e}")
        except Exception as e:
            out["market"] = {"error": str(e)}
            out["discipline"] = {"warnings": [f"市场复盘失败: {e}"]}
        out["_timing"]["market_s"] = round(time.time() - t2, 3)
    else:
        try:
            cached = json.loads((_reports_dir() / "market_latest.json").read_text(encoding="utf-8"))
            out["market"] = cached.get("market")
        except (OSError, ValueError):
            pass
    out["_timing"]["total_s"] = round(time.time() - t0, 3)
    return out


def write_portfolio_report(
    path: Path | str | None = None,
    *,
    include_signals: bool = True,
    include_market: bool = True,
    days: int = 90,
    open_browser: bool = False,
) -> Path:
    """生成报告文件，返回路径。"""
    data = collect_report_data(
        include_signals=include_signals,
        include_market=include_market,
        days=days,
    )
    print(f"[report] timing {data['_timing']}")
    now = datetime.now()
    html_str = build_portfolio_html(
        data["overview"],
        data["pnl"],
        data["risk"],
        data.get("signals"),
        generated_at=now,
        market=data.get("market"),
        discipline=data.get("discipline"),
        total_deposits=data.get("total_deposits"),
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
