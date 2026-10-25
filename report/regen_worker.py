"""子进程入口：生成持仓 HTML 报告。

与 `trademind serve` 进程隔离，避免 akshare/py_mini_racer (V8) 崩溃
（macOS SIGTRAP）拖死 HTTP 服务。

用法（一般由 report.server 调用）::

    python -m report.regen_worker [--signals] [--days 90]
"""

from __future__ import annotations

import argparse
import sys
import time


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TradeMind 报告生成子进程")
    parser.add_argument(
        "--signals",
        action="store_true",
        help="含固定策略信号（完整生成）",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=90,
        help="策略技术回溯天数",
    )
    args = parser.parse_args(argv)

    t0 = time.time()
    try:
        from data.cache import invalidate_quote_cache
        from portfolio import load_positions

        invalidate_quote_cache([p.code for p in load_positions()])
    except Exception as e:
        print(f"[regen-worker] invalidate cache skipped: {e}", file=sys.stderr)

    try:
        from report.html_report import write_portfolio_report

        path = write_portfolio_report(
            None,
            include_signals=bool(args.signals),
            include_market=bool(args.signals),
            days=int(args.days),
            open_browser=False,
        )
    except Exception as e:
        print(f"[regen-worker] FAILED: {e}", file=sys.stderr)
        return 1

    elapsed = time.time() - t0
    print(f"[regen-worker] ok signals={bool(args.signals)} {elapsed:.2f}s → {path}", file=sys.stderr)
    # 最后一行 stdout 供父进程解析路径
    print(str(path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
