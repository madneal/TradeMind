"""TradeMind CLI 入口。

命令：
- uv run trademind chat "分析一下贵州茅台"   单次查询
- uv run trademind chat                        交互式对话
- uv run trademind portfolio list              查看持仓
- uv run trademind portfolio add 600519 100 1500.5  添加持仓
- uv run trademind portfolio remove 600519     删除持仓
- uv run trademind portfolio sync-ths          从历史成交 Lscj 辅助校验/合并（非主源）
- uv run trademind report                      生成持仓 HTML 报告并打开浏览器
- uv run trademind serve                       本地 HTTP 服务托管持仓报告
- uv run trademind signals                     持仓固定策略买卖清单
- uv run trademind signals 518880              单票策略决策
- uv run trademind strategies                  列出固定策略规则
- uv run trademind backtest 518880             单票历史回测（技术规则）
- uv run trademind backtest                    持仓分票历史回测
"""

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

app = typer.Typer(
    help="TradeMind —— A 股票分析 Agent",
    no_args_is_help=False,
    add_completion=False,
)
portfolio_app = typer.Typer(
    help="持仓管理：添加/删除/查看持仓",
    no_args_is_help=True,
    add_completion=False,
)
app.add_typer(portfolio_app, name="portfolio")

console = Console()


# ──────────────────────────── portfolio 子命令 ────────────────────────────


@portfolio_app.command("list")
def portfolio_list():
    """查看当前持仓。"""
    from portfolio import load_positions

    positions = load_positions()
    if not positions:
        console.print("[dim]持仓为空。用 [cyan]trademind portfolio add[/cyan] 添加持仓。[/dim]")
        return

    table = Table(title="当前持仓", show_lines=True)
    table.add_column("代码", style="cyan")
    table.add_column("股数", justify="right")
    table.add_column("成本价", justify="right")
    table.add_column("成本金额", justify="right")
    for p in positions:
        table.add_row(
            p.code,
            str(p.shares),
            f"{p.cost_price:.2f}",
            f"{p.cost_price * p.shares:,.2f}",
        )
    console.print(table)


@portfolio_app.command("add")
def portfolio_add(
    code: str = typer.Argument(..., help="股票代码（6 位）"),
    shares: int = typer.Argument(..., help="持仓股数"),
    cost_price: float = typer.Argument(..., help="买入成本价"),
):
    """添加持仓（已有则合并）。"""
    from portfolio import add_position

    try:
        add_position(code, shares, cost_price)
        console.print(f"[green]✓ 已添加 {code} × {shares} 股，成本价 {cost_price:.2f}[/green]")
    except ValueError as e:
        console.print(f"[red]{e}[/red]")


@portfolio_app.command("remove")
def portfolio_remove(
    code: str = typer.Argument(..., help="要删除的股票代码"),
):
    """删除持仓。"""
    from portfolio import remove_position

    if remove_position(code):
        console.print(f"[green]✓ 已删除 {code}[/green]")
    else:
        console.print(f"[yellow]未找到 {code} 的持仓[/yellow]")


