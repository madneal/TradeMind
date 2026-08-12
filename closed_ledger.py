"""已清仓账本：closed.toml（复盘用，不参与市值）。"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from config import HOLDINGS_PATH
from data.source import normalize_code

CLOSED_PATH = Path(HOLDINGS_PATH).resolve().parent / "closed.toml"


@dataclass
class ClosedPosition:
    code: str
    name: str = ""
    shares: int = 0
    cost_price: float = 0.0
    exit_price: float = 0.0
    closed_date: str = ""
    note: str = ""

    @property
    def pnl_pct(self) -> float | None:
        if not self.cost_price:
            return None
        return round((self.exit_price - self.cost_price) / self.cost_price * 100, 2)


def load_closed(path: Path | str | None = None) -> list[ClosedPosition]:
    path = Path(path or CLOSED_PATH)
    if not path.exists():
        return []
    with open(path, "rb") as f:
        data = tomllib.load(f)
    rows = []
    for p in data.get("closed") or []:
        rows.append(
            ClosedPosition(
                code=normalize_code(str(p.get("code", ""))),
                name=str(p.get("name") or ""),
                shares=int(p.get("shares") or 0),
                cost_price=float(p.get("cost_price") or 0),
                exit_price=float(p.get("exit_price") or 0),
                closed_date=str(p.get("closed_date") or ""),
                note=str(p.get("note") or ""),
            )
        )
    return rows


def save_closed(rows: list[ClosedPosition], path: Path | str | None = None) -> None:
    import tomli_w

    path = Path(path or CLOSED_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "closed": [
            {
                "code": r.code,
                "name": r.name,
                "shares": r.shares,
                "cost_price": r.cost_price,
                "exit_price": r.exit_price,
                "closed_date": r.closed_date,
                "note": r.note,
            }
            for r in rows
        ]
    }
    with open(path, "wb") as f:
        tomli_w.dump(payload, f)


def add_closed(
    code: str,
    shares: int,
    cost_price: float,
    exit_price: float,
    *,
    name: str = "",
    note: str = "",
    closed_date: str | None = None,
    path: Path | str | None = None,
) -> ClosedPosition:
    rows = load_closed(path)
    row = ClosedPosition(
        code=normalize_code(code),
        name=name,
        shares=shares,
        cost_price=cost_price,
        exit_price=exit_price,
        closed_date=closed_date or date.today().isoformat(),
        note=note,
    )
    rows.append(row)
    save_closed(rows, path)
    return row
