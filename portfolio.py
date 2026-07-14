"""持仓管理：TOML 配置文件加载/保存 + 增删改查。

持仓文件格式 (holdings.toml):
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


def load_positions(path: Path | str | None = None) -> list[Position]:
    """从 TOML 读取持仓列表。文件不存在返回空列表。"""
    path = Path(path or HOLDINGS_PATH)
    if not path.exists():
        return []
    with open(path, "rb") as f:
        data = tomllib.load(f)
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


def save_positions(positions: list[Position], path: Path | str | None = None) -> None:
    """保存持仓到 TOML。"""
    path = Path(path or HOLDINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"positions": [p.to_dict() for p in positions]}
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


def remove_position(code: str, path: Path | str | None = None) -> bool:
    """删除持仓，返回是否删除成功。"""
    code = normalize_code(code)
    positions = load_positions(path)
    before = len(positions)
    positions = [p for p in positions if p.code != code]
    if len(positions) < before:
        save_positions(positions, path)
        return True
    return False