@portfolio_app.command("sync-ths")
def portfolio_sync_ths(
    write: bool = typer.Option(
        False,
        "--write",
        help="写入 holdings.toml（默认只预览 diff）",
    ),
    mode: str = typer.Option(
        "smart",
        "--mode",
        help="合并策略: smart | rebuild | prefer-local | prefer-ths",
    ),
    update_cost: bool = typer.Option(
        False,
        "--update-cost",
        help="股数一致时也用成交加权成本覆盖本地成本",
    ),
    prune_missing: bool = typer.Option(
        False,
        "--prune",
        help="rebuild/prefer-ths 时删除源中无记录的本地持仓",
    ),
    lscj_dir: str | None = typer.Option(
        None,
        "--lscj-dir",
        help="自定义 XcsLscjDataFile 目录（默认 Mac 同花顺 sandbox）",
    ),
    probe: bool = typer.Option(
        False,
        "--probe",
        help="只探测本地有哪些数据源（不重建持仓）",
    ),
):
    """用同花顺本地「历史成交」做辅助校验/合并（非主源）。

    主持仓请维护 holdings.toml（截图/手动）。
    已放弃 Frida/进程注入抓包（风险高、需关闭系统防护，ROI 低）。
    """
    from data.ths_local import probe_local_sources, sync_summary
    from portfolio import save_positions

    if probe:
        info = probe_local_sources()
        console.print(
            Panel(
                f"{info['conclusion']}\n\n目录: {info['docs_dir']}\n存在: {info['docs_exists']}",
                title="同花顺本地探测结论",
                border_style="yellow",
            )
        )
        table = Table(title="候选数据源", show_lines=True)
        table.add_column("名称")
        table.add_column("可否作持仓源")
        table.add_column("说明")
        table.add_column("文件数", justify="right")
        for c in info["candidates"]:
            usable = c["usable_for_holdings"]
            if usable is True:
                u = "[green]是[/green]"
            elif usable == "partial":
                u = "[yellow]部分[/yellow]"
            else:
                u = "[red]否[/red]"
            table.add_row(c["name"], u, c["detail"], str(len(c.get("files") or [])))
        console.print(table)
        console.print(
            "[dim]主持仓请用 holdings.toml；Lscj 仅辅助。已放弃进程注入抓包。[/dim]"
        )
        return

    mode = (mode or "smart").strip().lower()
    if mode not in ("smart", "rebuild", "prefer-local", "prefer-ths"):
        console.print(f"[red]未知 mode={mode}[/red]")
        raise typer.Exit(1)

    summary = sync_summary(
        lscj_dir=lscj_dir,
        mode=mode,  # type: ignore[arg-type]
        update_cost=update_cost,
        prune_missing=prune_missing,
    )
    if not summary["files"]:
        console.print(
            "[red]未找到历史成交 XcsLscjDataFile_*[/red]\n"
            f"[dim]查找目录: {summary['lscj_dir']}[/dim]\n"
            "持仓请直接维护 [cyan]holdings.toml[/cyan] "
            "（portfolio add / 编辑文件）。"
        )
        raise typer.Exit(1)

    console.print(
        Panel(
            f"来源: 历史成交 Lscj（辅助，窗口外底仓可能不全）\n"
            f"目录: {summary['lscj_dir']}\n"
            f"文件: {', '.join(summary['files'])}\n"
            f"账号: {', '.join(summary['accounts']) or '—'}\n"
            f"成交: {summary['fill_count']} 笔  "
            f"区间 {summary['date_min']} → {summary['date_max']}\n"
            f"合并: mode={mode}"
            + ("  update-cost" if update_cost else "")
            + ("  prune" if prune_missing else "")
            + "\n主源: holdings.toml（截图/手动）",
            title="同花顺本地历史成交",
            border_style="cyan",
        )
    )

    table = Table(title="同步预览（相对当前 holdings.toml）", show_lines=False)
    table.add_column("代码", style="cyan")
    table.add_column("动作")
    table.add_column("本地股数", justify="right")
    table.add_column("源股数", justify="right")
    table.add_column("最终股数", justify="right")
    table.add_column("本地成本", justify="right")
    table.add_column("最终成本", justify="right")
    table.add_column("说明")

    changed = 0
    for r in summary["rows"]:
        if r.action != "keep":
            changed += 1
        style = {
            "add": "green",
            "update": "yellow",
            "prefer_local": "magenta",
            "prefer_ths": "yellow",
            "remove": "red",
            "keep": "dim",
        }.get(r.action, "")
        table.add_row(
            r.code,
            f"[{style}]{r.action}[/{style}]" if style else r.action,
            str(r.local_shares) if r.local_shares else "—",
            str(r.ths_shares) if r.ths_shares else "—",
            str(r.final_shares) if r.final_shares else "—",
            f"{r.local_cost:.3f}" if r.local_shares else "—",
            f"{r.final_cost:.3f}" if r.final_shares else "—",
            r.note,
        )
    console.print(table)

    incomplete = [
        p.code for p in summary["ths_positions"].values() if p.history_incomplete
    ]
    if incomplete:
        console.print(
            f"[yellow]提示：Lscj 流水首笔为卖，底仓可能不全：{', '.join(incomplete)}[/yellow]"
        )

    positions = summary["positions"]
    if not write:
        console.print(
            f"\n[dim]预览完成（{len(positions)} 只最终持仓，{changed} 项动作非 keep）。"
            f"确认后加 [cyan]--write[/cyan] 写入 holdings.toml[/dim]"
        )
        return

    save_positions(positions)
    console.print(
        f"[green]✓ 已写入 holdings.toml，共 {len(positions)} 只持仓[/green]"
    )


