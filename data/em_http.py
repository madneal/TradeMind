"""东财 HTTP 统一入口：串行限流 + 会话复用（借鉴 a-stock-data / Vibe-Research）。

所有 eastmoney.com 请求应走 em_get()，避免高频触发 IP 风控。
"""

from __future__ import annotations

import random
import threading
import time

import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

EM_SESSION = requests.Session()
EM_SESSION.headers.update({"User-Agent": UA})

try:
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry

    _adapter = HTTPAdapter(
        max_retries=Retry(
            total=3,
            connect=3,
            backoff_factor=0.6,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
    )
    EM_SESSION.mount("https://", _adapter)
    EM_SESSION.mount("http://", _adapter)
except Exception:
    pass

# 两次东财请求最小间隔（秒）；批量场景可调大
EM_MIN_INTERVAL = 1.0
_lock = threading.Lock()
_last_call = 0.0


def em_get(
    url: str,
    params: dict | None = None,
    headers: dict | None = None,
    timeout: int = 15,
    **kwargs,
) -> requests.Response:
    """东财统一 GET：自动节流 + 复用 session + 默认 UA。"""
    global _last_call
    with _lock:
        wait = EM_MIN_INTERVAL - (time.time() - _last_call)
        if wait > 0:
            time.sleep(wait + random.uniform(0.05, 0.35))
        try:
            hdrs = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
            if headers:
                hdrs.update(headers)
            return EM_SESSION.get(
                url, params=params, headers=hdrs, timeout=timeout, **kwargs
            )
        finally:
            _last_call = time.time()
