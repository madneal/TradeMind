"""TradeMind CLI 入口。

支持两种模式：
- 交互式多轮对话：uv run trademind
- 单次查询：uv run trademind "分析一下贵州茅台最近走势"
"""

import json

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel

app = typer.Typer(
    help="TradeMind —— A 股票分析 Agent",
    no_args_is_help=False,
    add_completion=False,
)
console = Console()


def _tool_observer(name: str, args: dict) -> None:
    """工具调用时显示进度。"""
    args_str = ", ".join(f"{k}={v}" for k, v in args.items())
    console.print(f"  [dim]⚙ 调用工具 [cyan]{name}[/cyan]({args_str})[/dim]")


def _print_reply(text: str) -> None:
    """渲染 agent 回答（支持 Markdown）。"""
    console.print(Panel(Markdown(text), border_style="green", title="TradeMind"))


@app.callback(invoke_without_command=True)
def main(
    query: list[str] = typer.Argument(
        None, help="单次查询内容（不传则进入交互式对话）"
    ),
):
    """TradeMind —— 用自然语言分析 A 股。"""
    import tools  # noqa: F401  触发工具注册

    # 单次查询模式
    if query:
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
            "输入你的问题，按回车发送。输入 [cyan]exit[/cyan] 或 [cyan]quit[/cyan] 退出。",
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
            # 维护多轮历史
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
