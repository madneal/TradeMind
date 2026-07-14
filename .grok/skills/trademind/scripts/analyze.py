#!/usr/bin/env python3
"""TradeMind 无 API 分析入口：直接跑本地工具，输出 JSON 供 Grok 解读。

用法（在 TradeMind 项目根目录）:
  uv run python .grok/skills/trademind/scripts/analyze.py
  uv run python .grok/skills/trademind/scripts/analyze.py --mode portfolio
  uv run python .grok/skills/trademind/scripts/analyze.py --mode quote --code 518880
  uv run python .grok/skills/trademind/scripts/analyze.py --mode indicators --code 518880 --indicators MA,MACD,RSI
  uv run python .grok/skills/trademind/scripts/analyze.py --mode kline --code 600418 --days 60
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 保证从任意 cwd 都能 import 项目包
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def mode_portfolio() -> dict:
    import tools  # noqa: F401
    from tools.portfolio import get_portfolio, analyze_pnl, analyze_portfolio_risk

    return {
        "mode": "portfolio",
        "overview": get_portfolio(),
        "pnl": analyze_pnl(),
        "risk": analyze_portfolio_risk(),
        "notes": [
            "若某些代码 price=0，说明行情源未拉到（常见于部分 159 开头 ETF），解读时请标注数据缺失。",
            "不要给出绝对买卖建议，用偏多/偏空/震荡、仓位结构风险等表述。",
        ],
    }


def mode_quote(code: str) -> dict:
    import tools  # noqa: F401
    from tools.market import get_quote

    return {"mode": "quote", "code": code, "data": get_quote(code)}


def mode_kline(code: str, days: int) -> dict:
    import tools  # noqa: F401
    from tools.market import get_kline

    return {"mode": "kline", "code": code, "days": days, "data": get_kline(code, days=days)}


def mode_indicators(code: str, indicators: list[str], days: int) -> dict:
    import tools  # noqa: F401
    from tools.indicators import calc_indicators

    return {
        "mode": "indicators",
        "code": code,
        "indicators": indicators,
        "data": calc_indicators(code, indicators=indicators, days=days),
    }


def mode_signals(code: str = "", days: int = 90) -> dict:
    from strategy.engine import evaluate_code, evaluate_portfolio

    if code:
        return {"mode": "signals", "data": evaluate_code(code, days=days).to_dict()}
    return {"mode": "signals", "data": evaluate_portfolio(days=days)}


def main() -> int:
    parser = argparse.ArgumentParser(description="TradeMind local analysis (no LLM API)")
    parser.add_argument(
        "--mode",
        choices=["portfolio", "quote", "kline", "indicators", "signals", "all"],
        default="portfolio",
        help="分析模式，默认 portfolio；signals=固定策略买卖决策",
    )
    parser.add_argument("--code", default="", help="股票/ETF 代码（6 位）")
    parser.add_argument("--days", type=int, default=60, help="K 线/指标回溯天数")
    parser.add_argument(
        "--indicators",
        default="MA,MACD,RSI,KDJ,BOLL",
        help="逗号分隔指标，默认全部",
    )
    args = parser.parse_args()

    try:
        if args.mode in ("portfolio", "all"):
            _dump(mode_portfolio())
            if args.mode == "portfolio":
                return 0

        if args.mode in ("signals", "all"):
            _dump(mode_signals(args.code, days=args.days))
            if args.mode == "signals":
                return 0

        if args.mode in ("quote", "all"):
            if not args.code:
                raise SystemExit("--mode quote/all 需要 --code")
            _dump(mode_quote(args.code))

        if args.mode in ("kline", "all"):
            if not args.code:
                raise SystemExit("--mode kline/all 需要 --code")
            _dump(mode_kline(args.code, args.days))

        if args.mode in ("indicators", "all"):
            if not args.code:
                raise SystemExit("--mode indicators/all 需要 --code")
            inds = [x.strip().upper() for x in args.indicators.split(",") if x.strip()]
            _dump(mode_indicators(args.code, inds, args.days))
    except Exception as e:
        _dump({"error": f"{type(e).__name__}: {e}"})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
