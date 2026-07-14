"""TradeMind CLI 入口。

命令：
- uv run trademind chat "分析一下贵州茅台"   单次查询
- uv run trademind chat                        交互式对话
- uv run trademind portfolio list              查看持仓
- uv run trademind portfolio add 600519 100 1500.5  添加持仓
- uv run trademind portfolio remove 600519     删除持仓
- uv run trademind signals                     持仓固定策略买卖清单
- uv run trademind signals 518880              单票策略决策
- uv run trademind strategies                  列出固定策略规则
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
        console.print(Panel(
            f"[{style}]动作：{d.action}[/{style}]  置信度：{d.confidence}  "
            f"现价：{d.price}  技术净分：{d.tech_score}\n\n"
            + "\n".join(f"• {r}" for r in d.reasons),
            title=f"{d.code} {d.name}",
            border_style=style,
        ))
        table = Table(title="子策略明细", show_lines=True)
        table.add_column("策略")
        table.add_column("动作")
        table.add_column("理由")
        for s in d.rule_signals:
            table.add_row(s["name"], s["action"], s["reason"])
        console.print(table)
        console.print("[dim]规则信号不构成投资建议[/dim]")
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
    table.add_column("置信度", justify="center")
    table.add_column("技术分", justify="right")
    table.add_column("主要理由")
    for d in result["decisions"]:
        style = _action_style(d["action"])
        reason = d["reasons"][0] if d.get("reasons") else ""
        table.add_row(
            d["code"],
            d.get("name") or "",
            f"{d['price']:.3f}" if d.get("price") else "-",
            f"[{style}]{d['action']}[/{style}]",
            d.get("confidence") or "",
            str(d.get("tech_score", "")),
            reason[:60],
        )
    console.print(table)

    if result.get("sell_or_reduce"):
        codes = ", ".join(f"{x['code']}({x['action']})" for x in result["sell_or_reduce"])
        console.print(f"[red]优先处理（卖出/减仓）[/red]：{codes}")
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