# ──────────────────────────── HTML 报告 ────────────────────────────


@app.command("report")
def report_cmd(
    output: str | None = typer.Option(
        None,
        "--output",
        "-o",
        help="输出 HTML 路径（默认 notes/reports/portfolio_时间戳.html）",
    ),
    no_signals: bool = typer.Option(
        False,
        "--no-signals",
        help="不跑固定策略（更快，仅行情/盈亏/风险）",
    ),
    no_open: bool = typer.Option(
        False,
        "--no-open",
        help="不自动打开浏览器",
    ),
    days: int = typer.Option(90, "--days", help="策略技术回溯天数"),
):
    """生成持仓分析 HTML 报告（单文件，可本地打开分享）。"""
    from report.html_report import write_portfolio_report

    console.print("[dim]正在拉取持仓/行情" + (" + 策略信号…" if not no_signals else "…") + "[/dim]")
    try:
        path = write_portfolio_report(
            output,
            include_signals=not no_signals,
            days=days,
            open_browser=not no_open,
        )
    except Exception as e:
        console.print(f"[red]报告生成失败: {e}[/red]")
        raise typer.Exit(1) from e
    console.print(f"[green]✓ HTML 报告已生成[/green]\n  {path}")
    if not no_open:
        console.print("[dim]已尝试在默认浏览器中打开。[/dim]")


@app.command("serve")
def serve_cmd(
    host: str = typer.Option("127.0.0.1", "--host", help="绑定地址（默认仅本机）"),
    port: int = typer.Option(8765, "--port", "-p", help="端口"),
    no_signals: bool = typer.Option(
        False,
        "--no-signals",
        help="生成时不跑固定策略（更快）",
    ),
    days: int = typer.Option(90, "--days", help="策略技术回溯天数"),
    no_open: bool = typer.Option(False, "--no-open", help="不自动打开浏览器"),
    no_generate: bool = typer.Option(
        False,
        "--no-generate",
        help="启动时不重新生成，仅托管已有 HTML",
    ),
):
    """启动本地 HTTP 服务，在浏览器中查看/刷新持仓 HTML 报告。

    默认地址: http://127.0.0.1:8765/
    - /         最新报告
    - /refresh  重新生成
    - /history  历史时间戳报告列表
    """
    from report.server import run_server

    console.print(
        f"[cyan]TradeMind 报告服务[/cyan]  →  [bold]http://{host}:{port}/[/bold]\n"
        f"[dim]signals={'off' if no_signals else 'on'}  days={days}  "
        f"generate_on_start={not no_generate}[/dim]"
    )
    try:
        run_server(
            host=host,
            port=port,
            include_signals=not no_signals,
            days=days,
            open_browser=not no_open,
            generate_on_start=not no_generate,
        )
    except OSError as e:
        console.print(f"[red]启动失败: {e}[/red]")
        console.print("[dim]端口占用时可换: uv run trademind serve -p 8766[/dim]")
        raise typer.Exit(1) from e


# ──────────────────────────── 固定策略 ────────────────────────────


def _action_style(action: str) -> str:
    if action in ("买入", "加仓"):
        return "green"
    if action in ("卖出", "减仓", "禁止买入"):
        return "red"
    return "yellow"


