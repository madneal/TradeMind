"""Mac 同花顺本地历史成交（Lscj）辅助解析 — 非持仓主源。

主持仓请维护 holdings.toml（截图 / portfolio add）。

Mac 实测：实时持仓不落盘；仅 XcsLscjDataFile 可部分轧差重建（窗口外底仓会少）。
已放弃 Frida/进程注入抓包（需削弱系统防护，ROI 低）。

路径：
  ~/Library/Containers/cn.com.10jqka.macstockPro/Data/Documents/XcsFold/
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Literal

from data.source import normalize_code

# Mac 同花顺 sandbox 默认路径
DEFAULT_THS_DOCS = Path.home() / (
    "Library/Containers/cn.com.10jqka.macstockPro/Data/Documents"
)
DEFAULT_LSCJ_DIR = DEFAULT_THS_DOCS / "XcsFold"

# 不计入权益持仓的操作 / 代码
_SKIP_ACTIONS = frozenset(
    {
        "",
        "红股派息",
        "配售申购",
        "报价回购终止",
        "新股申购",
        "新股中签",
    }
)
# 国债逆回购等（204/131 沪深逆回购，205 报价回购等）
_REPO_PREFIXES = ("204", "131", "205")


@dataclass
class TradeFill:
    account_id: str
    code: str
    trade_date: str  # YYYYMMDD
    trade_time: str
    action: str
    price: float
    quantity: float
    source_file: str


@dataclass
class RebuiltPosition:
    code: str
    shares: float
    cost_price: float
    buy_shares: float = 0.0
    sell_shares: float = 0.0
    accounts: list[str] = field(default_factory=list)
    # 流水内第一笔有效成交是否为卖出 → 说明窗口前已有底仓，股数可能偏低
    history_incomplete: bool = False
    first_date: str = ""
    last_date: str = ""


@dataclass
class MergeRow:
    code: str
    final_shares: int
    final_cost: float
    ths_shares: int
    ths_cost: float
    local_shares: int
    local_cost: float
    action: str  # keep / add / update / prefer_local / prefer_ths / remove
    note: str


def discover_lscj_files(lscj_dir: Path | str | None = None) -> list[Path]:
    """发现 XcsLscjDataFile_* 文件，按修改时间新→旧排序。"""
    root = Path(lscj_dir or os.getenv("TRADEMIND_THS_LSCJ_DIR") or DEFAULT_LSCJ_DIR)
    if not root.is_dir():
        return []
    files = [p for p in root.iterdir() if p.is_file() and p.name.startswith("XcsLscjDataFile_")]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


def probe_local_sources(docs_dir: Path | str | None = None) -> dict:
    """探测 Mac 同花顺本地目录：哪些像持仓源、实际能否用。

    不解析敏感成交明细正文，只报告路径/大小/结论。
    """
    docs = Path(docs_dir or DEFAULT_THS_DOCS)
    container = docs.parent.parent if docs.name == "Documents" else docs
    lscj_dir = docs / "XcsFold"
    lscj = discover_lscj_files(lscj_dir)

    candidates = [
        {
            "name": "XcsLscjDataFile（历史成交）",
            "path": str(lscj_dir),
            "usable_for_holdings": "partial",
            "detail": f"找到 {len(lscj)} 个文件；可重建流水内持仓，窗口外底仓会缺失",
            "files": [
                {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
                for p in lscj
            ],
        },
        {
            "name": "实时持仓表（ChiCang / TradeDataTable）",
            "path": "(内存，无持久化文件)",
            "usable_for_holdings": False,
            "detail": (
                "App 通过 requestChiCangGu 拉取，存 CTradeDataTableNew/CCChicangData；"
                "shouldClearTradeDataWithAppClose 表明退出清空，磁盘无对应 XcsChiCang 文件"
            ),
            "files": [],
        },
        {
            "name": "recentBrowseAndSelfStock（自选/浏览）",
            "path": str(docs / "recentBrowseAndSelfStock"),
            "usable_for_holdings": False,
            "detail": "最近浏览/自选代码列表，无股数与成本",
            "files": _list_files(docs / "recentBrowseAndSelfStock"),
        },
        {
            "name": "cloud_store/blockstock（云自选块）",
            "path": str(docs / "cloud_store"),
            "usable_for_holdings": False,
            "detail": "自选分组同步，非券商持仓",
            "files": _list_files(docs / "cloud_store", max_files=20),
        },
        {
            "name": "cifox_trade*.log（交易日志）",
            "path": str(docs),
            "usable_for_holdings": False,
            "detail": "会话/协议日志，实测无「代码+股数」可解析持仓表",
            "files": [
                {"name": p.name, "size": p.stat().st_size, "mtime": p.stat().st_mtime}
                for p in sorted(docs.glob("cifox_trade*.log"), key=lambda x: x.stat().st_mtime, reverse=True)[:5]
            ],
        },
        {
            "name": "TableScheme / WidgetSetting（UI 方案）",
            "path": str(docs / "TableSchemeSettings"),
            "usable_for_holdings": False,
            "detail": "仅含 ChiCang 表头/界面配置字符串，无持仓数值",
            "files": _list_files(docs / "TableSchemeSettings", max_files=10)
            + _list_files(docs / "PKLocalSettings", max_files=5),
        },
    ]

    return {
        "container": str(container),
        "docs_dir": str(docs),
        "docs_exists": docs.is_dir(),
        "conclusion": (
            "Mac 同花顺本地没有完整实时持仓文件；"
            "仅历史成交 XcsLscj 可部分重建，建议以券商截图/手动维护 holdings.toml 为准，"
            "Lscj 仅作辅助校验。"
        ),
        "candidates": candidates,
    }


def _list_files(path: Path, max_files: int = 20) -> list[dict]:
    if not path.exists():
        return []
    out = []
    if path.is_file():
        st = path.stat()
        return [{"name": path.name, "size": st.st_size, "mtime": st.st_mtime}]
    for p in sorted(path.rglob("*")):
        if not p.is_file():
            continue
        st = p.stat()
        out.append({"name": str(p.relative_to(path)), "size": st.st_size, "mtime": st.st_mtime})
        if len(out) >= max_files:
            break
    return out


def _parse_account_id(file_name: str) -> str:
    # XcsLscjDataFile_<account>_<userid>
    parts = file_name.split("_")
    return parts[1] if len(parts) >= 3 else ""


def _is_buy(action: str) -> bool:
    # 买入 / 证券买入 / 报价回购买入 — 逆回购买入已在调用侧按代码过滤
    return "买" in action and "卖" not in action


def _is_sell(action: str) -> bool:
    return "卖" in action


def _is_repo_code(code: str) -> bool:
    return code.startswith(_REPO_PREFIXES)


def load_fills(paths: Iterable[Path] | None = None) -> list[TradeFill]:
    """读取历史成交 JSON，返回扁平成交列表。"""
    files = list(paths) if paths is not None else discover_lscj_files()
    fills: list[TradeFill] = []
    for path in files:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        account_id = _parse_account_id(path.name)
        for bucket, date_map in data.items():
            if bucket == "startdate" or not isinstance(date_map, dict):
                continue
            for date_key, records in date_map.items():
                if not isinstance(records, list):
                    continue
                for rec in records:
                    if not isinstance(rec, dict):
                        continue
                    code = str(rec.get("zqdm") or "").strip()
                    action = str(rec.get("czmc") or "").strip()
                    try:
                        qty = float(rec.get("cjsl") or 0)
                        price = float(rec.get("cjjg") or 0)
                    except (TypeError, ValueError):
                        continue
                    if not code or qty <= 0 or action in _SKIP_ACTIONS:
                        continue
                    if _is_repo_code(code):
                        continue
                    if not (_is_buy(action) or _is_sell(action)):
                        continue
                    try:
                        code = normalize_code(code)
                    except ValueError:
                        continue
                    fills.append(
                        TradeFill(
                            account_id=account_id,
                            code=code,
                            trade_date=str(rec.get("cjrq") or date_key),
                            trade_time=str(rec.get("cjsj") or ""),
                            action=action,
                            price=price,
                            quantity=qty,
                            source_file=path.name,
                        )
                    )
    fills.sort(key=lambda t: (t.account_id, t.trade_date, t.trade_time, t.code))
    return fills


def _rebuild_one_account(fills: list[TradeFill]) -> dict[str, RebuiltPosition]:
    """单资金账号内按时间顺序重建：买入加权成本，卖出减仓（成本价不变）。"""
    ordered = sorted(fills, key=lambda t: (t.trade_date, t.trade_time, t.code))
    state: dict[str, dict] = {}
    for t in ordered:
        st = state.setdefault(
            t.code,
            {
                "shares": 0.0,
                "cost": 0.0,
                "buy": 0.0,
                "sell": 0.0,
                "first_sell": False,
                "saw_trade": False,
                "first_date": t.trade_date,
                "last_date": t.trade_date,
                "accounts": set(),
            },
        )
        st["last_date"] = t.trade_date
        st["accounts"].add(t.account_id)
        if not st["saw_trade"]:
            st["saw_trade"] = True
            st["first_date"] = t.trade_date
            if _is_sell(t.action):
                st["first_sell"] = True  # 窗口前必有底仓
        if _is_buy(t.action):
            if st["shares"] <= 1e-9:
                st["shares"] = t.quantity
                st["cost"] = t.price
            else:
                total = st["shares"] + t.quantity
                st["cost"] = (st["cost"] * st["shares"] + t.price * t.quantity) / total
                st["shares"] = total
            st["buy"] += t.quantity
        else:
            st["shares"] -= t.quantity
            st["sell"] += t.quantity
            if st["shares"] < 1e-6:
                st["shares"] = 0.0
                st["cost"] = 0.0

    out: dict[str, RebuiltPosition] = {}
    for code, st in state.items():
        if st["shares"] <= 0.5:
            continue
        out[code] = RebuiltPosition(
            code=code,
            shares=st["shares"],
            cost_price=float(st["cost"]),
            buy_shares=st["buy"],
            sell_shares=st["sell"],
            accounts=sorted(st["accounts"]),
            history_incomplete=bool(st["first_sell"]),
            first_date=st["first_date"],
            last_date=st["last_date"],
        )
    return out


def rebuild_positions(fills: list[TradeFill] | None = None) -> dict[str, RebuiltPosition]:
    """多账号分别重建后合并股数；成本按股数加权。"""
    if fills is None:
        fills = load_fills()
    by_acct: dict[str, list[TradeFill]] = {}
    for t in fills:
        by_acct.setdefault(t.account_id or "_", []).append(t)

    merged: dict[str, RebuiltPosition] = {}
    for acct, acct_fills in by_acct.items():
        part = _rebuild_one_account(acct_fills)
        for code, pos in part.items():
            if code not in merged:
                merged[code] = RebuiltPosition(
                    code=code,
                    shares=pos.shares,
                    cost_price=pos.cost_price,
                    buy_shares=pos.buy_shares,
                    sell_shares=pos.sell_shares,
                    accounts=list(pos.accounts) or [acct],
                    history_incomplete=pos.history_incomplete,
                    first_date=pos.first_date,
                    last_date=pos.last_date,
                )
                continue
            m = merged[code]
            total = m.shares + pos.shares
            if total > 0:
                m.cost_price = (m.cost_price * m.shares + pos.cost_price * pos.shares) / total
            m.shares = total
            m.buy_shares += pos.buy_shares
            m.sell_shares += pos.sell_shares
            for a in pos.accounts or [acct]:
                if a not in m.accounts:
                    m.accounts.append(a)
            m.history_incomplete = m.history_incomplete or pos.history_incomplete
            if pos.first_date and (not m.first_date or pos.first_date < m.first_date):
                m.first_date = pos.first_date
            if pos.last_date and pos.last_date > m.last_date:
                m.last_date = pos.last_date
    return merged


MergeMode = Literal["smart", "rebuild", "prefer-local", "prefer-ths"]


def merge_with_local(
    ths: dict[str, RebuiltPosition],
    local: dict[str, tuple[int, float]],
    *,
    mode: MergeMode = "smart",
    update_cost: bool = False,
    prune_missing: bool = False,
) -> list[MergeRow]:
    """将同花顺重建结果与本地 holdings 合并。

    mode:
      - smart: 股数一致保留本地成本；同花顺更大则采用同花顺；
               同花顺更小则默认保留本地（历史窗口不全），并标注。
      - rebuild: 完全以同花顺重建为准
      - prefer-local: 两边都有时保留本地
      - prefer-ths: 两边都有时采用同花顺
    """
    codes = sorted(set(ths) | set(local))
    rows: list[MergeRow] = []
    for code in codes:
        tp = ths.get(code)
        ths_sh = int(round(tp.shares)) if tp else 0
        ths_c = float(tp.cost_price) if tp else 0.0
        loc_sh, loc_c = local.get(code, (0, 0.0))

        if mode == "rebuild":
            if ths_sh <= 0:
                if prune_missing and loc_sh > 0:
                    rows.append(
                        MergeRow(
                            code, 0, 0.0, ths_sh, ths_c, loc_sh, loc_c, "remove", "rebuild 且无持仓"
                        )
                    )
                continue
            note = "纯历史成交重建"
            if tp and tp.history_incomplete:
                note += "（流水首笔为卖，底仓可能不全）"
            rows.append(
                MergeRow(
                    code,
                    ths_sh,
                    ths_c,
                    ths_sh,
                    ths_c,
                    loc_sh,
                    loc_c,
                    "add" if loc_sh == 0 else "update",
                    note,
                )
            )
            continue

        if mode == "prefer-local":
            if loc_sh > 0:
                rows.append(
                    MergeRow(
                        code,
                        loc_sh,
                        loc_c,
                        ths_sh,
                        ths_c,
                        loc_sh,
                        loc_c,
                        "keep",
                        "优先本地",
                    )
                )
            elif ths_sh > 0:
                rows.append(
                    MergeRow(
                        code, ths_sh, ths_c, ths_sh, ths_c, loc_sh, loc_c, "add", "本地无，采用同花顺"
                    )
                )
            continue

        if mode == "prefer-ths":
            if ths_sh > 0:
                rows.append(
                    MergeRow(
                        code,
                        ths_sh,
                        ths_c,
                        ths_sh,
                        ths_c,
                        loc_sh,
                        loc_c,
                        "add" if loc_sh == 0 else "update",
                        "优先同花顺",
                    )
                )
            elif loc_sh > 0 and not prune_missing:
                rows.append(
                    MergeRow(
                        code, loc_sh, loc_c, ths_sh, ths_c, loc_sh, loc_c, "keep", "同花顺无记录，保留本地"
                    )
                )
            elif loc_sh > 0 and prune_missing:
                rows.append(
                    MergeRow(code, 0, 0.0, ths_sh, ths_c, loc_sh, loc_c, "remove", "同花顺无，剔除")
                )
            continue

        # ── smart ──
        if ths_sh <= 0 and loc_sh > 0:
            rows.append(
                MergeRow(
                    code,
                    loc_sh,
                    loc_c,
                    ths_sh,
                    ths_c,
                    loc_sh,
                    loc_c,
                    "keep",
                    "同花顺无持仓记录，保留本地",
                )
            )
            continue
        if ths_sh > 0 and loc_sh <= 0:
            note = "本地无，新增"
            if tp and tp.history_incomplete:
                note += "（历史可能不全）"
            rows.append(
                MergeRow(code, ths_sh, ths_c, ths_sh, ths_c, loc_sh, loc_c, "add", note)
            )
            continue

        # both exist
        if ths_sh == loc_sh:
            cost = ths_c if update_cost else loc_c
            note = "股数一致"
            if update_cost:
                note += "，成本改用成交加权"
            else:
                note += "，保留本地成本（券商成本通常更准）"
            act = "update" if update_cost and abs(cost - loc_c) > 1e-6 else "keep"
            rows.append(
                MergeRow(code, loc_sh, cost, ths_sh, ths_c, loc_sh, loc_c, act, note)
            )
        elif ths_sh > loc_sh:
            rows.append(
                MergeRow(
                    code,
                    ths_sh,
                    ths_c if update_cost or loc_sh == 0 else loc_c,
                    ths_sh,
                    ths_c,
                    loc_sh,
                    loc_c,
                    "update",
                    f"同花顺股数更大（+{ths_sh - loc_sh}），采用同花顺"
                    + ("；成本沿用本地" if not update_cost and loc_sh > 0 else ""),
                )
            )
            # when not update_cost and loc_sh>0, still using loc_c with larger shares is imperfect
            # but avoids destroying broker cost; user can --update-cost
            if not update_cost and loc_sh > 0:
                rows[-1] = MergeRow(
                    code,
                    ths_sh,
                    loc_c,
                    ths_sh,
                    ths_c,
                    loc_sh,
                    loc_c,
                    "update",
                    f"同花顺股数更大（+{ths_sh - loc_sh}），股数用同花顺、成本暂留本地",
                )
        else:
            # ths < local：默认认为历史成交窗口不全
            incomplete = bool(tp and tp.history_incomplete) or True
            rows.append(
                MergeRow(
                    code,
                    loc_sh,
                    loc_c,
                    ths_sh,
                    ths_c,
                    loc_sh,
                    loc_c,
                    "prefer_local",
                    f"同花顺股数更小（{ths_sh} < {loc_sh}），保留本地"
                    + ("；流水首笔为卖/窗口不全" if incomplete else "")
                    + "。若已卖出请用 --mode prefer-ths",
                )
            )
    return rows


def rows_to_positions(rows: list[MergeRow]):
    """MergeRow → portfolio.Position 列表（延迟导入避免环）。"""
    from portfolio import Position

    positions = []
    for r in rows:
        if r.final_shares <= 0:
            continue
        positions.append(
            Position(
                code=normalize_code(r.code),
                shares=int(r.final_shares),
                cost_price=float(r.final_cost),
            )
        )
    positions.sort(key=lambda p: p.code)
    return positions


def sync_summary(
    *,
    lscj_dir: Path | str | None = None,
    local_positions: list | None = None,
    mode: MergeMode = "smart",
    update_cost: bool = False,
    prune_missing: bool = False,
) -> dict:
    """一站式：发现文件 → 重建 → 合并，返回摘要 dict。"""
    files = discover_lscj_files(lscj_dir)
    fills = load_fills(files)
    ths = rebuild_positions(fills)

    if local_positions is None:
        from portfolio import load_positions

        local_positions = load_positions()
    local_map = {p.code: (int(p.shares), float(p.cost_price)) for p in local_positions}

    rows = merge_with_local(
        ths,
        local_map,
        mode=mode,
        update_cost=update_cost,
        prune_missing=prune_missing,
    )
    accounts = sorted({t.account_id for t in fills if t.account_id})
    dates = [t.trade_date for t in fills if t.trade_date]
    return {
        "lscj_dir": str(Path(lscj_dir or DEFAULT_LSCJ_DIR)),
        "files": [p.name for p in files],
        "accounts": accounts,
        "fill_count": len(fills),
        "date_min": min(dates) if dates else "",
        "date_max": max(dates) if dates else "",
        "ths_positions": ths,
        "rows": rows,
        "positions": rows_to_positions(rows),
    }
