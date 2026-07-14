"""TradeMind CLI 入口。

命令：
- uv run trademind chat "分析一下贵州茅台"   单次查询
- uv run trademind chat                        交互式对话
- uv run trademind portfolio list              查看持仓
- uv run trademind portfolio add 600519 100 1500.5  添加持仓
- uv run trademind portfolio remove 600519     删除持仓
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