@app.command("strategies")
def strategies_cmd():
    """列出固定分析策略与买卖规则。"""
    from strategy.rules import STRATEGY_CATALOG

    for s in STRATEGY_CATALOG:
        console.print(Panel(
            f"[bold]买入[/bold]：{s['buy']}\n"
            f"[bold]卖出[/bold]：{s['sell']}\n"
            f"[bold]观望[/bold]：{s['hold']}",
            title=f"{s['id']} · {s['name']}",
            border_style="blue",
        ))
    console.print("[dim]规则信号不构成投资建议[/dim]")


@app.command("backtest")
def backtest_cmd(
    code: str = typer.Argument(None, help="股票代码；不传则回测全部持仓（分票）"),
    days: int = typer.Option(250, help="回测交易日大约数"),
    fee_bps: float = typer.Option(5.0, help="单边手续费（基点）"),
):
    """用历史日 K 回测技术面 S5 规则（T 日信号，T+1 成交）。"""
    from strategy.backtest import backtest_code, backtest_portfolio_codes
    from portfolio import load_positions

    if code:
        console.print(f"[dim]回测 {code}，约 {days} 日，手续费 {fee_bps}bp…[/dim]")
        try:
            r = backtest_code(code, days=days, fee_bps=fee_bps)
        except Exception as e:
            console.print(f"[red]回测失败：{e}[/red]")
            raise typer.Exit(1)
        _print_backtest_one(r.to_dict())
        return

    positions = load_positions()
    if not positions:
        console.print("[yellow]持仓为空，请指定代码：trademind backtest 600418[/yellow]")
        raise typer.Exit(1)
    codes = [p.code for p in positions]
    console.print(f"[dim]分票回测持仓 {len(codes)} 只，约 {days} 日…[/dim]")
    out = backtest_portfolio_codes(codes, days=days, fee_bps=fee_bps)
    s = out.get("summary") or {}
    console.print(
        f"样本 [cyan]{out['count']}[/cyan] 只 | "
        f"策略均收益 [cyan]{s.get('avg_total_return', 0):.2%}[/cyan] | "
        f"买入持有均收益 [cyan]{s.get('avg_buy_hold', 0):.2%}[/cyan] | "
        f"超额均 [cyan]{s.get('avg_excess', 0):.2%}[/cyan] | "
        f"跑赢买入持有 [green]{s.get('beat_buy_hold', 0)}[/green]/{out['count']}"
    )
    table = Table(title="分票回测（按超额收益排序）", show_lines=True)
    table.add_column("代码")
    table.add_column("名称")
    table.add_column("策略收益", justify="right")
    table.add_column("买入持有", justify="right")
    table.add_column("超额", justify="right")
    table.add_column("最大回撤", justify="right")
    table.add_column("胜率", justify="right")
    table.add_column("笔数", justify="right")
    for r in out["results"]:
        ex = r["excess_return"]
        style = "green" if ex > 0 else "red"
        table.add_row(
            r["code"],
            (r.get("name") or "")[:10],
            f"{r['total_return']:.2%}",
            f"{r['buy_hold_return']:.2%}",
            f"[{style}]{ex:.2%}[/{style}]",
            f"{r['max_drawdown']:.2%}",
            f"{r['win_rate']:.1%}",
            str(r["trades"]),
        )
    console.print(table)
    if out.get("errors"):
        console.print("[yellow]失败：[/yellow] " + ", ".join(
            f"{e['code']}({e['error'][:40]})" for e in out["errors"]
        ))
    console.print(f"[dim]{out.get('disclaimer', '')}[/dim]")


