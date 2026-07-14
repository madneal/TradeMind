"""配置加载：从环境变量 / .env 读取。"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── LLM：默认 xAI Grok ──
XAI_API_KEY = os.getenv("XAI_API_KEY", "")
XAI_MODEL = os.getenv("XAI_MODEL", "grok-4.5")
XAI_BASE_URL = os.getenv("XAI_BASE_URL", "https://api.x.ai/v1")

# Agent 主循环最多调用工具的次数，防止死循环
MAX_TOOL_ITERATIONS = 8

# 数据缓存库路径
DB_PATH = os.getenv("TRADEMIND_DB_PATH", "trademind.db")

# 持仓配置文件路径
HOLDINGS_PATH = os.getenv("TRADEMIND_HOLDINGS_PATH", "holdings.toml")
