"""经营业绩过滤：F0 合规一票否决 + F1 质量门槛。

- ETF/场内基金：跳过财务层
- 业绩不单独打「买入分」，只限制买入/加仓资格
- 数据：东财利润表/资产负债表/现金流量表（akshare），本地缓存 7 天
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd

from strategy.rules import (
    ETF_CODE_PREFIXES,
    GROSS_MARGIN_DROP_PP,
    OCF_TO_PROFIT_YELLOW,
    RECEIVABLE_VS_REVENUE_YOY_GAP,
)

FundLevel = Literal["pass", "yellow", "red", "unknown", "skip"]


@dataclass
class FundamentalVerdict:
    code: str
    skip: bool
    level: FundLevel
    forbid_buy: bool
    reasons: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    source: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def is_etf_or_fund(code: str, name: str = "") -> bool:
    code = (code or "").zfill(6)
    if code.startswith(ETF_CODE_PREFIXES):
        return True
    n = name or ""
    return "ETF" in n.upper() or "基金" in n or "联接" in n


def _safe_float(x) -> float | None:
    if x is None:
        return None
    try:
        if pd.isna(x):
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


def _latest_row(df: pd.DataFrame) -> pd.Series | None:
    if df is None or df.empty:
        return None
    if "REPORT_DATE" in df.columns:
        d = df.copy()
        d["REPORT_DATE"] = pd.to_datetime(d["REPORT_DATE"], errors="coerce")
        d = d.sort_values("REPORT_DATE", ascending=False)
        return d.iloc[0]
    return df.iloc[0]


def _prev_annual_row(df: pd.DataFrame) -> pd.Series | None:
    """最近一期年报行（用于同比毛利率等）。"""
    if df is None or df.empty or "REPORT_DATE" not in df.columns:
        return None
    d = df.copy()
    d["REPORT_DATE"] = pd.to_datetime(d["REPORT_DATE"], errors="coerce")
    d = d.sort_values("REPORT_DATE", ascending=False)
    for _, row in d.iterrows():
        rtype = str(row.get("REPORT_TYPE") or "")
        if "年" in rtype or (hasattr(row["REPORT_DATE"], "month") and row["REPORT_DATE"].month == 12):
            return row
    return None


def _em_symbol(code: str) -> str:
    """东财三表接口需要 SH/SZ 前缀。"""
    from data.source import normalize_code, _to_sina_symbol

    code = normalize_code(code)
    sina = _to_sina_symbol(code)  # sh600519 / sz000001
    return sina[:2].upper() + code  # SH600519


def fetch_fundamental_metrics(code: str) -> dict[str, Any]:
    """拉取并标准化关键财务字段。失败返回 {error: ...}。"""
    from data import cache
    from data.source import normalize_code

    code = normalize_code(code)
    cached = cache.get_fund_cache(code)
    if cached is not None and not cached.get("error"):
        return cached
    # 带 error 的短缓存也尊重，避免狂打接口；但本次若刚修 bug 可强制刷新 error
    if cached is not None and cached.get("error") and "NoneType" not in str(cached.get("error")):
        return cached

    import akshare as ak

    out: dict[str, Any] = {"code": code}
    sym = _em_symbol(code)
    try:
        profit = ak.stock_profit_sheet_by_report_em(symbol=sym)
        bal = ak.stock_balance_sheet_by_report_em(symbol=sym)
        cash = ak.stock_cash_flow_sheet_by_report_em(symbol=sym)
    except Exception as e:
        out["error"] = f"{type(e).__name__}: {e}"
        cache.set_fund_cache(code, out)
        return out

    pr = _latest_row(profit)
    br = _latest_row(bal)
    cr = _latest_row(cash)
    if pr is None:
        out["error"] = "无利润表数据"
        cache.set_fund_cache(code, out)
        return out

    revenue = _safe_float(pr.get("TOTAL_OPERATE_INCOME"))
    revenue_yoy = _safe_float(pr.get("TOTAL_OPERATE_INCOME_YOY"))
    netprofit = _safe_float(pr.get("PARENT_NETPROFIT") or pr.get("NETPROFIT"))
    netprofit_yoy = _safe_float(pr.get("PARENT_NETPROFIT_YOY") or pr.get("NETPROFIT_YOY"))
    op_cost = _safe_float(pr.get("OPERATE_COST"))
    ocf = _safe_float(cr.get("NETCASH_OPERATE")) if cr is not None else None
    receivable = _safe_float(br.get("ACCOUNTS_RECE")) if br is not None else None

    gross_margin = None
    if revenue and op_cost is not None and revenue != 0:
        gross_margin = (revenue - op_cost) / revenue * 100

    # 上一期年报毛利率（若有）
    gross_margin_prev = None
    pa = _prev_annual_row(profit)
    # 找次新年报
    if profit is not None and not profit.empty and "REPORT_DATE" in profit.columns:
        d = profit.copy()
        d["REPORT_DATE"] = pd.to_datetime(d["REPORT_DATE"], errors="coerce")
        annuals = []
        for _, row in d.iterrows():
            rtype = str(row.get("REPORT_TYPE") or "")
            if "年" in rtype or (pd.notna(row["REPORT_DATE"]) and row["REPORT_DATE"].month == 12 and row["REPORT_DATE"].day >= 28):
                annuals.append(row)
        if len(annuals) >= 1:
            a0 = annuals[0]
            rev0 = _safe_float(a0.get("TOTAL_OPERATE_INCOME"))
            cost0 = _safe_float(a0.get("OPERATE_COST"))
            if rev0 and cost0 is not None and rev0 != 0:
                gross_margin = (rev0 - cost0) / rev0 * 100  # 用年报毛利率更稳
                out["gross_margin_period"] = str(a0.get("REPORT_DATE_NAME") or a0.get("REPORT_DATE"))
            if len(annuals) >= 2:
                a1 = annuals[1]
                rev1 = _safe_float(a1.get("TOTAL_OPERATE_INCOME"))
                cost1 = _safe_float(a1.get("OPERATE_COST"))
                if rev1 and cost1 is not None and rev1 != 0:
                    gross_margin_prev = (rev1 - cost1) / rev1 * 100

    # 应收同比：用两期资产负债表
    receivable_yoy = None
    if bal is not None and not bal.empty and "REPORT_DATE" in bal.columns and receivable is not None:
        b = bal.copy()
        b["REPORT_DATE"] = pd.to_datetime(b["REPORT_DATE"], errors="coerce")
        b = b.sort_values("REPORT_DATE", ascending=False)
        if len(b) >= 5:
            # 约一年前同期：找报告日差 360±60 天
            t0 = b.iloc[0]["REPORT_DATE"]
            for _, row in b.iloc[1:].iterrows():
                t1 = row["REPORT_DATE"]
                if pd.isna(t0) or pd.isna(t1):
                    continue
                days = abs((t0 - t1).days)
                if 300 <= days <= 430:
                    prev_ar = _safe_float(row.get("ACCOUNTS_RECE"))
                    if prev_ar and prev_ar != 0:
                        receivable_yoy = (receivable - prev_ar) / abs(prev_ar) * 100
                    break

    ocf_to_profit = None
    if netprofit is not None and netprofit != 0 and ocf is not None:
        ocf_to_profit = ocf / netprofit

    out.update({
        "report_name": str(pr.get("REPORT_DATE_NAME") or pr.get("REPORT_DATE") or ""),
        "revenue": revenue,
        "revenue_yoy": revenue_yoy,
        "netprofit": netprofit,
        "netprofit_yoy": netprofit_yoy,
        "ocf": ocf,
        "ocf_to_profit": ocf_to_profit,
        "receivable": receivable,
        "receivable_yoy": receivable_yoy,
        "gross_margin": gross_margin,
        "gross_margin_prev": gross_margin_prev,
        "source": "eastmoney_em",
    })
    cache.set_fund_cache(code, out)
    return out


def evaluate_fundamentals(code: str, name: str = "") -> FundamentalVerdict:
    """输出 F0/F1 裁决。"""
    from data.source import normalize_code

    code = normalize_code(code)
    if is_etf_or_fund(code, name):
        return FundamentalVerdict(
            code=code,
            skip=True,
            level="skip",
            forbid_buy=False,
            reasons=["ETF/场内基金：跳过经营业绩过滤"],
            metrics={},
            source="skip",
        )

    # F0：名称合规
    n = (name or "").replace(" ", "")
    nu = n.upper()
    if "退" in n and ("市" in n or "整" in n):
        return FundamentalVerdict(
            code=code,
            skip=False,
            level="red",
            forbid_buy=True,
            reasons=["F0：名称含退市相关风险警示 → 禁止买入/加仓"],
            metrics={"name": name},
            source="name",
        )

    metrics = fetch_fundamental_metrics(code)
    if metrics.get("error"):
        return FundamentalVerdict(
            code=code,
            skip=False,
            level="unknown",
            forbid_buy=False,
            reasons=[f"F1：财务数据不可用（{metrics['error']}）→ 不否决，降低置信度"],
            metrics=metrics,
            source="error",
        )

    reasons: list[str] = []
    level: FundLevel = "pass"
    forbid_buy = False

    # ST 在 F0 中再强调一次（与 P2 叠加）
    if "ST" in nu or n.startswith("*ST"):
        level = "red"
        forbid_buy = True
        reasons.append("F0：ST/*ST 标的 → 禁止买入/加仓（合规层）")

    netprofit = metrics.get("netprofit")
    ocf = metrics.get("ocf")
    ocf_to_profit = metrics.get("ocf_to_profit")
    revenue_yoy = metrics.get("revenue_yoy")
    receivable_yoy = metrics.get("receivable_yoy")
    gm = metrics.get("gross_margin")
    gm_prev = metrics.get("gross_margin_prev")

    # F1 红灯：盈利但经营现金流为负
    if netprofit is not None and netprofit > 0 and ocf is not None and ocf < 0:
        level = "red"
        forbid_buy = True
        reasons.append(
            f"F1 红灯：净利润 {netprofit/1e8:.2f} 亿>0 但经营现金流 {ocf/1e8:.2f} 亿<0 → 禁止买入/加仓"
        )

    # F1 黄灯：现金流/净利过低
    if (
        not forbid_buy
        and ocf_to_profit is not None
        and netprofit is not None
        and netprofit > 0
        and ocf_to_profit < OCF_TO_PROFIT_YELLOW
    ):
        level = "yellow"
        forbid_buy = True  # 黄灯：禁止加仓/新建（与设计一致）
        reasons.append(
            f"F1 黄灯：经营现金流/净利润={ocf_to_profit:.2f}<{OCF_TO_PROFIT_YELLOW} → 禁止加仓"
        )

    # F1 黄灯：应收增速远快于营收
    if (
        revenue_yoy is not None
        and receivable_yoy is not None
        and (receivable_yoy - revenue_yoy) > RECEIVABLE_VS_REVENUE_YOY_GAP
    ):
        if level == "pass":
            level = "yellow"
        forbid_buy = True
        reasons.append(
            f"F1 黄灯：应收同比 {receivable_yoy:.1f}% - 营收同比 {revenue_yoy:.1f}% "
            f"> {RECEIVABLE_VS_REVENUE_YOY_GAP}pp → 禁止加仓"
        )

    # F1 黄灯：毛利率同比骤降
    if gm is not None and gm_prev is not None and (gm_prev - gm) >= GROSS_MARGIN_DROP_PP:
        if level == "pass":
            level = "yellow"
        forbid_buy = True
        reasons.append(
            f"F1 黄灯：毛利率 {gm:.1f}% 较上年 {gm_prev:.1f}% 下降超过 {GROSS_MARGIN_DROP_PP}pp → 禁止加仓"
        )

    if not reasons:
        parts = []
        if metrics.get("report_name"):
            parts.append(str(metrics["report_name"]))
        if netprofit is not None:
            parts.append(f"净利 {netprofit/1e8:.2f} 亿")
        if ocf is not None:
            parts.append(f"经营现金流 {ocf/1e8:.2f} 亿")
        if ocf_to_profit is not None:
            parts.append(f"现金流/净利 {ocf_to_profit:.2f}")
        if revenue_yoy is not None:
            parts.append(f"营收同比 {revenue_yoy:.1f}%")
        reasons.append("F1 通过：" + ("，".join(parts) if parts else "关键质量指标未见红黄灯"))

    return FundamentalVerdict(
        code=code,
        skip=False,
        level=level,
        forbid_buy=forbid_buy,
        reasons=reasons,
        metrics=metrics,
        source=str(metrics.get("source") or "eastmoney_em"),
    )