def _print_backtest_one(r: dict) -> None:
    ex = r["excess_return"]
    style = "green" if ex > 0 else "red"
    console.print(Panel(
        f"区间 [cyan]{r['start']}[/cyan] → [cyan]{r['end']}[/cyan]  ({r['bars']} 日)\n"
        f"策略收益 [{style}]{r['total_return']:.2%}[/{style}]  |  "
        f"买入持有 {r['buy_hold_return']:.2%}  |  "
        f"超额 [{style}]{ex:.2%}[/{style}]\n"
        f"最大回撤 {r['max_drawdown']:.2%}  |  "
        f"交易 {r['trades']} 笔  |  胜率 {r['win_rate']:.1%}  |  "
        f"仓位暴露 {r['exposure']:.1%}\n"
        f"平均单笔 {r['avg_trade_return']:.2%}  |  手续费 {r['fee_bps']}bp",
        title=f"回测 {r['code']} {r.get('name') or ''}",
        border_style=style,
    ))
    if r.get("trade_list"):
        table = Table(title="最近交易", show_lines=True)
        table.add_column("买入日")
        table.add_column("卖出日")
        table.add_column("买价", justify="right")
        table.add_column("卖价", justify="right")
        table.add_column("收益", justify="right")
        table.add_column("持有天", justify="right")
        for t in r["trade_list"][-10:]:
            rs = "green" if t["ret"] > 0 else "red"
            table.add_row(
                t["entry_date"], t["exit_date"],
                f"{t['entry_price']:.3f}", f"{t['exit_price']:.3f}",
                f"[{rs}]{t['ret']:.2%}[/{rs}]",
                str(t["bars"]),
            )
        console.print(table)
    for n in r.get("notes") or []:
        console.print(f"[dim]• {n}[/dim]")


@app.command("signals")
def signals_cmd(
    code: str = typer.Argument(None, help="可选：单只代码；不传则评估全部持仓"),
    days: int = typer.Option(90, help="K 线天数"),
):
    """按固定策略输出买入/卖出/观望决策。"""
    if code:
        from strategy.engine import evaluate_code
        from portfolio import load_positions
        from data.source import normalize_code

        code = normalize_code(code)
        held = False
        shares = 0
        cost = 0.0
        for p in load_positions():
            if p.code == code:
                held = True
                shares = p.shares
                cost = p.cost_price
                break
        d = evaluate_code(code, held=held, shares=shares, cost_price=cost, days=days)
        style = _action_style(d.action)
        ex = d.execution or {}
        exec_lines = ""
        if ex:
            exec_lines = (
                f"\n\n[bold]执行计划[/bold]  {ex.get('side')}  "
                f"{ex.get('shares', 0)} 股（约 {float(ex.get('ratio') or 0):.0%}）  "
                f"紧急度：{ex.get('urgency')}\n"
                f"价格：{ex.get('price_hint')}\n"
            )
            for b in ex.get("batches") or []:
                exec_lines += f"  · 第{b.get('batch')}批 {b.get('shares')}股 | {b.get('when')} | {b.get('how')}\n"
        console.print(Panel(
            f"[{style}]动作：{d.action}[/{style}]  置信度：{d.confidence}  "
            f"现价：{d.price}  技术净分：{d.tech_score}\n\n"
            + "\n".join(f"• {r}" for r in d.reasons)
            + exec_lines,
            title=f"{d.code} {d.name}",
            border_style=style,
        ))
        table = Table(title="子策略明细", show_lines=True)
        table.add_column("策略")
        table.add_column("动作")
        table.add_column("理由")
        for s in d.rule_signals:
            table.add_row(s["name"], s["action"], s["reason"][:80])
        console.print(table)
        console.print("[dim]规则信号与执行计划不构成投资建议[/dim]")
        return

    from strategy.engine import evaluate_portfolio

    console.print("[dim]正在按固定策略评估全部持仓…[/dim]")
    result = evaluate_portfolio(days=days)
    if result.get("message"):
        console.print(f"[yellow]{result['message']}[/yellow]")
        return

    console.print(
        f"总市值 [cyan]{result['total_market_value']:,.0f}[/cyan]  |  "
        f"黄金主题占比 [cyan]{result['gold_theme_weight']:.1f}%[/cyan]"
    )
    summary = result.get("summary") or {}
    if summary:
        console.print("汇总：" + "  ".join(f"{k}={len(v)}" for k, v in summary.items()))

    table = Table(title="持仓策略决策", show_lines=True)
    table.add_column("代码", style="cyan")
    table.add_column("名称")
    table.add_column("现价", justify="right")
    table.add_column("动作", justify="center")
    table.add_column("建议股数", justify="right")
    table.add_column("比例", justify="right")
    table.add_column("紧急", justify="center")
    table.add_column("价格提示")
    for d in result["decisions"]:
        style = _action_style(d["action"])
        ex = d.get("execution") or {}
        table.add_row(
            d["code"],
            (d.get("name") or "")[:8],
            f"{d['price']:.3f}" if d.get("price") else "-",
            f"[{style}]{d['action']}[/{style}]",
            str(ex.get("shares", 0)),
            f"{float(ex.get('ratio') or 0):.0%}",
            str(ex.get("urgency") or "-"),
            (ex.get("price_hint") or "-")[:36],
        )
    console.print(table)

    if result.get("sell_or_reduce"):
        console.print("[red bold]优先处理（含执行量）[/red bold]")
        for x in result["sell_or_reduce"]:
            ex = x.get("execution") or {}
            console.print(
                f"  [{_action_style(x['action'])}]{x['code']} {x.get('name','')}[/{_action_style(x['action'])}]  "
                f"{x['action']} {ex.get('shares', 0)} 股（{float(ex.get('ratio') or 0):.0%}）  "
                f"{ex.get('price_hint', '')}"
            )
    if result.get("buy_or_add"):
        codes = ", ".join(f"{x['code']}({x['action']})" for x in result["buy_or_add"])
        console.print(f"[green]可考虑（买入/加仓）[/green]：{codes}")
    console.print(f"[dim]{result.get('disclaimer', '')}[/dim]")


