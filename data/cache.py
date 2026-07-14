"""SQLite 缓存层：避免重复请求 AKShare 被限流。

历史 K 线按交易日缓存（过去的数据不会变），实时行情短缓存。
"""

import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from config import DB_PATH

# 实时行情缓存有效期（秒）
QUOTE_TTL = 60
# 历史K线缓存有效期（秒）—— 历史数据不变，缓存 1 天
KLINE_TTL = 86400


def _get_conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db() -> None:
    conn = _get_conn()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS kline_cache (
            code TEXT NOT NULL,
            period TEXT NOT NULL,
            adjust TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (code, period, adjust)
        );
        CREATE TABLE IF NOT EXISTS quote_cache (
            code TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (code)
        );
        CREATE TABLE IF NOT EXISTS fund_cache (
            code TEXT NOT NULL,
            fetched_at REAL NOT NULL,
            data_json TEXT NOT NULL,
            PRIMARY KEY (code)
        );
        """
    )
    conn.close()


# 财务指标缓存（季频数据，默认 7 天）
FUND_TTL = 7 * 86400


def get_fund_cache(code: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT fetched_at, data_json FROM fund_cache WHERE code=?", (code,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    fetched_at, data_json = row
    if time.time() - fetched_at > FUND_TTL:
        return None
    import json

    return json.loads(data_json)


def set_fund_cache(code: str, data: dict) -> None:
    import json

    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO fund_cache (code, fetched_at, data_json) VALUES (?,?,?)",
        (code, time.time(), json.dumps(data, default=str)),
    )
    conn.commit()
    conn.close()


_init_db()


def get_kline_cache(code: str, period: str, adjust: str) -> pd.DataFrame | None:
    """命中且未过期返回 DataFrame，否则 None。"""
    conn = _get_conn()
    row = conn.execute(
        "SELECT fetched_at, data_json FROM kline_cache WHERE code=? AND period=? AND adjust=?",
        (code, period, adjust),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    fetched_at, data_json = row
    if time.time() - fetched_at > KLINE_TTL:
        return None
    import json

    records = json.loads(data_json)
    return pd.DataFrame(records)


def set_kline_cache(code: str, period: str, adjust: str, df: pd.DataFrame) -> None:
    import json

    records = df.to_dict(orient="records")
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO kline_cache (code, period, adjust, fetched_at, data_json) VALUES (?,?,?,?,?)",
        (code, period, adjust, time.time(), json.dumps(records, default=str)),
    )
    conn.commit()
    conn.close()


def get_quote_cache(code: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT fetched_at, data_json FROM quote_cache WHERE code=?", (code,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    fetched_at, data_json = row
    if time.time() - fetched_at > QUOTE_TTL:
        return None
    import json

    return json.loads(data_json)


def set_quote_cache(code: str, data: dict) -> None:
    import json

    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO quote_cache (code, fetched_at, data_json) VALUES (?,?,?)",
        (code, time.time(), json.dumps(data, default=str)),
    )
    conn.commit()
    conn.close()
