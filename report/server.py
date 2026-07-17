"""持仓 HTML 报告本地 HTTP 服务。

默认：
  GET /              最新报告（portfolio_latest.html）
  GET /refresh       后台快速重新生成（默认不含策略，立即返回「生成中」页）
  GET /refresh?full=1  后台完整生成（含策略信号，较慢）
  GET /history       历史报告列表
  GET /r/<name>      打开指定历史报告
  GET /health        健康检查 / 生成状态

仅绑定本地环回地址，不鉴权；勿对公网暴露。
"""

from __future__ import annotations

import json
import re
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPORTS_DIR = Path(__file__).resolve().parent.parent / "notes" / "reports"
LATEST_NAME = "portfolio_latest.html"

_regen_lock = threading.Lock()
_regen_status: dict = {
    "running": False,
    "last_error": None,
    "last_ok_at": None,
    "started_at": None,
    "mode": None,  # "fast" | "full"
    "last_elapsed_s": None,
}


def reports_dir() -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    return REPORTS_DIR


def latest_path() -> Path:
    return reports_dir() / LATEST_NAME


def list_history() -> list[dict]:
    items = []
    for p in reports_dir().glob("portfolio_*.html"):
        st = p.stat()
        items.append(
            {
                "name": p.name,
                "size": st.st_size,
                "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                "is_latest": p.name == LATEST_NAME,
            }
        )
    items.sort(key=lambda x: x["mtime"], reverse=True)
    return items


def regenerate(*, include_signals: bool = True, days: int = 90) -> Path:
    """同步生成（内部/启动用）。

    注意：长驻 serve 进程会缓存已 import 的模块。每次生成前强制 reload
    html 模板相关模块，避免「完整生成」仍写出旧版 HTML。
    """
    import importlib
    import sys
    import time as _time

    # 强制重载模板与依赖，确保磁盘上的新格式立即生效
    for mod_name in (
        "report.html_report",
        "report",
        "tools.portfolio",
        "data.industry",
    ):
        mod = sys.modules.get(mod_name)
        if mod is not None:
            try:
                importlib.reload(mod)
            except Exception as e:
                print(f"[report-server] reload {mod_name} failed: {e}")

    from report.html_report import write_portfolio_report

    # 刷新时丢掉短 TTL 行情缓存，保证「重新生成」拿到新价；随后只打 1 次批量行情
    try:
        from data.cache import invalidate_quote_cache
        from portfolio import load_positions

        invalidate_quote_cache([p.code for p in load_positions()])
    except Exception:
        pass

    t0 = _time.time()
    path = write_portfolio_report(
        None,
        include_signals=include_signals,
        days=days,
        open_browser=False,
    )
    elapsed = _time.time() - t0
    print(f"[report-server] write_portfolio_report done in {elapsed:.2f}s signals={include_signals}")
    _regen_status["last_ok_at"] = datetime.now().isoformat(timespec="seconds")
    _regen_status["last_error"] = None
    _regen_status["last_elapsed_s"] = round(elapsed, 2)
    return path


def start_regenerate_async(*, include_signals: bool = False, days: int = 90) -> bool:
    """后台生成。返回 True 表示已启动；False 表示已有任务在跑。"""
    with _regen_lock:
        if _regen_status["running"]:
            return False
        _regen_status["running"] = True
        _regen_status["last_error"] = None
        _regen_status["started_at"] = datetime.now().isoformat(timespec="seconds")
        _regen_status["mode"] = "full" if include_signals else "fast"

    def _job() -> None:
        try:
            print(
                f"[report-server] 后台生成开始 mode={_regen_status['mode']} "
                f"signals={include_signals}"
            )
            t0 = time.time()
            path = regenerate(include_signals=include_signals, days=days)
            print(f"[report-server] 后台生成完成 {time.time() - t0:.1f}s → {path}")
        except Exception as e:
            _regen_status["last_error"] = str(e)
            print(f"[report-server] 后台生成失败: {e}")
        finally:
            with _regen_lock:
                _regen_status["running"] = False

    threading.Thread(target=_job, name="report-regen", daemon=True).start()
    return True