# ──────────────────────────── chat 子命令 ────────────────────────────


def _tool_observer(name: str, args: dict) -> None:
    """工具调用时显示进度。"""
    args_str = ", ".join(f"{k}={v}" for k, v in args.items())
    console.print(f"  [dim]⚙ 调用工具 [cyan]{name}[/cyan]({args_str})[/dim]")


def _print_reply(text: str) -> None:
    """渲染 agent 回答（支持 Markdown）。"""
    console.print(Panel(Markdown(text), border_style="green", title="TradeMind"))


@app.command()
def chat(
    query: list[str] = typer.Argument(
        None, help="单次查询内容（不传则进入交互式对话）"
    ),
):
    """与 TradeMind 对话，分析股票或持仓。"""
    import tools  # noqa: F401  触发工具注册

    if query:
        # 单次查询模式
        user_input = " ".join(query)
        console.print(f"[bold]你:[/bold] {user_input}")
        try:
            reply = _ask(user_input, history=None)
            _print_reply(reply)
        except Exception as e:
            console.print(f"[red]出错：{e}[/red]")
            raise typer.Exit(1)
        return

    # 交互式对话模式
    console.print(
        Panel(
            "[bold]TradeMind 已启动[/bold]\n"
            "输入你的问题，按回车发送。输入 [cyan]exit[/cyan] 或 [cyan]quit[/cyan] 退出。\n"
            "提示：先用 [cyan]trademind portfolio add[/cyan] 添加持仓，再问「分析我的持仓」。",
            border_style="blue",
        )
    )
    history: list[dict] = []
    while True:
        try:
            user_input = console.input("[bold cyan]你>[/bold cyan] ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[dim]再见[/dim]")
            break
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit", "q"):
            console.print("[dim]再见[/dim]")
            break

        try:
            reply = _ask(user_input, history=history)
            _print_reply(reply)
            history.append({"role": "user", "content": user_input})
            history.append({"role": "assistant", "content": reply})
        except Exception as e:
            console.print(f"[red]出错：{e}[/red]")


def _ask(user_input: str, history: list[dict] | None) -> str:
    """调用 agent，统一处理异常。"""
    from agent.core import run

    return run(user_input, history=history, on_tool_call=_tool_observer)


if __name__ == "__main__":
    app()
