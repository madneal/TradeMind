"""持仓管理：TOML 配置文件加载/保存 + 增删改查。

持仓文件格式 (holdings.toml):
    cash = 10000.0          # 可选：可用/资金余额（元）

    [[positions]]
    code = "600519"
    shares = 100
    cost_price = 1500.50
"""

from __future__ import annotations

import tomllib
import tomli_w
from dataclasses import dataclass, asdict
from pathlib import Path

from config import HOLDINGS_PATH
from data.source import normalize_code


@dataclass
class Position:
    code: str          # 6 位代码
    shares: int        # 持仓股数
    cost_price: float  # 买入成本价

    def to_dict(self) -> dict:
        return asdict(self)


def _load_raw(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_cash(path: Path | str | None = None) -> float | None:
    """读取资金余额；未配置则返回 None。"""
    path = Path(path or HOLDINGS_PATH)
    data = _load_raw(path)
    if "cash" not in data:
        return None
    try:
        return float(data["cash"])
    except (TypeError, ValueError):
        return None


def load_positions(path: Path | str | None = None) -> list[Position]:
    """从 TOML 读取持仓列表。文件不存在返回空列表。"""
    path = Path(path or HOLDINGS_PATH)
    data = _load_raw(path)
    positions = []
    for p in data.get("positions", []):
        positions.append(
            Position(
                code=normalize_code(p["code"]),
                shares=int(p["shares"]),
                cost_price=float(p["cost_price"]),
            )
        )
    return positions


def save_positions(
    positions: list[Position],
    path: Path | str | None = None,
    cash: float | None = None,
) -> None:
    """保存持仓到 TOML。

    cash=None 时保留文件中已有的 cash；显式传入则覆盖。
    """
    path = Path(path or HOLDINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_raw(path)
    data: dict = {"positions": [p.to_dict() for p in positions]}
    if cash is not None:
        data["cash"] = float(cash)
    elif "cash" in existing:
        data["cash"] = existing["cash"]
    with open(path, "wb") as f:
        tomli_w.dump(data, f)


def add_position(code: str, shares: int, cost_price: float, path: Path | str | None = None) -> None:
    """新增或更新持仓（同代码则累加股数、重算成本）。"""
    code = normalize_code(code)
    positions = load_positions(path)
    for p in positions:
        if p.code == code:
            # 已持有：合并成本价（按股数加权）
            total_shares = p.shares + shares
            p.cost_price = (p.cost_price * p.shares + cost_price * shares) / total_shares
            p.shares = total_shares
            save_positions(positions, path)
            return
    positions.append(Position(code=code, shares=shares, cost_price=cost_price))
    save_positions(positions, path)


def remove_position(
    code: str,
    path: Path | str | None = None,
    *,
    record_closed: bool = False,
    exit_price: float | None = None,
    note: str = "",
) -> bool:
    """删除持仓，返回是否删除成功。

    record_closed=True 时写入 closed.toml（需 exit_price）。
    """
    code = normalize_code(code)
    positions = load_positions(path)
    removed: Position | None = None
    kept: list[Position] = []
    for p in positions:
        if p.code == code:
            removed = p
        else:
            kept.append(p)
    if removed is None:
        return False
    save_positions(kept, path)
    if record_closed and exit_price is not None:
        try:
            from closed_ledger import add_closed
            from data.source import get_quote

            name = ""
            try:
                name = (get_quote(code) or {}).get("name") or ""
            except Exception:
                pass
            add_closed(
                code,
                removed.shares,
                removed.cost_price,
                float(exit_price),
                name=name,
                note=note,
            )
        except Exception:
            pass
    return True
