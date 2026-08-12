"""自选股：watchlist.toml（本地，可 gitignore）。"""

from __future__ import annotations

import tomllib
from pathlib import Path

from config import HOLDINGS_PATH
from data.source import normalize_code

# 与 holdings 同目录
WATCHLIST_PATH = Path(HOLDINGS_PATH).resolve().parent / "watchlist.toml"


def load_watchlist(path: Path | str | None = None) -> list[str]:
    path = Path(path or WATCHLIST_PATH)
    if not path.exists():
        return []
    with open(path, "rb") as f:
        data = tomllib.load(f)
    codes = []
    for c in data.get("codes") or []:
        codes.append(normalize_code(str(c)))
    # 去重保序
    seen = set()
    out = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def save_watchlist(codes: list[str], path: Path | str | None = None) -> None:
    import tomli_w

    path = Path(path or WATCHLIST_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    uniq = []
    seen = set()
    for c in codes:
        c = normalize_code(str(c))
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    with open(path, "wb") as f:
        tomli_w.dump({"codes": uniq}, f)


def add_watch(codes: list[str] | str, path: Path | str | None = None) -> list[str]:
    if isinstance(codes, str):
        import re

        parts = re.split(r"[\s,，;；]+", codes.strip())
        codes = [p for p in parts if p]
    cur = load_watchlist(path)
    for c in codes:
        c = normalize_code(c)
        if c not in cur:
            cur.append(c)
    save_watchlist(cur, path)
    return cur


def remove_watch(code: str, path: Path | str | None = None) -> list[str]:
    code = normalize_code(code)
    cur = [c for c in load_watchlist(path) if c != code]
    save_watchlist(cur, path)
    return cur