def _busy_page(*, full: bool = False) -> str:
    mode = "完整（含策略信号）" if full else "快速（仅行情/盈亏）"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>生成中…</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f1419; color: #e7ecf3; }}
  a {{ color: #6cb6ff; }}
  .box {{ max-width: 520px; background: #1a2332; border: 1px solid #2a3340; border-radius: 12px; padding: 1.25rem 1.5rem; }}
  .muted {{ color: #9aa7b8; font-size: 0.9rem; }}
  #status {{ margin-top: 0.75rem; font-variant-numeric: tabular-nums; }}
</style>
</head>
<body>
<div class="box">
  <h1 style="margin-top:0;font-size:1.25rem">报告生成中…</h1>
  <p class="muted">模式：{mode}。页面会自动跳转，无需等待请求挂起。</p>
  <p id="status">正在启动…</p>
  <p class="muted" style="margin-bottom:0">
    <a href="/">查看当前缓存</a> ·
    <a href="/history">历史</a>
  </p>
</div>
<script>
(function () {{
  var el = document.getElementById("status");
  var n = 0;
  function tick() {{
    n += 1;
    fetch("/health", {{ cache: "no-store" }})
      .then(function (r) {{ return r.json(); }})
      .then(function (j) {{
        if (j.running) {{
          el.textContent = "生成中… " + n + "s" + (j.mode ? " (" + j.mode + ")" : "");
          setTimeout(tick, 1000);
          return;
        }}
        if (j.last_error) {{
          el.textContent = "失败：" + j.last_error;
          el.style.color = "#f6465d";
          return;
        }}
        el.textContent = "完成，正在打开报告…";
        location.replace("/");
      }})
      .catch(function () {{
        el.textContent = "等待服务… " + n + "s";
        setTimeout(tick, 1000);
      }});
  }}
  setTimeout(tick, 400);
}})();
</script>
</body>
</html>
"""


def _history_page() -> str:
    rows = []
    for it in list_history():
        tag = " <span class='tag'>latest</span>" if it["is_latest"] else ""
        rows.append(
            f"<tr><td><a href='/r/{it['name']}'>{it['name']}</a>{tag}</td>"
            f"<td>{it['mtime']}</td><td>{it['size']:,}</td></tr>"
        )
    body = (
        "\n".join(rows)
        if rows
        else "<tr><td colspan=3>暂无报告，请先 <a href='/refresh'>快速生成</a></td></tr>"
    )
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>TradeMind 报告历史</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0f1419; color: #e7ecf3; }}
  a {{ color: #6cb6ff; }}
  table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
  th, td {{ text-align: left; padding: 0.6rem 0.8rem; border-bottom: 1px solid #2a3340; }}
  th {{ color: #9aa7b8; }}
  .tag {{ background: #1f6feb; color: #fff; font-size: 0.7rem; padding: 0.1rem 0.4rem;
          border-radius: 4px; margin-left: 0.4rem; }}
  nav a {{ margin-right: 1rem; }}
  .muted {{ color: #9aa7b8; font-size: 0.9rem; }}
</style>
</head>
<body>
  <nav>
    <a href="/">最新报告</a>
    <a href="/refresh">快速重新生成</a>
    <a href="/refresh?full=1">完整生成(含策略)</a>
    <a href="/history">历史列表</a>
  </nav>
  <h1>报告历史</h1>
  <p class="muted">目录：{reports_dir()}</p>
  <table>
    <thead><tr><th>文件</th><th>修改时间</th><th>大小 (bytes)</th></tr></thead>
    <tbody>{body}</tbody>
  </table>
</body>
</html>
"""


def _error_page(title: str, detail: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"/><title>{title}</title>
<style>body{{font-family:system-ui;margin:2rem;background:#0f1419;color:#e7ecf3}}
a{{color:#6cb6ff}} pre{{background:#1a2332;padding:1rem;border-radius:8px;overflow:auto}}</style>
</head><body>
<h1>{title}</h1>
<pre>{detail}</pre>
<p><a href="/">返回</a> · <a href="/refresh">快速重试</a> · <a href="/refresh?full=1">完整生成</a></p>
</body></html>
"""


class ReportHandler(BaseHTTPRequestHandler):
    server_version = "TradeMindReport/0.2"
    include_signals: bool = True
    days: int = 90

    def log_message(self, fmt: str, *args) -> None:
        print(f"[report-server] {self.address_string()} {fmt % args}")

    def _send(self, code: int, body: bytes, content_type: str = "text/html; charset=utf-8") -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, code: int, html_str: str) -> None:
        self._send(code, html_str.encode("utf-8"))

    def _send_json(self, code: int, obj: object) -> None:
        data = json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8")
        self._send(code, data, "application/json; charset=utf-8")

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = parse_qs(parsed.query)

        if path == "/health":
            self._send_json(
                200,
                {
                    "ok": True,
                    "running": _regen_status["running"],
                    "last_ok_at": _regen_status["last_ok_at"],
                    "last_error": _regen_status["last_error"],
                    "started_at": _regen_status["started_at"],
                    "mode": _regen_status["mode"],
                    "last_elapsed_s": _regen_status.get("last_elapsed_s"),
                    "latest_exists": latest_path().is_file(),
                },
            )
            return

        if path == "/history":
            self._send_html(200, _history_page())
            return

        if path == "/api/history":
            self._send_json(200, {"reports": list_history()})
            return

        if path.startswith("/r/"):
            name = path[3:]
            if not re.fullmatch(r"portfolio_[\w.-]+\.html", name):
                self._send_html(400, _error_page("无效文件名", name))
                return
            fp = reports_dir() / name
            if not fp.is_file():
                self._send_html(404, _error_page("未找到", name))
                return
            self._send(200, fp.read_bytes())
            return

        if path in ("/refresh", "/regen"):
            # full=1 / signals=1 → 含策略（慢）；默认快速
            full = qs.get("full", ["0"])[0] in ("1", "true", "yes")
            want_signals = full or qs.get("signals", ["0"])[0] in ("1", "true", "yes")
            # 兼容旧参数 no_signals
            if qs.get("no_signals", ["0"])[0] in ("1", "true", "yes"):
                want_signals = False
            try:
                days = int(qs.get("days", [str(self.days)])[0])
            except ValueError:
                days = self.days

            if _regen_status["running"]:
                self._send_html(200, _busy_page(full=want_signals))
                return

            started = start_regenerate_async(include_signals=want_signals, days=days)
            if not started:
                self._send_html(200, _busy_page(full=want_signals))
                return
            # 立即返回，不阻塞 HTTP
            self._send_html(200, _busy_page(full=want_signals))
            return

        if path == "/":
            lp = latest_path()
            force = qs.get("refresh", ["0"])[0] in ("1", "true", "yes")
            if force:
                # 强制刷新走异步，不卡首页
                full = qs.get("full", ["0"])[0] in ("1", "true", "yes")
                if not _regen_status["running"]:
                    start_regenerate_async(include_signals=full, days=self.days)
                self._send_html(200, _busy_page(full=full))
                return

            if not lp.is_file():
                if not _regen_status["running"]:
                    start_regenerate_async(
                        include_signals=False,  # 首次用快速生成
                        days=self.days,
                    )
                self._send_html(200, _busy_page(full=False))
                return

            # 报告自带右侧操作栏，直接输出
            content = lp.read_text(encoding="utf-8")
            self._send_html(200, content)
            return

        self._send_html(404, _error_page("Not Found", path))


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    include_signals: bool = True,
    days: int = 90,
    open_browser: bool = True,
    generate_on_start: bool = True,
) -> None:
    """阻塞运行本地报告服务。"""
    ReportHandler.include_signals = include_signals
    ReportHandler.days = days

    if generate_on_start:
        # 启动时用快速生成，避免卡很久；需要策略可点「完整生成」
        print("[report-server] 启动时快速生成报告（不含策略）…")
        try:
            t0 = time.time()
            path = regenerate(include_signals=False, days=days)
            print(f"[report-server] 已生成 ({time.time() - t0:.1f}s): {path}")
        except Exception as e:
            print(f"[report-server] 启动生成失败（仍会提供已有缓存）: {e}")

    httpd = ThreadingHTTPServer((host, port), ReportHandler)
    url = f"http://{host}:{port}/"
    print(f"[report-server] 持仓报告服务已启动: {url}")
    print("[report-server] / 最新 | /refresh 快速重生成 | /refresh?full=1 含策略 | /history | /health")
    print("[report-server] Ctrl+C 停止")

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[report-server] 已停止")
    finally:
        httpd.server_close()
